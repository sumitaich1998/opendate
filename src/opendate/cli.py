"""OpenDate command-line interface (``python -m opendate ...``).

Commands
--------
* ``init``       — write example config + .env into the current directory
* ``providers``  — list every supported LLM provider
* ``skills``     — list the loaded dating skills
* ``persona``    — build the user's persona profile from posts/chats
* ``screen``     — preview like/pass decisions on recommendations
* ``run``        — start the runtime loop

Use ``--mock`` (a global flag) anywhere to run fully offline with the mock
connector and a stub LLM — no real credentials required.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import (
    EXAMPLE_CONFIG_YAML,
    EXAMPLE_ENV,
    AppConfig,
    load_config,
    load_secrets,
)
from .connectors.base import build_connector
from .llm.providers import list_providers, provider_ready
from .llm.router import LLMRouter
from .orchestrator.loop import Orchestrator, score_candidate
from .orchestrator.safety import SafetyGuard
from .persona.analyze import PersonaProfile, build_persona, load_profile
from .skills.engine import SkillsEngine
from .utils.logging import configure_logging, get_logger

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="OpenDate — a vibe-dating AI agent. Use --mock to run offline.",
)
persona_app = typer.Typer(help="Build and inspect your persona profile.")
app.add_typer(persona_app, name="persona")

console = Console()
log = get_logger("cli")


@dataclass
class State:
    config_path: Optional[Path]
    env_file: Path
    mock: bool


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"OpenDate {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to config YAML (defaults are auto-found)."
    ),
    env_file: Path = typer.Option(
        Path(".env"), "--env", help="Path to the .env file with secrets."
    ),
    mock: bool = typer.Option(
        False, "--mock", help="Use the offline mock connector + stub LLM."
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level."),
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    configure_logging(log_level.upper())
    ctx.obj = State(config_path=config, env_file=env_file, mock=mock)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_config(state: State) -> AppConfig:
    return load_config(state.config_path)


def _build_router(state: State, config: AppConfig) -> tuple[LLMRouter, object]:
    secrets = load_secrets(state.env_file)
    router = LLMRouter.from_config(config.llm, secrets.env_map(), stub=state.mock)
    if not state.mock:
        router.ensure_ready(secrets.env_map())
    return router, secrets


def _load_or_build_persona(config: AppConfig, router: LLMRouter) -> PersonaProfile:
    path = Path(config.persona.profile_path)
    if path.exists():
        try:
            return load_profile(path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load persona profile %s: %s", path, exc)
    return build_persona(
        config.persona, voice=config.preferences.voice, router=router
    )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
@app.command()
def init(
    directory: Path = typer.Argument(
        Path("."), help="Where to write config.yaml and .env."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Write a starter ``config.yaml`` and ``.env`` you can fill in."""
    directory.mkdir(parents=True, exist_ok=True)
    targets = {
        directory / "config.yaml": EXAMPLE_CONFIG_YAML,
        directory / ".env": EXAMPLE_ENV,
    }
    for path, content in targets.items():
        if path.exists() and not force:
            console.print(f"[yellow]skip[/] {path} (exists; use --force)")
            continue
        path.write_text(content, encoding="utf-8")
        console.print(f"[green]wrote[/] {path}")
    console.print(
        "\nNext: put your secrets in [bold].env[/], edit [bold]config.yaml[/], "
        "then run [bold]opendate --mock run[/] to try it offline."
    )


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------
@app.command()
def providers(ctx: typer.Context) -> None:
    """List every supported LLM provider (Western + Chinese)."""
    state: State = ctx.obj
    try:
        secrets = load_secrets(state.env_file)
        env_map = secrets.env_map()
    except Exception:  # noqa: BLE001
        env_map = None

    table = Table(title="Supported LLM providers", show_lines=False)
    table.add_column("Key", style="bold cyan")
    table.add_column("Provider")
    table.add_column("Region")
    table.add_column("Mode")
    table.add_column("API key env")
    table.add_column("Default model")
    table.add_column("Cfg", justify="center")

    for region in ("Western", "Chinese"):
        for spec in list_providers(region=region):  # type: ignore[arg-type]
            ready = provider_ready(spec.key, env_map) if env_map is not None else False
            table.add_row(
                spec.key,
                spec.label,
                spec.region,
                spec.mode,
                spec.api_key_env,
                spec.default_model,
                "[green]✓[/]" if ready else "[dim]—[/]",
            )
    console.print(table)
    console.print(
        f"[dim]{len(list_providers())} provider routes. "
        "Set the matching API key env var (see .env.example), then select one "
        "in config.yaml under llm.provider.[/]"
    )


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------
@app.command()
def skills(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show playbooks."),
) -> None:
    """List the loaded dating skills."""
    engine = SkillsEngine()
    loaded = engine.load_all()
    table = Table(title=f"Loaded skills ({len(loaded)})")
    table.add_column("Skill", style="bold cyan")
    table.add_column("Category")
    table.add_column("Fires when")
    table.add_column("What it does", overflow="fold", max_width=60)
    for name in sorted(loaded):
        s = loaded[name]
        table.add_row(s.name, s.category or "-", s.fires_when or "-", s.description)
    console.print(table)
    if verbose:
        for name in sorted(loaded):
            console.print(
                Panel(loaded[name].body, title=name, border_style="magenta")
            )


# ---------------------------------------------------------------------------
# persona build
# ---------------------------------------------------------------------------
@persona_app.command("build")
def persona_build(ctx: typer.Context) -> None:
    """Ingest your posts/chats and build a persona profile."""
    state: State = ctx.obj
    config = _load_config(state)
    router, _ = _build_router(state, config)
    profile = build_persona(
        config.persona,
        voice=config.preferences.voice,
        router=router,
        save_path=config.persona.profile_path,
    )
    console.print(
        Panel(
            profile.style_brief(),
            title="Persona profile",
            border_style="blue",
        )
    )
    console.print(
        f"[green]Saved[/] persona to {config.persona.profile_path} "
        f"(LLM-refined: {profile.generated_with_llm})"
    )


@persona_app.command("show")
def persona_show(ctx: typer.Context) -> None:
    """Show the saved persona profile."""
    state: State = ctx.obj
    config = _load_config(state)
    path = Path(config.persona.profile_path)
    if not path.exists():
        console.print(f"[yellow]No persona at {path}. Run `opendate persona build`.[/]")
        raise typer.Exit(code=1)
    profile = load_profile(path)
    console.print(Panel(profile.style_brief(), title="Persona", border_style="blue"))


# ---------------------------------------------------------------------------
# screen
# ---------------------------------------------------------------------------
@app.command()
def screen(
    ctx: typer.Context,
    limit: int = typer.Option(10, "--limit", help="How many candidates to screen."),
) -> None:
    """Preview like/pass decisions on current recommendations (read-only)."""
    state: State = ctx.obj
    config = _load_config(state)
    secrets = load_secrets(state.env_file)
    connector = build_connector(config, secrets, force_mock=state.mock)

    async def _run() -> None:
        try:
            candidates = await connector.get_recommendations(limit)
            table = Table(title="Screening preview")
            table.add_column("Candidate", style="bold")
            table.add_column("Age")
            table.add_column("Decision")
            table.add_column("Score")
            table.add_column("Why", overflow="fold", max_width=60)
            for cand in candidates:
                decision, score, reasons, _ = score_candidate(
                    cand, config.preferences
                )
                color = "green" if decision == "like" else "red"
                table.add_row(
                    cand.name or cand.id,
                    str(cand.age or "-"),
                    f"[{color}]{decision}[/]",
                    str(score),
                    "; ".join(reasons),
                )
            console.print(table)
        finally:
            await connector.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
@app.command()
def run(
    ctx: typer.Context,
    cycles: int = typer.Option(1, "--cycles", help="Loop cycles (0 = run forever)."),
    interval: Optional[float] = typer.Option(
        None, "--interval", help="Seconds between cycles (defaults to config)."
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        help="Prompt before sending. --no-interactive never sends (dry run).",
    ),
    auto_send: Optional[bool] = typer.Option(
        None,
        "--auto-send/--no-auto-send",
        help="Override config auto_send (send without asking).",
    ),
    provider: Optional[str] = typer.Option(None, "--provider", help="Override LLM provider."),
    model: Optional[str] = typer.Option(None, "--model", help="Override LLM model."),
) -> None:
    """Run the OpenDate loop: Sync → Screen → Decide → Generate → Voice → Guard → Act."""
    state: State = ctx.obj
    config = _load_config(state)
    if provider:
        config.llm.provider = provider
    if model:
        config.llm.model = model
    if auto_send is not None:
        config.auto_send = auto_send

    router, secrets = _build_router(state, config)
    connector = build_connector(config, secrets, force_mock=state.mock)
    engine = SkillsEngine()
    engine.load_all()
    persona = _load_or_build_persona(config, router)
    guard = SafetyGuard(
        config.safety,
        router=router,
        guidance=(engine.get_or_none("consent-and-safety").body if engine.get_or_none("consent-and-safety") else ""),
    )

    orchestrator = Orchestrator(
        connector=connector,
        router=router,
        skills=engine,
        persona=persona,
        config=config,
        safety=guard,
        console=console,
        interactive=interactive,
    )

    mode = "MOCK" if state.mock else config.source.upper()
    send_mode = (
        "auto-send ON" if config.auto_send else "human-in-the-loop (no auto-send)"
    )
    console.print(
        Panel(
            f"Source: [bold]{mode}[/]   LLM: [bold]{router.primary_label}[/]"
            f"{' (stub)' if router.is_stub else ''}\n"
            f"Mode: {send_mode}   Interactive: {interactive}",
            title="OpenDate run",
            border_style="bold magenta",
        )
    )

    async def _run() -> None:
        try:
            await orchestrator.run(cycles=cycles, interval=interval or config.poll_interval)
        finally:
            await connector.close()

    asyncio.run(_run())


def main_entry() -> None:
    """Console-script / ``python -m opendate`` entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main_entry()

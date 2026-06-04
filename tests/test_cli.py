"""CLI tests via Typer's CliRunner (offline; --mock everywhere it touches I/O)."""

from __future__ import annotations

from typer.testing import CliRunner

from opendate.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "OpenDate" in result.stdout


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "OpenDate" in result.stdout


def test_providers_lists_both_regions():
    result = runner.invoke(app, ["providers"])
    assert result.exit_code == 0
    assert "openai" in result.stdout
    assert "deepseek" in result.stdout
    assert "Chinese" in result.stdout


def test_skills_lists_fourteen():
    result = runner.invoke(app, ["skills"])
    assert result.exit_code == 0
    assert "14" in result.stdout
    assert "opener" in result.stdout
    assert "consent-and-safety" in result.stdout


def test_init_writes_files(tmp_path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / ".env").exists()


def test_mock_run_dry(tmp_path):
    # Run a single offline cycle that proposes but never sends.
    result = runner.invoke(
        app,
        ["--mock", "run", "--cycles", "1", "--no-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    assert "OpenDate run" in result.stdout


def test_mock_screen():
    result = runner.invoke(app, ["--mock", "screen"])
    assert result.exit_code == 0
    assert "Screening preview" in result.stdout

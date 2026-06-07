# Changelog

All notable changes to OpenDate are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-07

Initial public release.

### Added

- **Multi-provider LLM router** built on `litellm` covering 19 provider routes —
  10 Western (OpenAI, Anthropic, Google Gemini, xAI Grok, Groq, Together,
  Mistral, Cohere, AWS Bedrock, Azure OpenAI) and 9 Chinese (DeepSeek, Alibaba
  Qwen, Zhipu GLM, Moonshot Kimi, Baidu ERNIE, 01.AI Yi, MiniMax, Tencent
  Hunyuan, ByteDance Doubao). Adding a provider is a single registry entry.
- Router resilience: timeouts, exponential-backoff retries, an ordered fallback
  model chain, a structured-JSON helper with safe parsing, and token-usage
  accounting. Deterministic offline stub LLM for demos and tests.
- **Connectors** behind a swappable `MatchSource` interface: a `tinder`
  connector (`httpx`, unofficial endpoints) with retry/backoff and pagination,
  and a `mock` connector for fully offline runs.
- **14 dating skills** in the agentskills.io `SKILL.md` format: profile-screening,
  opener, approaching, flirting, banter, rapport-building, storytelling,
  proposing-a-date, number-exchange, re-engagement, conversation-recovery,
  relationship-intent-matching, persona-style-transfer, and consent-and-safety.
- **Skills engine** with stage- and signal-aware, explainable skill selection
  and always-active modifiers.
- **Personality engine** that learns the user's voice from social posts and past
  chats (tone, vocabulary, emoji/punctuation rate, length/cadence, humor,
  go-to openers), produces a voice card, and powers style transfer. Degrades
  gracefully to heuristics with no LLM.
- **Async orchestrator** implementing the Sync to Screen to Decide to Generate to
  Voice to Guard to Act loop, with conversation memory + a stage machine,
  per-match error isolation, match prioritization, pacing/cooldowns, a daily
  action cap, a no-double-text rule, a dry-run plan, and structured decision
  logging.
- **Safety guard** as a blocking gate before every send: refuses deception,
  coercion/pressure, and explicit content (unless explicitly allowed), backs off
  on disinterest/discomfort, and hard-blocks possible-minor signals.
- **Message-quality critic** that scores drafts for genericness, cringe,
  repetition, and energy/length mismatch and regenerates weak drafts once.
- **Typer CLI** (`opendate`): `init`, `providers`, `skills`, `persona build/show`,
  `screen`, and `run`, plus a global `--mock` flag for keyless offline runs.
- Configuration via `config.yaml` + `.env`, with secret redaction in logs.
- Fully offline `pytest` suite and example posts/chats for persona building.

[Unreleased]: https://github.com/sumitaich1998/OpenDate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sumitaich1998/OpenDate/releases/tag/v0.1.0

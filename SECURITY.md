# Security Policy

OpenDate handles sensitive credentials (your Tinder token and LLM API keys) and
personal data (your persona, learned from your posts and chats). We take that
seriously.

## Supported versions

OpenDate is pre-1.0 and moves quickly. Security fixes target the latest `main`.

| Version | Supported |
| --- | --- |
| `main` (latest) | ✅ |
| older tags | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Instead, report privately via GitHub's
[Security Advisories](https://github.com/sumitaich1998/OpenDate/security/advisories/new)
for this repository, or contact the maintainer through their GitHub profile
([@sumitaich1998](https://github.com/sumitaich1998)).

When reporting, please include:

- A description of the issue and its impact.
- Steps to reproduce (a minimal proof of concept if possible).
- Any suggested remediation.

We'll acknowledge your report as soon as we can, keep you updated on progress,
and credit you (if you'd like) once a fix ships.

## Never commit secrets

- Keep your `TINDER_AUTH_TOKEN` and LLM API keys in `.env` only — it is
  git-ignored. Never paste real tokens into issues, PRs, logs, or screenshots.
- OpenDate's logging layer has an active redaction filter that masks secrets, but
  treat that as a safety net, not a license to be careless.
- Persona artifacts (`persona.json`) and conversation state (`data/`) may contain
  personal data and are git-ignored. Keep them private.
- If you accidentally expose a credential, **revoke/rotate it immediately**
  (re-authenticate on Tinder, regenerate the LLM key) and scrub it from history.

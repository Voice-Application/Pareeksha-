# Pareeksha

India-native crash-testing and call-audit platform for voice AI agents. Synthetic Indian callers (Kannada, Hindi, Hinglish/Kanglish, noisy phone lines) test a voice bot before launch; the same judge audits real calls after launch; a dialect report shows where speech recognition breaks; results flow to HubSpot, webhooks and CI.

Status: build in progress (spec v0.2). Live task board: [STATUS.md](STATUS.md). Full spec: [docs/README.md](docs/README.md).

## Quick start
Written in DOC-02 and tested from a clean clone. Target: first evaluated call in under 20 minutes.

## Architecture
Written in DOC-02 (diagram from `docs/04-system-design.md`).

## Guides
The 8 adopter guides (`docs/10-integrations-and-dx.md` §7) are written in DOC-02.

## Limitations
Written in DOC-02 from QA-05 results.

## Contributing and agents
Multi-agent build rules: [docs/AGENTS.md](docs/AGENTS.md). Contract changes are logged in [CHANGELOG.md](CHANGELOG.md).

## Safety
Secrets only in `.env` (never committed; see `.env.example`). Fixtures are synthetic; voice and dialect clips require consent.

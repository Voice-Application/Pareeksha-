# DOC-02 proof

## Built
- `README.md`: quick start, mermaid architecture, guide index, honest limitations.
- `docs/guides/01..08` (the 8 adopter guides of `docs/10 §7`) and `docs/guides/sdk-reference.md`; `examples/connector-slack/` (guide 7's one-file connector, tests, compose overlay).
- Docs updated for build decisions: `docs/README.md` (DeepSeek default + Gemini optional, pluggable speech providers with keys pending, SDK import `pareeksha_sdk`, `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS`, no `make demo`), `docs/10`, `docs/03`, `docs/02`, `CHANGELOG.md`.
- Product-side fixes found while following the guides: `.env.example` (trailing comment after an empty value was read as the value by Compose; `MOCK_BUGS` crashed the mock agent), `docker-compose.yml` (overridable host ports, `host.docker.internal` for backend services), `docker-compose.proxy.yml` (CA also at run time), `examples/pipecat-bot/requirements.txt`.

## How verified
Each guide was followed from a fresh `git clone -b task/DOC-02` in a scratch dir with a private compose project (`doc02a`) on non-default ports (API 18000, web 13000, Postgres 15432, Kafka 19094, mock agent 18765), sandbox proxy overlay `docker-compose.proxy.yml`. Logs: `proof/DOC-02/guides/<n>.log` (1 quickstart, 2 Pipecat, 3 any bot, 4 webhook source, 5 HubSpot, 6 GitHub Action, 7 connector, 8 Kafka). Keys came from the environment and were never printed.

## Result per guide
See the `RESULT:` line at the end of each log.

## Not covered / honest notes
- Guide 5 live step pending owner HubSpot token; guide 4's outbound sink delivery to a real receiver not exercised (INT-01 tests cover it). Guide 1 step 5 (planted bug) not run live. Cold-build time for NFR-14 not measured (cached layers).
- Guide 6 was run as the action's steps by hand (no GitHub runner here).
- Docker Hub rate-limited the sandbox (429); images were pulled via `mirror.gcr.io` and retagged. Not a product issue.

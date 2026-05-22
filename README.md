# Palestine Issue Signal Dashboard

Local-first MVP for collecting authorized Palestine-related text signals and reviewing recurring actionable problems.

## Stack

- FastAPI API and Python worker.
- PostgreSQL with `pgvector` enabled and a full-text index over retained evidence text.
- React/Vite dashboard on localhost.
- Connector slots for Telegram, Discord, Facebook, and RSS/Atom news.

## Run locally

1. Copy `.env.example` to `.env` and fill the connector credentials you have.
2. Start the stack:

   ```sh
   docker compose up --build
   ```

3. Open the dashboard at `http://127.0.0.1:5173`.
4. API docs are available at `http://127.0.0.1:18000/docs`.

The worker queues scheduled `ingest`, `discover`, and `retention` runs every 60 minutes by default. The dashboard can queue manual collection, discovery, and retention runs.
PostgreSQL is exposed to the host on `127.0.0.1:55432` and the API on `127.0.0.1:18000` by default so the stack does not collide with common local Postgres or API ports.

## Source setup

### Telegram

Telegram uses a user session with official API credentials. Fill `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`, then authorize the session once:

```sh
docker compose run --rm api python -m app.telegram_login
```

Add approved public or joined Telegram channels/groups by username, chat ID, or `t.me` URL. Discovery searches the configured Telegram queries and sends candidates to review before ingestion.

### Discord

Discord uses a bot token. Add whitelisted text-channel IDs as Discord sources after the bot has access to those channels and message history. A full channel URL such as `https://discord.com/channels/<server-id>/<channel-id>` is also accepted. Server URLs and `@home` URLs do not identify a collectable channel. Missing permissions become connector health states instead of hidden failures.

### Facebook

Facebook is intentionally gated in this MVP. The dashboard accepts Facebook source records, but the connector does not automate browser scraping or bypass Meta access controls. Add an approved Meta access implementation before expecting live Facebook collection.

### News

Add publisher-permitted RSS or Atom feeds as news sources. `NEWS_DISCOVERY_FEED_URLS` accepts comma-separated discovery feeds; feeds with configured Palestine keyword matches become review candidates.

## Data behavior

- Stores normalized evidence text, source provenance, connector cursors, issue clusters, scores, and time-series counts.
- Does not store raw social payload archives or author identity fields.
- Expires retained evidence text after 90 days by default while issue aggregates remain.
- Text-only MVP: captions/titles/text are eligible; OCR, audio transcription, image analysis, and video analysis are deferred.
- Hosted AI hooks receive minimized snippets only. The default MVP scoring path is deterministic keyword/topic clustering until an approved hosted AI analysis client is configured.

## API surface

- `GET/POST/PATCH/DELETE /api/sources`
- `POST /api/runs`, `GET /api/runs`
- `GET /api/discovery-candidates`
- `POST /api/discovery-candidates/{id}/review`
- `GET /api/issues`, `GET /api/issues/{id}`

## Backend tests

```sh
python -m venv .venv
.venv/bin/pip install -e "backend[test]"
.venv/bin/pytest backend
```

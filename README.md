# Veloxi Engine

A pipeline and API that discovers, verifies, normalizes and serves **real**
learning and career opportunities (courses, certifications, jobs, scholarships,
research programs, summer schools) from trusted providers.

Raw items land in a staging table, get classified (a deterministic heuristic by
default, optionally refined by an LLM), deduplicated by canonical URL, scored for
freshness and quality, and published to a searchable index. A validation daemon
keeps the index honest by pinging live links and retiring dead or expired ones. A
skills graph links every opportunity to the skills it teaches, which powers
explainable recommendations and a Career Agent that turns a CV into a learning
roadmap.

```
sources ──probe──▶ verify_source ──▶ VERIFIED
   └─▶ raw_opportunities (PENDING) ──▶ approval queue (optional)
        └─▶ normalize: canonicalize URL ▶ classify ▶ dedupe ▶ freshness + quality score
             └─▶ opportunities (is_active) ──serve──▶ /api/opportunities, /api/recommendations
                  ├─▶ skills graph ──▶ Career Agent: CV ▶ skills ▶ gap ▶ courses ▶ roadmap
                  └─▶ validation daemon: ping URLs, log results, retire dead / expired links
```

Everything runs offline with no API keys. Network access and LLMs are opt-in.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional; defaults work out of the box

python -m app.cli seed          # ~180 real opportunities in 26 categories, plus the skills graph
python -m app.cli serve         # http://localhost:8000/docs
```

Try the Career Agent from the command line:

```bash
python -m app.cli career cv.pdf --goal "data analyst"        # PDF, DOCX or text
echo "Skills: Python, SQL, Excel" | python -m app.cli career - --goal "data analyst"
```

```
Goal: data analyst
You have: Excel, Python, SQL
Gap:      Data Visualization, Data Analysis, DAX
  1. Microsoft Power BI Data Analyst (PL-300) (Microsoft, Intermediate)
     covers: DAX, Data Analysis, Data Visualization
```

## CLI

| Command | What it does |
|---|---|
| `init-db` | Create the tables |
| `seed` | Load the built-in sources, opportunities and skills graph (idempotent) |
| `ingest [--source ID]` | Fetch every enabled source (or one), stage, classify and promote |
| `validate [--loop]` | Ping active URLs, log results, expire or disable dead links |
| `career CV [--goal G] [--json]` | Run the Career Agent on a CV file, or `-` for stdin |
| `serve [--port N]` | Run the API with uvicorn |

## API

Interactive docs at `/docs`.

### Public (read-only)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/opportunities` | Filter with `q, category, kind, max_cost, free_only, difficulty, certificate_only, provider, skill, sort, limit, offset` |
| GET | `/api/opportunities/{id}` | One active opportunity |
| GET | `/api/categories` | Live counts per category, grouped into sections |
| GET | `/api/providers` | Live counts per provider |
| GET | `/api/skills` | Most-taught skills in the graph |
| GET | `/api/recommendations?goal=...` | Ranked results, each with a plain-language explanation |
| GET | `/api/stats` | Active counts, verified in the last 24h, source health |
| GET | `/health` | Liveness and version |

### Admin

Send the `X-Admin-Token` header. **The admin API stays locked until `ADMIN_TOKEN`
is set**, so a deployment never runs with a guessable default.

| Area | Endpoints |
|---|---|
| Sources | `GET/POST /admin/sources`, `PATCH/DELETE /admin/sources/{id}`, `POST /admin/sources/{id}/probe`, `POST /admin/sources/{id}/ingest`, `POST /admin/ingest` |
| Approval queue | `GET /admin/queue`, `POST /admin/queue/{id}/approve`, `POST /admin/queue/{id}/reject` |
| Opportunities | `POST /admin/opportunities` (manual submission), `DELETE /admin/opportunities/{id}`, `POST /admin/reseed` |
| Health | `GET /admin/logs/ingestion`, `GET /admin/logs/validation`, `GET /admin/stale`, `POST /admin/validate`, `GET /admin/alerts` |
| Career Agent | `POST /admin/career/analyze` (CV text), `POST /admin/career/analyze-file` (PDF/DOCX/TXT upload), `GET /admin/career/reports` |

CVs are processed in memory and never stored. Only the derived result (skills,
gap, recommended opportunity ids) is persisted.

## Sources

Add sources through the admin API or in `app/seed/sources_seed.py`. The seed ships
ready-to-enable examples, all disabled so nothing touches the network until you
opt in: freeCodeCamp (RSS), dev.to (RSS), We Work Remotely (RSS, jobs), RemoteOK
(JSON API) and an Apify actor.

| Type | `config` keys |
|---|---|
| `rss` | `default_category, default_cost, default_certificate, default_audit, default_duration, default_tags, auto_promote` |
| `api` (JSON) | `items_path` (omit for a top-level array), `title_field, url_field, id_field, description_field` |
| `apify` | `actor_id, input`, plus the same field mapping as `api`. Needs `APIFY_TOKEN` |
| `manual` | Admin submissions via `POST /admin/opportunities` |

With `auto_promote: false`, items go to the approval queue instead of straight to
the public index.

Apify is paid and usage-based, and some sites restrict scraping in their terms.
Prefer official APIs and RSS feeds where they exist.

### Try live ingestion locally

```bash
python -m http.server 9000 -d examples &          # serves examples/sample-feed.xml
export ADMIN_TOKEN=dev-token
python -m app.cli serve &
curl -X POST localhost:8000/admin/sources -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Sample","type":"rss","url":"http://127.0.0.1:9000/sample-feed.xml","config":{"auto_promote":true}}'
curl -X POST localhost:8000/admin/ingest -H "X-Admin-Token: $ADMIN_TOKEN"
```

## Optional LLM

Classification and the Career Agent are fully deterministic without a key. To let
an LLM refine classification and CV skill extraction, set in `.env`:

```
LLM_PROVIDER=anthropic        # or: openai | gemini
ANTHROPIC_API_KEY=...
```

and install the matching client (`anthropic` is in `requirements.txt`; `pip install
openai` or `google-generativeai` for the others). The LLM only refines a validated
result, and on any error the pipeline falls back to the heuristic. Reading scanned
PDF CVs uses Claude's PDF support and needs `LLM_PROVIDER=anthropic`.

## Deploy

The engine is a single always-on process: FastAPI serves the API, and an
in-process scheduler runs ingestion and validation when `INGEST_ENABLED=true`. It
needs a container host, not a serverless platform.

```bash
docker build -t veloxi-engine .
docker run -p 8000:8000 -e ADMIN_TOKEN=... -e DATABASE_URL=postgresql://... veloxi-engine
docker run --rm -e DATABASE_URL=postgresql://... veloxi-engine python -m app.cli seed   # once
```

- Use Postgres in production (`DATABASE_URL`). `postgres://` URLs are normalized
  automatically. SQLite works only with a persistent volume.
- Run **one replica** while the scheduler is in-process, or move `ingest` and
  `validate` to a separate cron job and leave `INGEST_ENABLED=false` on the web tier.

## Layout

```
app/
  main.py          FastAPI app; starts the scheduler only if INGEST_ENABLED
  cli.py           command-line interface
  config.py db.py models.py schemas.py deps.py
  pipeline/        canonicalize · classify · llm · dedupe · freshness · quality · promote · verify_source · opportunity_filter
  ingest/          adapter registry · rss · api_json · apify · scraper · manual · runner
  daemon/          validation (ping / expire / disable) · scheduler (APScheduler)
  services/        opportunities · recommend · stats · career · cv_extract · alerts
  seed/            real opportunities, sources and skills graph, idempotent loader
  routers/         public · admin
examples/          sample RSS feed for local ingestion
tests/             offline, deterministic: pipeline, adapters, API, seed, Career Agent
```

```bash
pip install pytest && python -m pytest
```

## License

[Apache-2.0](LICENSE)

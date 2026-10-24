# Decisions and Repository Guide

A map for reviewers and contributors: what the project does, where code lives, and why the major choices were made.

## Product summary
Ride-The-Trends collects public YouTube and Bluesky trend signals, validates candidates with deterministic SQL/dbt logic, then helps a human draft and review creative hooks. AI does not decide whether a trend is real; it is used only after a trend has passed data validation.

## Repository map

| Folder/file | Purpose | Entry points |
|---|---|---|
| `1_ingestion/` | Provider API collectors and orchestration | `worker.py`, `base_scraper.py`, `youtube_scraper.py`, `bluesky_scraper.py` |
| `2_transformations/` | dbt staging, validation, feedback adjustment, and prompt mart | `dbt_project.yml`, `models/staging/`, `models/intermediate/`, `models/marts/` |
| `3_app/` | Streamlit operator-facing UI | `app.py`, `pages/1_Trend_Discovery.py`, `pages/2_Audit_Hub.py`, `pages/3_Observability.py` |
| `3_app/utils/` | Creative generation and critic inference | `llm_engine.py` |
| `core/` | Config, SQLAlchemy pool, Bronze writes, scraper factory, logging, exceptions | `config.py`, `database.py`, `factory.py`, `logging.py`, `exceptions.py` |
| `scripts/` | Feedback-driven critic model training | `retrain_bert.py` |
| `tests/` | Connectivity checks | `connectivity_check.py` |
| `.github/workflows/` | Scheduled ingestion and smoke-check automation | `ingestion.yml`, `smoke-test.yml` |
| `README.md` | Install, run, configuration, schema, and security instructions | Start here to operate the app |

## End-to-end data flow

1. Hourly GitHub Actions invokes `1_ingestion/worker.py`.
2. Scrapers call YouTube Data API v3 and Bluesky `searchPosts`, normalize useful fields, and preserve provider context.
3. `core/database.py` writes JSONB payloads to `bronze.raw_ingestion` and reports attempted, inserted, and duplicate counts.
4. dbt staging models extract typed fields; intermediate models calculate deterministic validation and feedback adjustments; the analytics mart exposes prompt records.
5. Streamlit Discovery reads validated prompts, generates hooks with Ollama or optional OpenAI fallback, and scores each candidate with a cached DistilBERT critic.
6. Human feedback is stored in `gold.human_feedback`; the scheduled retraining script can update the critic when enough eligible labels exist.
7. Observability reports database health, provider-level ingestion freshness and row counts, recent source IDs, feedback totals, and prompt totals without exposing raw post text.

## Engineering decisions

### Deterministic scoring before generative AI

Trend validation is SQL/dbt logic; generation is a final creative aid. This creates an auditable boundary between observed signals and generated language. It does mean that SQL models and their tests are core product logic, not just plumbing.

### Provider payloads stored as JSONB

Normalized fields support the current dbt models; the source resource is retained to support future model changes. This is flexible but consumes more storage and requires careful casts for optional provider fields.

### Idempotency at the database boundary

The Bronze writer uses provider identity from `payload->>'source_id'`. At worker startup it ensures a PostgreSQL unique expression index; inserts use `ON CONFLICT DO NOTHING`. This protects against repeated hourly results, retries, and concurrent jobs. The worker does not delete historical records. If the index cannot be created because existing duplicates are present, setup fails instead of modifying data silently.

**Data-change and privilege constraint:** Remove historical duplicates only through a reviewed, backed-up one-time migration. The recurring worker still needs index DDL privileges if it creates the index at startup; for a strict least-privilege deployment, create it in migration and remove runtime DDL rights (the `IF NOT EXISTS` operation should then be removed or kept only if database permissions permit). Search results missing `source_id` do not conflict and remain insertable.

**Topic trade-off:** The unique key is provider-wide, so if a source is discovered for multiple topics, it is stored once and only the first topic association is kept. If topic attribution needs to be many-to-many, separate source objects from per-topic observation rows.

### Caches in Streamlit and model inference

Short-lived query caches reduce repeated work on Streamlit reruns. The process reuses SQLAlchemy connections, the critic model, and the Ollama HTTP session. Caches can be briefly stale; the Observability page provides a refresh action. These caches are process-local, not shared across replicas.

### Local-first generation

Ollama is tried first; OpenAI is optional. Local inference avoids sending prompts to an external vendor if configured and available. Cloud fallback can incur charges and transmits prompt content externally. Generation failures should remain visible rather than being treated as validated data.

### Human-in-the-loop model feedback

A small classifier head can be fine-tuned from explicit approval/rejection labels. This is a heuristic preference score, not a validated viral-potential metric. Before relying on it, add held-out evaluation, class-balance reporting, model versioning, and drift checks.

## Security and operations

- Keep secrets in local `.env` or GitHub Actions Secrets; rotate leaked credentials.
- Use a least-privilege database role, TLS, backups, and separate dev/prod credentials.
- Use a dedicated revocable Bluesky app password and restrict the YouTube key to the needed API.
- Streamlit has no built-in authentication in this project; place it behind an authenticated gateway or keep it on a trusted network.
- Scraped text and model output are untrusted; do not execute it or treat it as privileged instructions.
- Observability deliberately displays source IDs and metadata, not post text.

## Practical follow-ups

1. Move unique-index creation into a reviewed migration and remove runtime DDL rights; clean any historical duplicates only as a separate backed-up migration.
2. Confirm the deployed JSONB/table/dbt source definitions match the README contract.
3. Add temporary-Postgres integration tests for expression-index conflict behavior and migration safety.
4. Persist workflow metrics beyond Actions logs if long-term operational visibility is needed.
5. Add authentication before public deployment.
6. Evaluate critic quality on a held-out labeled dataset before presenting its score as a decision signal.
7. Adding more scope is discussed in Proposals.md

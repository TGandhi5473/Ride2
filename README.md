# Ride-The-Trends
Ride-The-Trends is designed to reduce the manual effort involved in identifying emerging social media trends and translating them into actionable creative research. By consolidating public signals from YouTube and Bluesky, applying consistent data-validation rules, and generating reviewable summaries and creative suggestions, the workflow helps marketing teams prioritize trends for further exploration. Its human-feedback mechanism provides a foundation for evaluating output usefulness and refining future recommendations; time savings and improvements in decision quality remain to be measured.

**AI is not the trend validator.** Generated copy and the classifier score are creative aids, not verified claims or predictions. Review hooks before use. Not an authoratitive source/workflow in progress to test AI's ability to adapt to creative tasks.

## What it does

- Collects public YouTube Data API v3 search results and Bluesky search posts.
- Stores normalized fields plus provider context in PostgreSQL/Neon.
- Deduplicates provider objects by platform/source ID when a unique database index is present.
- Runs dbt staging, deterministic validation, feedback adjustment, and prompt-mart models.
- Offers a Streamlit dashboard, Trend Discovery, Audit Hub, and Observability page.
- Optionally generates hooks through local Ollama, with an optional OpenAI cloud fallback; scores candidates with a cached DistilBERT critic.
- Records explicit human approve/reject feedback for later critic training.

## Proposed Business KPIs

The architecture is designed to support marketing teams in identifying emerging social media trends and translating them into actionable creative research. The following KPIs could be used to evaluate its business relevance in a pilot deployment:

| KPI | Definition | Evaluation Method |
|---|---|---|
| **Research-to-Brief Time** | Time required to turn a surfaced trend into a reviewable creative brief. | Compare median completion time with and without the assisted workflow. |
| **Trend Exploration Acceptance Rate** | Percentage of surfaced trends that analysts select for further investigation. | Track human selections relative to the total number of trends reviewed. |
| **Summary Usefulness Rate** | Percentage of AI-generated trend summaries that reviewers consider useful for creative research. | Collect reviewer feedback using a consistent usefulness rating or binary approval. |

**Evaluation Objective:** Determine whether the architecture reduces manual research effort, surfaces relevant trends, and provides useful context for human decision-making. These KPIs are proposed evaluation criteria; business impact has not yet been measured in a production environment.
## Architecture and repository map

```text
Public provider APIs
       │
       ▼
1_ingestion/ ──► bronze.raw_ingestion (JSONB)
                       │
                       ▼
2_transformations/ ──► staging → intermediate → analytics prompt mart
                                                   │
                                                   ▼
3_app/ ──► Explore trends → optional hook generation → human feedback
             │                                     │
             └── Audit Hub / Observability ◄──────┘

scripts/retrain_bert.py ← eligible human labels
core/                   shared settings, database, factory, logging
```

- `1_ingestion/` — YouTube and Bluesky scrapers plus scheduled worker.
- `2_transformations/` — dbt project and SQL models.
- `3_app/` — Streamlit entry point, pages, and generation/scoring utilities.
- `core/` — environment configuration, SQLAlchemy engine, Bronze writes, scraper factory, logging, and exceptions.
- `scripts/retrain_bert.py` — feedback-driven classifier-head training.
- `tests/` — external connectivity smoke check.
- `.github/workflows/` — hourly ingestion/retraining and manually triggered integration check.
- `DECISIONS.md` — design trade-offs, operational decisions, and reviewer-oriented repository guide.

## Requirements and local setup

Use Python 3.11 or newer. PostgreSQL/Neon is required for the full application; YouTube ingestion requires an API key. Bluesky ingestion is optional.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your own credentials. Never commit it. Do not paste secrets into source files or logs. See `.env.example` for settings. In brief:

- Required for ingestion: `DATABASE_URL`, `YOUTUBE_API_KEY`.
- Optional Bluesky: `BSKY_HANDLE`, `BSKY_PASSWORD` (use a dedicated revocable app password).
- Optional generation: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`; `OLLAMA_BASE_URL` is restricted in code to localhost/loopback. `OPENAI_API_KEY` enables cloud fallback and sends prompt text to OpenAI if local Ollama is unavailable.
- Optional behavior: `DEFAULT_TOPICS`, `SCRAPE_LIMIT`, `MAX_SEQ_LENGTH`, `TRAINING_THRESHOLD`.

## Run the app and pipeline

Launch the UI from the project root:

```bash
streamlit run 3_app/app.py
```

Navigate using Streamlit's sidebar. Trend Discovery shows validated prompts and allows hook generation and human rating. Audit Hub shows pending feedback and an aggregate provider pulse. Observability shows database health, ingestion counts/freshness, recent source IDs (not post text), feedback counts, and prompt counts.

Run ingestion manually:

```bash
python 1_ingestion/worker.py
```

Run eligible feedback retraining manually:

```bash
python scripts/retrain_bert.py
```

The GitHub Actions ingestion workflow runs hourly. Add its database and provider credentials as repository Actions secrets before enabling it. The optional local model service must be reachable from the Streamlit process. A configured OpenAI fallback may incur costs. dbt should be run against the configured database before the app has prompt records to display.

## Database contract

The current code expects the following deployed structures (validate names and types against your actual database before operating):

- `bronze.raw_ingestion(platform, target_topic, payload, ingested_at)`; `payload` must be PostgreSQL `JSONB`.
- `analytics.fct_creative_prompts(prompt_id, target_topic, confidence_level, optimized_score, llm_prompt_template, validated_at)`.
- `gold.human_feedback(id, prompt_id, text, label_id, used_for_training, created_at)`.
- dbt sources and a dbt profile named `ride_the_trends_profile`.

Feedback labels are `0 = reject`, `1 = approve`. Retraining requires the configured minimum count and both classes. The trained critic and tokenizer are saved under `models/refined_bert`; that directory is ignored by Git and may not persist in ephemeral hosting.

## Idempotency and historical data safety

Bronze writes use `(platform, payload->>'source_id')` as provider identity. The worker ensures a partial unique expression index at startup, and inserts use `ON CONFLICT DO NOTHING`; records without a source ID are outside that uniqueness rule. The worker no longer removes existing duplicates.

If the index cannot be created due to existing duplicate keys, the database will reject index creation and the ingestion run will stop rather than deleting data. Resolve duplicates in a separate reviewed, backed-up migration, preserving any topic associations you need. Check table type, index definition, permissions, and existing data before deployment. The worker startup still attempts index DDL; for least-privilege production operations, create the index through a migration and remove or change runtime index maintenance accordingly.

A provider object is stored once across topics. If the same source is discovered for multiple topics, the first stored topic remains its attribution; use a separate topic-observation relation if you need many-to-many attribution.

## Security and operational boundaries

- The Streamlit app has **no built-in authentication or authorization**. Keep it on a trusted network or put it behind an authenticated access gateway before exposing it publicly. Human feedback writes are not user-authenticated in this project.
- Use separate, least-privilege development and production database roles, TLS, backups, and revocable provider credentials. Restrict the YouTube key to the required API.
- The app currently returns generic database errors to the UI; use server logs for diagnosis and avoid logging secret-bearing provider exception strings.
- Ollama URLs are restricted to loopback to reduce server-side request forgery risk. Cloud fallback sends trend prompt content externally when configured.
- Treat provider text and model output as untrusted content. Do not execute it or treat it as privileged instructions.
- Observability intentionally avoids raw post text but still shows source IDs and operational metadata.
- Startup index creation requires database DDL privileges. Prefer a migration-owned index and a worker role with minimal write permissions.
- Logs and Observability describe current runs/state; no durable historical metrics store is included.

## Verification and limitations

Python syntax checks and fixture-level tests have been used during development, but a live end-to-end run depends on valid provider credentials, the expected Neon schema, and dbt being installed/configured. `tests/connectivity_check.py` is an external connectivity smoke check, not a schema migration or complete integration test.

The classifier approval probability is only a heuristic based on collected human feedback. It is not evidence that a hook will perform well. Evaluate it on held-out labels before using it to guide decisions.

For implementation rationale and additional trade-offs, read [`DECISIONS.md`](DECISIONS.md).

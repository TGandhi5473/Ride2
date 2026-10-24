# Proposal: Extending Ride-The-Trends to More Social Platforms

## Executive summary

Ride-The-Trends currently ingests public YouTube and Bluesky signals into a PostgreSQL Bronze layer, uses deterministic dbt transformations to derive validated trends, and presents those results in a human-reviewed Streamlit workflow. I would extend it by adding provider integrations behind a common ingestion contract and introducing Apache Airflow as the orchestrator when the number of sources, schedules, dependencies, and operational requirements outgrow a single scheduled worker.

The goal is not to force every network into the same semantics. The goal is to make collection reliable, policy-compliant, observable, replayable, and comparable where comparison is meaningful. Each connector would preserve provider-native context in Bronze and expose a deliberately small, versioned set of common fields for cross-platform analytics.

> **Important constraint:** Access to TikTok, X, Meta (Instagram/Facebook), and WhatsApp data depends on each provider's current API products, app review, permissions, account type, region, quotas, and terms. This proposal assumes only approved, documented API access. It does not assume unrestricted public-post search or access to private messages.

## Design principles

1. **Provider adapters, shared envelope.** Isolate provider-specific API mechanics from ingestion scheduling and downstream models.
2. **Bronze is immutable evidence.** Preserve what was received, when, from which API version and query, while minimizing or redacting secrets and unnecessary personal data.
3. **At-least-once delivery, effectively-once outcomes.** Network workflows may retry and replay. Stable source identities, idempotent writes, and versioned transformations prevent repeated work from creating duplicate logical records.
4. **Deterministic trend decisions.** Provider API results are observations; dbt rules determine validation. Generated content remains downstream and optional.
5. **Failure isolation.** One provider's outage or quota exhaustion must not stop healthy providers or erase already committed data.
6. **Policy and privacy by design.** Respect API terms, deletion/erasure requirements, retention limits, scopes, and applicable privacy rules. Store less where the API or use case permits.
7. **Observable and explainable.** Make each request, page, checkpoint, record, retry, and transformation traceable without logging secrets or unnecessary raw content.

## Target architecture

```text
Airflow DAGs (schedules, dependencies, retries, alerts)
          │
          ├── YouTube adapter
          ├── Bluesky adapter
          ├── TikTok adapter (approved API product/scopes only)
          ├── X adapter (approved API product/entitlements only)
          ├── Instagram adapter (eligible professional-account surfaces)
          ├── Facebook adapter (approved Pages/Groups surfaces)
          └── WhatsApp adapter (Business Platform events/messages only)
                    │
                    ▼
       Provider-specific Bronze observations
       + request/run ledger + durable checkpoints
                    │
                    ▼
       dbt staging (one model per provider/version)
                    │
                    ▼
       Canonical observation and identity models
                    │
                    ▼
       Deterministic trend marts / quality tests
                    │
                    ▼
       Streamlit discovery, audit, observability
```

Airflow should orchestrate bounded units of work (provider + account/tenant + query/window + page range), rather than hold large API payloads in XCom. Persist intermediate data and cursors in the database or object storage, and pass only small references and run metadata through XCom.

### Suggested modular layout

```text
1_ingestion/
  providers/
    base.py
    youtube/
    bluesky/
    tiktok/
    x/
    meta_instagram/
    meta_facebook/
    whatsapp/
  contracts.py
  worker.py
  persistence.py
  checkpoints.py
airflow/
  dags/
    social_ingestion.py
  plugins/                 # only if custom operators are justified
2_transformations/
  models/staging/<provider>/
  models/intermediate/
  models/marts/
```

The existing `BaseScraper`/factory direction is a useful starting point. I would evolve it into an explicit adapter contract and keep provider SDK objects out of the transformation layer.

## Provider onboarding strategy

Before implementation, confirm the API is available for the intended use case, required permissions are obtainable, data can be retained and displayed as planned, and deletion obligations can be met. Build a small access spike to validate quotas, pagination, field availability, and review requirements before estimating a production connector.

### TikTok

Use only the official TikTok API product approved for the specific use case (for example, an approved research or business/marketing product where eligible). Confirm whether it provides search/discovery access to the desired content; do not assume that a consumer-facing feed or broad public trend search is available to every app. Implement supported fields and pagination as returned, preserve API/product version and query provenance, and keep unsupported metrics absent rather than synthesizing them. Treat permissions and review status as deployment prerequisites.

### X

Use X's official API at the account tier and endpoint entitlements available to the project. Search history, recent search, stream access, fields, and quotas are product-dependent and may change. Record the endpoint/product tier, requested fields, query, pagination token, and API version. Design for quota exhaustion and access changes; do not build around undocumented endpoints or scrape the website as a fallback.

### Instagram and Facebook (Meta)

Use the Meta Graph API with the appropriate app review, access tokens, and permissions. Access is commonly constrained to eligible professional accounts, Pages, authorized assets, and specific features; it should not be represented as unrestricted public Instagram/Facebook search. Separate Instagram and Facebook adapters even when they share Graph API infrastructure, because object models, permissions, webhooks, and retention rules differ. Subscribe to approved webhooks where event-driven ingestion is available, verify signatures, enqueue events durably, and fetch full details asynchronously.

### WhatsApp

Treat WhatsApp as a business messaging/event integration, not a public social trend-search source. Use the WhatsApp Business Platform for an explicitly authorized business number and approved use cases. Process inbound message/status webhooks, verify provider signatures, acknowledge quickly, and persist an event before asynchronous processing. Minimize message content, restrict access, define short retention/redaction rules, and never collect personal conversations without a clear lawful basis and consent/authorization. The downstream analytics should separate private customer-support signals from public social trend signals; do not combine them as equivalent evidence.

## Common adapter contract

An adapter should expose capabilities and operations rather than pretending all providers support the same API:

```python
class ProviderAdapter(Protocol):
    provider: str
    api_version: str
    capabilities: ProviderCapabilities

    def fetch(self, request: FetchRequest, checkpoint: Checkpoint | None) -> FetchPage: ...
    def normalize(self, response: object) -> list[ProviderObservation]: ...
```

`FetchRequest` should include the authorized account/tenant, query or subscription, bounded time interval, requested fields, and correlation/run ID. `ProviderCapabilities` should declare support for search, historical range, streaming/webhooks, deletions, metrics, and cursor-based pagination. A capability-aware scheduler can skip unsupported work explicitly instead of treating “no data” as an API failure.

A canonical envelope might contain:

- `provider`, `provider_object_id`, `object_type`, and provider/API version;
- `account_or_tenant_id` (internal tokenized ID; never an access token);
- `observed_at`, `provider_created_at`, and `ingested_at` as UTC timestamps;
- `query_id` / collection definition, `run_id`, page/cursor reference, and schema version;
- a minimal normalized content/metrics projection for common use;
- provider-native payload or object-storage reference, subject to retention policy;
- deletion/tombstone and edit/version metadata where supported.

Make the identity scope explicit. A raw ID may be unique only within a provider, account, object type, or tenant. Use a composite identity such as `(provider, account_scope, object_type, provider_object_id)` where the provider's semantics require it. For content that can be edited, preserve an observation/version key as well as the stable object key. For webhooks, provider event ID and object ID are different identities and both can matter.

## Storage and data model evolution

The current single Bronze row with `platform`, `target_topic`, JSONB payload, and ingestion timestamp is a useful prototype, but multi-provider production needs distinguishable objects, observations, topics, and delivery events. A possible relational model:

- `ingestion_runs`: run ID, DAG/task, provider, scope, query/window, start/end, status, attempt, API version, and aggregate counts;
- `provider_observations`: provider-scoped object identity, observed/created timestamps, payload schema version, minimal normalized fields, payload/object-storage reference, and run ID;
- `topic_observations`: many-to-many source-to-query/topic association, with observed time and query definition;
- `provider_checkpoints`: scope, cursor/watermark, last successful page/window, updated time, and optimistic version;
- `provider_events`: webhook event ID, signature-validation result, receipt time, processing state, and event dedupe key;
- `deletion_requests` / tombstones: provider object and downstream deletion state where policy requires erasure.

Use migrations to create indexes and constraints, not recurring ingestion startup DDL. For large raw payloads, object storage may be appropriate with encryption, lifecycle policies, and a database pointer/checksum; avoid indefinitely retaining payloads that are not needed. Partition large observation tables by ingestion/observation time only after measuring real volume and query patterns. Keep schema evolution additive: version payload contracts and staging models, tolerate missing fields, and test schema changes against representative fixtures.

## Airflow orchestration proposal

### DAG boundaries

I would begin with separate provider DAGs or mapped provider tasks under a common DAG factory, selected based on independent schedules and failure SLAs. Each task should be a bounded, restartable unit such as `(provider, account, query, time-window, page batch)`. A typical flow:

1. Create a run/partition record and choose a durable checkpoint or time window.
2. Request one or more bounded pages from the provider.
3. Validate response status, schema, pagination metadata, and rate-limit headers.
4. Persist observations and the next checkpoint transactionally (or use an outbox pattern where one transaction is not possible).
5. Emit task metrics and commit page completion.
6. Run dbt staging/tests for completed partitions or on a separate dependency-aware schedule.
7. Publish/update trend marts only after data-quality gates pass.
8. Alert, reconcile, and optionally replay failed windows.

Use Airflow task mapping for independent accounts/queries with concurrency pools per provider. Set `max_active_runs`, task limits, provider pools, and DAG timeouts to protect quotas and database connections. Keep Airflow secrets in a secrets backend/connection store, never DAG source or XCom. Use Airflow's supported executor and metadata database for the deployment scale; keep the app's analytical Postgres schema separate from Airflow metadata where practical.

### Retries and backoff

Retries should be classified, bounded, and jittered:

- Retry network timeouts, connection resets, transient 5xx errors, and provider-designated transient failures with exponential backoff plus jitter.
- Respect `Retry-After`, reset timestamps, quota headers, and provider-specific rate-limit guidance. Pause/pool the provider rather than having every mapped task retry simultaneously.
- Do not repeatedly retry permanent 4xx responses such as invalid queries, revoked credentials, unsupported scopes, or deleted resources. Fail fast, alert, and route to operator remediation.
- Treat authentication/permission failures as a circuit-breaker signal: stop that provider's tasks, protect the credential, and avoid retry storms.
- Bound attempts and total elapsed time. Include retry count and final error category in the run ledger, but redact URLs, headers, tokens, and response bodies that may contain secrets or personal data.
- For long quota windows, defer to a later scheduled run instead of holding workers asleep for hours.

Airflow retries provide task-level retry orchestration, but the adapter should also distinguish errors and expose retry-after metadata. Avoid nested uncontrolled retry loops in the SDK and Airflow simultaneously; choose one layer to own the retry budget.

### Checkpoints and pagination

A checkpoint is a recovery hint, not proof that every prior page was durably committed. Advance a cursor only after the corresponding page's records and its completion state are persisted. For a provider without stable cursors, use bounded overlapping time windows and deduplicate by provider identity; periodically reconcile a wider window to capture late-arriving or edited content. Store a watermark with an overlap buffer (for example, “last successful time minus a configured lag”) rather than assuming API ordering is perfect.

For webhook feeds, acknowledge after durable receipt, then process asynchronously. Use an inbox table keyed by provider event ID, or a provider-appropriate composite key, to absorb duplicate deliveries. Preserve event ordering only where the provider guarantees it; otherwise make handlers version-aware and tolerant of reordering.

### Failover

Failover should preserve correctness, not silently change data sources:

- If one provider fails, continue healthy provider branches and mark cross-platform aggregates as incomplete/stale until the missing input recovers.
- If the API is unavailable or the credential is broken, do not substitute scraped HTML, unofficial endpoints, or another provider's data under the failed provider label.
- Use historical data only as explicitly marked stale fallback for read-only user experience; never count it as a fresh observation.
- If the primary database is unavailable, stop checkpoint advancement. Optionally write durable encrypted batches to an outbox/object store with idempotency keys and replay them after recovery. Do not acknowledge work as complete while its only copy is in task memory/XCom.
- For Airflow worker failure, tasks should be safe to restart from a page/window boundary. Configure queue/executor redundancy and back up the Airflow metadata DB, but do not confuse Airflow metadata recovery with source-data recovery.
- A second region or provider account should be considered only if it is contractually and technically valid, and its identities/coverage must be recorded separately.

### Eventual consistency

Social APIs may index posts late, update counts, remove content, return delayed webhook events, or expose slightly different views across endpoints. The system should represent this rather than conceal it:

- Store `provider_created_at`, `observed_at`, and `ingested_at` separately.
- Treat engagement counts as time-stamped snapshots, not immutable attributes. Store a metric observation history or a last-seen projection with measurement time.
- Use an ingestion watermark with a deliberate overlap window to find late items. Re-read recent objects when API terms and quotas allow.
- Make trend marts idempotently recomputable from Bronze and version the transformation logic/run.
- Mark source coverage and freshness by provider; a trend computed from one available provider should not be presented as equivalent to a complete multi-provider signal.
- Define a correction policy for edited/deleted source objects. Where required, propagate deletions to raw, staging, marts, cached UI, and derived exports; record a tombstone rather than resurrecting deleted content on replay.
- Expose “as of” timestamps and completeness flags in the UI.

## Idempotency and exactly-once boundaries

True exactly-once delivery across a remote API, Airflow, Postgres, and object storage is generally not available as one atomic transaction. Design for at-least-once execution and idempotent effects:

1. Use stable provider identity plus scope and object type. For webhooks, dedupe event deliveries separately from underlying objects.
2. Enforce a database unique constraint/index as the final guard. Use `INSERT ... ON CONFLICT` for safe replay.
3. If an existing object is updated, apply a deterministic upsert with provider update/version time, or append an observation snapshot; avoid “last task to finish wins” without version checks.
4. Persist page records and checkpoint changes atomically when both are in Postgres. Otherwise use an outbox/inbox or a replayable object-store manifest.
5. Keep a durable ingestion ledger so operators can distinguish “requested,” “received,” “committed,” “transformed,” and “published.”
6. Make dbt models deterministic and repeatable; use unique keys, incremental merge semantics, freshness tests, and periodic full reconciliation.
7. Do not mark training feedback used until the corresponding model artifact is successfully and atomically promoted; archive exactly the feedback IDs included in that artifact.

This yields effectively-once logical records even though requests/tasks can execute more than once.

## Data quality, privacy, and governance

Add automated gates for:

- required provider identity, allowed provider/type, timestamps, JSON schema/version, and payload size;
- duplicate rates, null rates, unexpected field/type changes, API pagination completeness, and freshness;
- impossible metrics and provider-specific constraints without inventing missing values;
- cross-source coverage and confidence rules, clearly handling missing providers;
- test fixtures for normal, empty, malformed, throttled, deleted, and edited responses.

Store only data needed for the stated purpose. Separate public content from business/customer data. Apply encryption in transit and at rest, role-based access, audit trails for human feedback, retention limits, and deletion workflows. Redact access tokens, app secrets, phone numbers, direct identifiers, and sensitive content from logs/metrics. Do not put raw message bodies, tokens, or large API responses into Airflow XCom. Review provider terms and legal/privacy requirements before retaining or redistributing any data.

## Observability and incident response

For every provider/task/window, report:

- run/task ID, provider, scope, query/window, API/schema version, attempt, status;
- pages and records requested/received/inserted/updated/deduplicated/rejected;
- latency, retry count, quota/rate-limit state, checkpoint before/after, and freshness;
- dbt test and mart publication status, plus data coverage/completeness.

Alert on repeated auth failures, sustained 429/5xx, stale checkpoints, zero-result anomalies, rising duplicate/schema-rejection rates, task backlog, database connection pressure, and missing scheduled runs. Include runbook steps: pause a provider, rotate credentials, requeue a window, inspect a sanitized sample, rebuild a partition, and verify downstream completeness. Build a reconciliation dashboard for expected vs committed pages/windows.

## Rollout plan

1. **Foundation:** move index creation to migrations, add typed ingestion-run/checkpoint tables and a provider-independent envelope, create contract/fixture tests, and make topic association many-to-many.
2. **Orchestration:** deploy Airflow for current YouTube/Bluesky work first; verify retries, concurrency pools, alerting, restart safety, and replay in a staging database.
3. **One new provider at a time:** run an API access/terms spike, implement a provider adapter, add golden fixtures and tests, then shadow-ingest without affecting trend scores.
4. **Quality and policy gate:** compare coverage, field semantics, latency, cost/quota use, deletion behavior, and retention obligations before allowing the provider into cross-platform scoring.
5. **Production cutover:** enable a canary account/query, monitor for a defined period, then increase scope with quota limits and rollback controls.
6. **Ongoing:** review API changes/permissions and retention quarterly; rotate credentials; rehearse replay and provider deletion workflows.

## Open questions to resolve before implementation

- Which user/account and permitted use case is required for each API?
- Which exact endpoints/products and API access tiers are available and approved?
- Is the product searching public content, monitoring owned business accounts, processing customer messages, or a combination? These are materially different permission and privacy models.
- What retention period, data residency, deletion SLA, and export policy apply?
- How fresh must each provider be, and what completeness is required before a trend is labeled validated?
- What volume, tenant count, and Airflow deployment/availability target justify the operational cost?
- Which warehouse/object store and secrets backend are available, and who owns on-call response?

## Expected hiring-manager discussion

The central architectural choice is to scale orchestration and provider diversity without pretending API capabilities or data semantics are interchangeable. Airflow supplies dependency management, bounded retries, scheduling, and operational visibility; durable checkpoints and unique keys make replay safe; Bronze preserves provenance; dbt provides deterministic and testable transformations; and policy-aware deletion/retention protects data subjects and provider access. I would validate API access and data rights before promising connector scope or timelines.

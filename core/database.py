"""Database helpers with lazy engine creation, deduplicated writes, and run metrics."""
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import Config
from .logging import setup_logger

logger = setup_logger("DatabaseCore")


@lru_cache(maxsize=1)
def get_neon_engine() -> Engine:
    """Create one reusable pool on demand; importing the UI does not connect to DB."""
    database_url = Config.require_database()
    connect_args = {"sslmode": "require"} if database_url.startswith(("postgresql://", "postgres://")) else {}
    return create_engine(
        database_url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
    )


def ensure_ingestion_constraints() -> dict[str, int]:
    """Ensure the provider identity index exists without destructive row cleanup.

    Historical duplicates must be reviewed and removed via a separate, backed-up
    migration. Ingestion never silently deletes Bronze history at worker startup.
    """
    ddl = text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_ingestion_provider_source
        ON bronze.raw_ingestion (platform, (payload->>'source_id'))
        WHERE payload->>'source_id' IS NOT NULL
    """)
    with get_neon_engine().begin() as conn:
        conn.execute(ddl)
    logger.info("Bronze provider-identity unique index verified")
    return {"removed_duplicates": 0}



def save_to_bronze_batch(records: list[dict[str, Any]]) -> dict[str, int]:
    """Insert distinct provider objects; database uniqueness makes retries safe.

    `source_id` is already embedded in normalized JSON payloads. PostgreSQL's
    `ON CONFLICT` uses the expression index above to ignore repeat search hits.
    """
    if not records:
        return {"inserted": 0, "duplicates": 0, "attempted": 0}
    normalized = []
    seen = set()
    for record in records:
        payload = record.get("payload", {})
        if not isinstance(payload, (dict, list)):
            payload = {"value": payload}
        source_id = payload.get("source_id") if isinstance(payload, dict) else None
        # Local dedupe prevents sending duplicate parameters in the same batch;
        # provider identity is platform-wide, not topic-specific.
        identity = (record["platform"], str(source_id)) if source_id else None
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        normalized.append({
            "platform": record["platform"],
            "target_topic": record["target_topic"],
            "payload": json.dumps(payload, default=str),
            "ingested_at": record.get("ingested_at") or datetime.now(timezone.utc),
        })

    query = text("""
        INSERT INTO bronze.raw_ingestion (platform, target_topic, payload, ingested_at)
        VALUES (:platform, :target_topic, CAST(:payload AS jsonb), :ingested_at)
        ON CONFLICT (platform, (payload->>'source_id'))
        WHERE payload->>'source_id' IS NOT NULL
        DO NOTHING
    """)
    engine = get_neon_engine()
    with engine.begin() as conn:
        result = conn.execute(query, normalized)
        inserted = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
    attempted = len(normalized)
    metrics = {"inserted": inserted, "duplicates": max(0, attempted - inserted), "attempted": attempted}
    logger.info(
        "Bronze ingestion attempted=%d inserted=%d duplicates=%d",
        metrics["attempted"], metrics["inserted"], metrics["duplicates"],
    )
    return metrics


def fetch_gold_prompts(limit: int = 200) -> list[dict[str, Any]]:
    """Fetch a bounded set of fields used by Discovery, newest first."""
    query = text("""
        SELECT prompt_id, target_topic, confidence_level, optimized_score,
               llm_prompt_template, validated_at
        FROM analytics.fct_creative_prompts
        ORDER BY validated_at DESC
        LIMIT :limit
    """)
    with get_neon_engine().connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, {"limit": max(1, min(limit, 1000))})]

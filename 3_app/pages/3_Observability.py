"""Operational dashboard: database health, ingestion freshness, and data volumes."""
import streamlit as st
import pandas as pd
from sqlalchemy import text
from core.config import Config
from core.database import get_neon_engine

st.set_page_config(page_title="Observability | Ride-The-Trends", page_icon="📡", layout="wide")


@st.cache_data(ttl=30, show_spinner=False)
def load_observability_metrics():
    """Return operational summaries only; raw post text is deliberately excluded."""
    engine = get_neon_engine()
    with engine.connect() as conn:
        db_health = conn.execute(text("SELECT current_timestamp AS checked_at, current_database() AS database_name")).mappings().one()
        ingestion = pd.read_sql(text("""
            SELECT platform, COUNT(*) AS rows_total,
                   COUNT(DISTINCT payload->>'source_id') AS unique_sources,
                   MAX(ingested_at) AS last_ingested_at,
                   COUNT(*) FILTER (WHERE ingested_at >= now() - interval '24 hours') AS rows_last_24h
            FROM bronze.raw_ingestion
            GROUP BY platform ORDER BY platform
        """), conn)
        latest = pd.read_sql(text("""
            SELECT platform, target_topic, payload->>'source_id' AS source_id, ingested_at
            FROM bronze.raw_ingestion
            ORDER BY ingested_at DESC LIMIT 25
        """), conn)
        feedback = conn.execute(text("""
            SELECT COUNT(*) FILTER (WHERE used_for_training = FALSE) AS pending,
                   COUNT(*) FILTER (WHERE used_for_training = TRUE) AS trained
            FROM gold.human_feedback
        """)).mappings().one()
        prompts = conn.execute(text("""
            SELECT COUNT(*) AS prompt_count,
                   MAX(validated_at) AS latest_prompt_at
            FROM analytics.fct_creative_prompts
        """)).mappings().one()
    return dict(db_health), ingestion, latest, dict(feedback), dict(prompts)


def _freshness_label(timestamp):
    if timestamp is None or pd.isna(timestamp):
        return "No data"
    age_hours = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(timestamp).tz_convert("UTC")).total_seconds() / 3600
    if age_hours <= 2:
        return "Fresh"
    if age_hours <= 26:
        return "Delayed"
    return "Stale"


def show_page():
    st.title("📡 Observability")
    st.caption("Operational health and freshness metrics; sensitive post text is not shown here.")
    if st.button("↻ Refresh metrics"):
        load_observability_metrics.clear()

    try:
        db, ingestion, latest, feedback, prompts = load_observability_metrics()
    except Exception:
        st.error("Could not load operational metrics. Check server logs for details.")
        st.info("Check DATABASE_URL and confirm the Bronze, Gold, and analytics schemas are available.")
        return

    st.success(f"Database connection healthy · {db['database_name']} · checked {db['checked_at']}")
    refined = (Config.BERT_REFINED_PATH / "config.json").exists()
    a, b, c, d = st.columns(4)
    a.metric("Validated prompts", prompts["prompt_count"])
    b.metric("Pending feedback", feedback["pending"])
    c.metric("Critic model", "Fine-tuned" if refined else "Base model")
    d.metric("Last prompt update", str(prompts["latest_prompt_at"] or "No prompts"))

    st.subheader("Ingestion by provider")
    if ingestion.empty:
        st.warning("No ingestion rows found.")
    else:
        view = ingestion.copy()
        view["Freshness"] = view["last_ingested_at"].apply(_freshness_label)
        st.dataframe(view, use_container_width=True, hide_index=True)

    st.subheader("Recent ingestion records")
    st.dataframe(latest, use_container_width=True, hide_index=True)
    st.caption("Newest 25 records, with provider source IDs only; post content is intentionally omitted.")
    st.caption(f"Metrics refresh every 30 seconds. Feedback trained: {feedback['trained']}.")


show_page()

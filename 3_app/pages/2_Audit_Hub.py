import streamlit as st
import pandas as pd
from sqlalchemy import text
from core.database import get_neon_engine
from core.config import Config

st.set_page_config(page_title="Audit Hub", page_icon="🛡️", layout="wide")


@st.cache_data(ttl=30, show_spinner=False)
def fetch_audit_data():
    """Fetch bounded feedback and pulse summaries for the audit view."""
    engine = get_neon_engine()
    feedback_query = text("""
        SELECT f.text AS "Generated Hook",
               CASE WHEN f.label_id = 1 THEN '✅ Approved' ELSE '❌ Rejected' END AS "Human Label",
               p.target_topic AS "Topic Context", p.confidence_level AS "Trend Confidence"
        FROM gold.human_feedback f
        JOIN analytics.fct_creative_prompts p ON f.prompt_id = p.prompt_id
        WHERE f.used_for_training = FALSE
        ORDER BY f.created_at DESC LIMIT 500
    """)
    pulse_query = text("""
        SELECT target_topic AS "Topic",
               COUNT(*) FILTER (WHERE platform = 'youtube') AS "YouTube Hits",
               COUNT(*) FILTER (WHERE platform = 'bluesky') AS "Bluesky Hits",
               CASE WHEN COUNT(DISTINCT platform) > 1 THEN 'HIGH' ELSE 'MEDIUM' END AS "Auto-Confidence"
        FROM bronze.raw_ingestion
        GROUP BY target_topic ORDER BY COUNT(*) DESC LIMIT 200
    """)
    with engine.connect() as conn:
        return pd.read_sql(feedback_query, conn), pd.read_sql(pulse_query, conn)


def show_audit():
    st.title("🛡️ Governance & HITL Audit")
    st.subheader("🚀 Ingestion & Model Status")
    col1, col2, col3 = st.columns(3)
    col1.metric("Active critic", "Fine-tuned" if (Config.BERT_REFINED_PATH / "config.json").exists() else "Base model")
    col2.metric("Training threshold", f"{Config.TRAINING_THRESHOLD} labels")
    col3.metric("Database", "Neon Postgres")
    st.divider()

    try:
        feedback_df, pulse_df = fetch_audit_data()
        st.subheader("🧠 BERT Training Queue")
        current_count = len(feedback_df)
        st.write(f"**Pending feedback shown:** {current_count} (up to 500) · **Retraining threshold:** {Config.TRAINING_THRESHOLD}")
        st.progress(min(current_count / max(Config.TRAINING_THRESHOLD, 1), 1.0))
        if not feedback_df.empty:
            st.dataframe(feedback_df, use_container_width=True, hide_index=True)
        else:
            st.info("Queue is empty. Rate generated hooks in Trend Discovery.")
        st.caption("Training is run by the scheduled pipeline once enough unused labels are available.")
        st.divider()
        st.subheader("📊 Cross-platform trend pulse")
        if pulse_df.empty:
            st.info("No ingestion records available yet.")
        else:
            st.dataframe(pulse_df, use_container_width=True, hide_index=True)
    except Exception:
        st.error("Audit data could not be loaded. Check server logs for details.")


if __name__ == "__main__":
    show_audit()

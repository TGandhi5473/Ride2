import streamlit as st
import pandas as pd
from sqlalchemy import text
from core.database import get_neon_engine

st.set_page_config(page_title="Ride-The-Trends | Dashboard", page_icon="🌊", layout="wide")


@st.cache_data(ttl=60, show_spinner=False)
def get_dashboard_stats():
    """Cache low-cost summary metrics; avoid repeating identical queries on reruns."""
    query = text("""
        SELECT COUNT(*) FILTER (WHERE confidence_level = 'HIGH') AS high_confidence,
               COUNT(*) AS total_prompts
        FROM analytics.fct_creative_prompts
    """)
    with get_neon_engine().connect() as conn:
        row = conn.execute(query).mappings().one()
        return dict(row)


def main():
    st.title("🌊 Ride-The-Trends")
    st.subheader("Creative Intelligence Engine")
    st.markdown("Validated data signals inform AI-generated creative suggestions; generated copy should be reviewed before use.")
    try:
        stats = get_dashboard_stats()
        col1, col2, col3 = st.columns(3)
        col1.metric("High-confidence trends", stats["high_confidence"])
        col2.metric("Validated prompts", stats["total_prompts"])
        col3.metric("Data layer", "Gold intelligence")
    except Exception:
        st.warning("Dashboard metrics are unavailable. Check server logs for details.")
        st.caption("Check DATABASE_URL and confirm the dbt Gold model exists.")


if __name__ == "__main__":
    main()

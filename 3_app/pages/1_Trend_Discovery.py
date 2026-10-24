import streamlit as st
import pandas as pd
from sqlalchemy import text
from core.database import get_neon_engine
from utils.llm_engine import generate_creative_assets

st.set_page_config(page_title="Trend Discovery", page_icon="🎯", layout="wide")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_gold_prompts():
    """Reuse the frequently viewed trend feed for one minute and bound its size."""
    query = text("""
        SELECT prompt_id, target_topic, confidence_level, optimized_score,
               llm_prompt_template, validated_at
        FROM analytics.fct_creative_prompts
        ORDER BY validated_at DESC
        LIMIT 200
    """)
    with get_neon_engine().connect() as conn:
        return pd.read_sql(query, conn)


def save_feedback(prompt_id, hook_text, is_good):
    """Persist an explicit human label and invalidate cached queue/feed views."""
    query = text("""
        INSERT INTO gold.human_feedback (prompt_id, text, label_id, used_for_training)
        VALUES (:pid, :txt, :lbl, FALSE)
    """)
    try:
        with get_neon_engine().begin() as conn:
            conn.execute(query, {"pid": prompt_id, "txt": hook_text, "lbl": 1 if is_good else 0})
        fetch_gold_prompts.clear()
        return True
    except Exception:
        # Database/provider exception strings may disclose connection details.
        st.error("Could not save feedback. Check database configuration and server logs.")
        return False


def show_discovery():
    st.title("🎯 Validated Trend Discovery")
    st.caption("Validated signals are deterministic; generated hooks are suggestions for creative exploration.")
    st.markdown("---")
    try:
        df = fetch_gold_prompts()
    except Exception:
        st.error("Could not load validated trends. Check database configuration and server logs.")
        return
    if df.empty:
        st.warning("No validated trends found. Run ingestion and dbt to populate this feed.")
        return

    for _, trend in df.iterrows():
        key = f"btn_{trend['prompt_id']}"
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(f"Topic: {trend['target_topic']}")
                m1, m2, m3 = st.columns(3)
                m1.metric("Confidence", trend["confidence_level"])
                score_value = trend.get("optimized_score")
                m2.metric("Optimized Score", f"{score_value:.2f}" if pd.notna(score_value) else "—")
                m3.metric("Status", "Validated" if str(trend["confidence_level"]).upper() != "LOW" else "Draft")
                with st.expander("🔍 View prompt logic"):
                    st.code(str(trend["llm_prompt_template"] or ""), language="markdown")

            with col2:
                st.write("### AI Orchestration")
                if st.button("✨ Generate & Validate", key=key, use_container_width=True):
                    with st.spinner("Generating candidates and scoring them..."):
                        result = generate_creative_assets(str(trend["llm_prompt_template"] or ""))
                        if result.get("text"):
                            st.session_state[f"result_{key}"] = result
                        else:
                            st.error(result.get("error", "No result was generated."))

                result = st.session_state.get(f"result_{key}")
                if result:
                    hook, quality_score = result["text"], float(result["score"])
                    st.markdown("---")
                    st.success("Best candidate selected by the critic")
                    st.info(hook)
                    st.caption(f"Source: {result.get('source', 'unknown')} · {result.get('candidate_count', 1)} distinct candidate(s)")
                    color = "green" if quality_score > 0.7 else "orange" if quality_score > 0.4 else "red"
                    st.markdown(f"**Critic approval score:** :{color}[{quality_score:.1%}]")
                    st.progress(max(0.0, min(quality_score, 1.0)))
                    left, right = st.columns(2)
                    if left.button("👍 Approved", key=f"up_{key}", use_container_width=True):
                        if save_feedback(trend["prompt_id"], hook, True):
                            st.toast("Saved to the training queue", icon="🧠")
                            del st.session_state[f"result_{key}"]
                            st.rerun()
                    if right.button("👎 Rejected", key=f"down_{key}", use_container_width=True):
                        if save_feedback(trend["prompt_id"], hook, False):
                            st.toast("Rejection saved for model tuning", icon="📉")
                            del st.session_state[f"result_{key}"]
                            st.rerun()


if __name__ == "__main__":
    show_discovery()

import streamlit as st

def get_confidence_style(level: str):
    """Returns a color and icon for the UI based on deterministic scoring."""
    styles = {
        "HIGH": {"color": "#28a745", "icon": "🔥", "label": "Verified Trend"},
        "MEDIUM": {"color": "#fd7e14", "icon": "📈", "label": "Rising Heat"},
        "LOW": {"color": "#6c757d", "icon": "🧊", "label": "Cold Signal"}
    }
    return styles.get(level.upper(), styles["LOW"])

def render_trend_card(topic, confidence, prompt):
    """Renders a standardized card for the Discovery feed."""
    style = get_confidence_style(confidence)
    
    with st.container(border=True):
        cols = st.columns([0.1, 3, 1])
        cols[0].markdown(f"### {style['icon']}")
        
        with cols[1]:
            st.markdown(f"**{topic}**")
            st.caption(f"{style['label']} | Level: {confidence}")
            
        with cols[2]:
            # This triggers the LLM enrichment
            if st.button("Generate Ad", key=f"btn_{topic}"):
                st.session_state[f"active_prompt_{topic}"] = True

def format_llm_response(text: str):
    """Wraps the raw LLM string in a nice UI block quote."""
    return st.info(f"💡 **AI Creative Suggestion:**\n\n{text}")

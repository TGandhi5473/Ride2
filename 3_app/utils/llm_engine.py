"""Creative generation and critic scoring with process-level model/client caches."""
from functools import lru_cache
from typing import Any

import requests
from core.config import Config
from core.logging import setup_logger

logger = setup_logger("CreativeEngine")


@lru_cache(maxsize=2)
def _ollama_session(base_url: str):
    """Reuse HTTP connection pools across Streamlit reruns."""
    session = requests.Session()
    session.trust_env = False  # Avoid implicit proxy/credential forwarding from process env.
    session.headers.update({"Content-Type": "application/json"})
    return session


def _validated_ollama_url(base_url: str) -> str:
    """Allow only loopback Ollama endpoints to prevent SSRF to internal services."""
    from urllib.parse import urlsplit
    import ipaddress

    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("OLLAMA_BASE_URL must be an HTTP(S) URL on localhost or a private loopback address")
    hostname = parsed.hostname.lower().rstrip(".")
    allowed = hostname == "localhost"
    if not allowed:
        try:
            allowed = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            allowed = False
    if not allowed or parsed.username or parsed.password:
        raise ValueError("OLLAMA_BASE_URL must point to localhost/loopback without embedded credentials")
    return f"{parsed.scheme}://{parsed.netloc}"


@lru_cache(maxsize=2)
def _load_critic(model_path: str):
    """Load tokenizer/model once per model path; inference calls reuse the same objects."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(model_path)
    model.eval()
    return tokenizer, model, torch


def get_critic_score(text: str) -> float:
    """Return the classifier's probability for APPROVE (neutral fallback if unavailable)."""
    try:
        tokenizer, model, torch = _load_critic(Config.get_active_bert_path())
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=Config.MAX_SEQ_LENGTH)
        with torch.inference_mode():
            probabilities = torch.softmax(model(**inputs).logits, dim=-1)[0]
        label_index = next((int(k) for k, v in model.config.id2label.items() if str(v).upper() == "APPROVE"), 1)
        if label_index >= len(probabilities):
            label_index = 1
        return float(probabilities[label_index].item())
    except Exception as exc:
        logger.warning("Critic scoring unavailable; using neutral score (%s)", type(exc).__name__)
        return 0.5


def _generate_one(prompt: str) -> tuple[str | None, str | None]:
    """Try local Ollama first, then optional cloud fallback; return text and source."""
    try:
        ollama_url = _validated_ollama_url(Config.OLLAMA_BASE_URL)
        response = _ollama_session(ollama_url).post(
            f"{ollama_url}/api/generate",
            json={"model": Config.OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=(3, 30),
        )
        response.raise_for_status()
        content = response.json().get("response", "").strip()
        if content:
            return content, "ollama"
        logger.warning("Ollama returned an empty response")
    except requests.RequestException as exc:
        logger.info("Local Ollama unavailable (%s)", type(exc).__name__)
    except (ValueError, TypeError) as exc:
        logger.warning("Could not parse Ollama response (%s)", type(exc).__name__)

    if Config.OPENAI_API_KEY:
        try:
            from openai import OpenAI
            response = OpenAI(api_key=Config.OPENAI_API_KEY, timeout=30).chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
            )
            content = (response.choices[0].message.content or "").strip()
            if content:
                return content, "openai"
        except Exception as exc:
            logger.error("Cloud LLM fallback failed (%s)", type(exc).__name__)
    return None, None


def generate_creative_assets(prompt_template: str, n_candidates: int = 3) -> dict[str, Any]:
    """Generate distinct candidates, score once each, and return hook plus its score."""
    n_candidates = max(1, min(int(n_candidates), 5))
    full_prompt = (
        f"{prompt_template}\n\nWrite one original, punchy advertising hook. "
        "Return only the hook; avoid unsupported factual claims."
    )
    candidates = []
    sources: set[str] = set()
    for _ in range(n_candidates):
        content, source = _generate_one(full_prompt)
        if content and content not in {item["text"] for item in candidates}:
            candidates.append({"text": content, "score": get_critic_score(content)})
            if source:
                sources.add(source)

    if not candidates:
        return {"text": None, "score": None, "error": "No creative candidate generated. Check Ollama or configure an LLM fallback."}

    best = max(candidates, key=lambda candidate: candidate["score"])
    logger.info("Selected best of %d candidate(s), critic score %.2f", len(candidates), best["score"])
    return {"text": best["text"], "score": best["score"], "source": ", ".join(sorted(sources)), "candidate_count": len(candidates)}

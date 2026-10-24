"""Central configuration, loaded without requiring optional service secrets."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    # Service credentials are optional at import time. Each service validates its
    # own requirements when it is actually used, so read-only/local app views work.
    DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("HOT_DB_URL")
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
    BSKY_HANDLE = os.getenv("BSKY_HANDLE")
    BSKY_PASSWORD = os.getenv("BSKY_PASSWORD")

    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    MODEL_DIR = PROJECT_ROOT / "models"
    BERT_BASE_MODEL = os.getenv("BERT_BASE_MODEL", "distilbert-base-uncased")
    BERT_REFINED_PATH = MODEL_DIR / "refined_bert"
    MAX_SEQ_LENGTH = int(os.getenv("MAX_SEQ_LENGTH", "128"))
    TRAINING_THRESHOLD = int(os.getenv("TRAINING_THRESHOLD", "50"))
    LABEL_MAP = {0: "REJECT", 1: "APPROVE"}
    DEFAULT_TOPICS = [
        topic.strip() for topic in os.getenv(
            "DEFAULT_TOPICS", "AI,fitness,skincare,food,travel,personal finance"
        ).split(",") if topic.strip()
    ]
    SCRAPE_LIMIT = max(1, min(int(os.getenv("SCRAPE_LIMIT", "10")), 50))

    @classmethod
    def get_active_bert_path(cls) -> str:
        """Use a locally fine-tuned critic when available, otherwise a DistilBERT base."""
        if (cls.BERT_REFINED_PATH / "config.json").exists():
            return str(cls.BERT_REFINED_PATH)
        return cls.BERT_BASE_MODEL

    @classmethod
    def require_database(cls) -> str:
        if not cls.DATABASE_URL:
            raise EnvironmentError("DATABASE_URL is required for database operations.")
        return cls.DATABASE_URL

    @classmethod
    def validate_config(cls, *, require_database: bool = True, require_youtube: bool = True):
        missing = []
        if require_database and not cls.DATABASE_URL:
            missing.append("DATABASE_URL")
        if require_youtube and not cls.YOUTUBE_API_KEY:
            missing.append("YOUTUBE_API_KEY")
        if missing:
            raise EnvironmentError(f"Missing required configuration: {', '.join(missing)}")
        cls.MODEL_DIR.mkdir(parents=True, exist_ok=True)

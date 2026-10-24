"""Shared application services and compatibility exports."""
from pathlib import Path
import sys
import types

# `1_ingestion` is kept as the source directory name; expose it as an importable
# package without importing its external scraping dependencies at app startup.
_ingestion_dir = Path(__file__).resolve().parent.parent / "1_ingestion"
if "ingestion" not in sys.modules:
    _ingestion_package = types.ModuleType("ingestion")
    _ingestion_package.__path__ = [str(_ingestion_dir)]
    sys.modules["ingestion"] = _ingestion_package

from .config import Config
from .database import get_neon_engine, save_to_bronze_batch, fetch_gold_prompts
from .logging import setup_logger
from .factory import ScraperFactory
from .exceptions import (
    RideTheTrendsError,
    QuotaExceededError,
    DatabaseConnectionError,
    ProviderAuthenticationError,
)

__all__ = [
    "Config", "get_neon_engine", "save_to_bronze_batch", "fetch_gold_prompts",
    "setup_logger", "ScraperFactory", "RideTheTrendsError", "QuotaExceededError",
    "DatabaseConnectionError", "ProviderAuthenticationError",
]

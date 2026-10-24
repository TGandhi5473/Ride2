"""Scheduled ingestion worker with run-level metrics and retry-safe writes."""
from datetime import datetime, timezone
import json
import uuid

from core import Config, ScraperFactory, save_to_bronze_batch, setup_logger
from core.database import ensure_ingestion_constraints
from core.exceptions import QuotaExceededError, RideTheTrendsError

logger = setup_logger("IngestionWorker")


def run_pipeline():
    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    Config.validate_config(require_database=True, require_youtube=True)
    cleanup = ensure_ingestion_constraints()
    logger.info(
        "Ingestion run started run_id=%s topics=%d removed_existing_duplicates=%d",
        run_id, len(Config.DEFAULT_TOPICS), cleanup["removed_duplicates"],
    )

    scrapers = []
    for platform in ("youtube", "bluesky"):
        try:
            scrapers.append(ScraperFactory.get_scraper(platform))
        except RideTheTrendsError:
            # Never log provider exception strings: authentication/client errors can
            # include request URLs or credential-adjacent data.
            logger.error("Could not initialize %s scraper run_id=%s", platform, run_id)

    per_platform = {}
    failures = 0
    for scraper in scrapers:
        metrics = {"requests": 0, "results": 0, "inserted": 0, "duplicates": 0, "errors": 0}
        if not scraper.is_active:
            per_platform[scraper.platform] = metrics
            logger.warning("Provider inactive platform=%s run_id=%s", scraper.platform, run_id)
            continue
        records = []
        for topic in Config.DEFAULT_TOPICS:
            try:
                metrics["requests"] += 1
                topic_records = scraper.run(topic, limit=Config.SCRAPE_LIMIT)
                metrics["results"] += len(topic_records)
                records.extend(topic_records)
            except QuotaExceededError as exc:
                scraper.is_active = False
                metrics["errors"] += 1
                failures += 1
                logger.error("Quota stop platform=%s topic=%r run_id=%s", scraper.platform, topic, run_id)
                break
            except Exception as exc:
                metrics["errors"] += 1
                failures += 1
                logger.error(
                    "Provider request failed platform=%s topic=%r run_id=%s error_type=%s",
                    scraper.platform, topic, run_id, type(exc).__name__,
                )
        if records:
            write_result = save_to_bronze_batch(records)
            metrics["inserted"] = write_result["inserted"]
            metrics["duplicates"] = write_result["duplicates"]
        per_platform[scraper.platform] = metrics
        logger.info("Provider metrics run_id=%s platform=%s metrics=%s", run_id, scraper.platform, json.dumps(metrics, sort_keys=True))

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    summary = {"run_id": run_id, "started_at": started.isoformat(), "duration_seconds": round(elapsed, 2),
               "failures": failures, "providers": per_platform}
    logger.info("Ingestion run finished summary=%s", json.dumps(summary, sort_keys=True))
    if failures:
        logger.warning("Run completed with provider errors run_id=%s count=%d", run_id, failures)
    return summary


if __name__ == "__main__":
    run_pipeline()

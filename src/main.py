#!/usr/bin/env python3
"""AI News Daily - Main entry point.

Usage:
    python main.py          # run pipeline locally
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import now_beijing, now_utc, settings
from .ranker import rank, split_by_type, score_item
from .sources import fetch_all
from .summarizer import build_report
from .notifier import send_report

logger = logging.getLogger(__name__)


def _save_cache(items: list[dict]) -> None:
    """
    Save raw data cache to JSON.
    All paths live under settings.DATA_DIR so they never escape the container.
    """
    try:
        cache_dir = Path(settings.DATA_DIR) / "ai-news-daily"
        cache_dir.mkdir(parents=True, exist_ok=True)
        today = now_beijing().strftime("%Y-%m-%d")
        cache_file = cache_dir / f"raw_{today}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        logger.info("Raw data saved to %s", cache_file)
    except Exception as exc:
        logger.error("Cache write failed: %s", exc)


def _save_report(report_md: str) -> None:
    try:
        cache_dir = Path(settings.DATA_DIR) / "ai-news-daily"
        cache_dir.mkdir(parents=True, exist_ok=True)
        today = now_beijing().strftime("%Y-%m-%d")
        out_file = cache_dir / f"report_{today}.md"
        out_file.write_text(report_md, encoding="utf-8")
        logger.info("Report saved to %s", out_file)
    except Exception as exc:
        logger.error("Report save failed: %s", exc)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("Starting AI News Daily ...")

    # 1. Fetch
    logger.info("Fetching sources (lookback=24h) ...")
    raw_items: list[dict] = fetch_all(lookback_hours=24)
    logger.info("Total AI items fetched: %d", len(raw_items))

    if not raw_items:
        logger.warning("No items fetched. Check source connectivity and logs.")

    # 2. Cache raw
    _save_cache(raw_items)

    # 3. Rank & split
    # sort by interaction score as soft-prior for next stages
    raw_items.sort(key=score_item, reverse=True)
    grouped = split_by_type(raw_items)
    ranked = {k: rank(v) for k, v in grouped.items()}

    # 4. Summarize
    logger.info("Building report via LLM ...")
    report = build_report(ranked, max_top10=settings.MAX_ITEMS_PER_SECTION)
    logger.info("Report built (%d chars).", len(report))

    # 5. Save report artifact
    _save_report(report)

    # 6. Push
    ch = settings.active_push_channel()
    logger.info("Active push channel: %s", ch)
    if not send_report(report):
        # Log the report so we don't lose it
        logger.warning("Push not sent; report remains cached in data/ai-news-daily/.")
        sys.exit(1)

    logger.info("Done. AI News Daily run complete.")


if __name__ == "__main__":
    run()

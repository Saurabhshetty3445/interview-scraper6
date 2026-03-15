"""
main.py — Railway entry point.

Runs forever in a loop:
  1. Poll LeetCode for new interview posts
  2. Scrape + parse + deduplicate + save to CSV + push to Google Sheets
  3. Sleep for POLL_INTERVAL_MINUTES
  4. Repeat

Railway keeps this process alive 24/7 automatically.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

from config import POLL_INTERVAL_MINUTES
from monitor import Monitor
from worker import WorkerPool
from storage import Storage
from deduplicate import Deduplicator

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),          # Railway shows stdout logs
        logging.FileHandler("logs.txt", encoding="utf-8"),
    ],
)
logger = logging.getLogger("scraper.main")


async def run_cycle(monitor: Monitor, pool: WorkerPool) -> int:
    logger.info("═══════════ Starting scraping cycle ═══════════")
    posts = await monitor.fetch_new_posts()
    if not posts:
        logger.info("No new relevant posts found.")
        return 0
    logger.info(f"Queuing {len(posts)} post(s) for scraping …")
    saved = await pool.process(posts)
    logger.info(f"Cycle done — {saved} new record(s) saved.")
    return saved


async def main():
    logger.info("🚀 LeetCode Interview Scraper starting on Railway …")
    logger.info(f"   Poll interval : {POLL_INTERVAL_MINUTES} minute(s)")

    storage      = Storage()
    deduplicator = Deduplicator()
    monitor      = Monitor()
    pool         = WorkerPool(storage=storage, deduplicator=deduplicator, max_workers=3)

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"── Cycle #{cycle} ──")
        try:
            await run_cycle(monitor, pool)
        except Exception as e:
            logger.error(f"Cycle #{cycle} crashed: {e}", exc_info=True)

        logger.info(f"Sleeping {POLL_INTERVAL_MINUTES} min until next cycle …")
        await asyncio.sleep(POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(main())

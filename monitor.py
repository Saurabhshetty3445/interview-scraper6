"""
monitor.py — Only scrapes NEW posts published after the scraper started.

First run behaviour:
  - Fetches current 50 posts, marks ALL as seen, saves NONE.
  - This sets the "baseline" — everything before now is ignored.

Every run after:
  - Fetches latest posts.
  - Any ID not in seen list = genuinely new post published after baseline.
  - Only those get scraped and saved.
"""

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import List, Dict, Any

import aiohttp

from config import (
    GRAPHQL_URL, HEADERS_POOL, REQUEST_TIMEOUT,
    MONITOR_PAGE_SIZE, PROCESSED_IDS_FILE,
    QUEUE_FILE, TARGET_PHRASES, MIN_DELAY, MAX_DELAY,
)

logger = logging.getLogger("scraper.monitor")

BASELINE_DONE_FILE = "baseline_done.txt"


class Monitor:
    def __init__(self):
        self._seen: set = self._load_seen()
        self._baseline_done: bool = Path(BASELINE_DONE_FILE).exists()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_seen(self) -> set:
        p = Path(PROCESSED_IDS_FILE)
        if p.exists():
            ids = set(
                line.strip()
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            logger.info(f"Loaded {len(ids)} processed IDs.")
            return ids
        return set()

    def _save_seen(self):
        Path(PROCESSED_IDS_FILE).write_text(
            "\n".join(sorted(self._seen)), encoding="utf-8"
        )

    def _mark_baseline_done(self):
        Path(BASELINE_DONE_FILE).write_text("done", encoding="utf-8")
        self._baseline_done = True
        logger.info("Baseline set. From next cycle, only NEW posts will be scraped.")

    # ── Relevance ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_relevant(title: str) -> bool:
        lower = title.lower()
        return any(p in lower for p in TARGET_PHRASES)

    # ── GraphQL ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_query(skip: int = 0, first: int = MONITOR_PAGE_SIZE) -> Dict[str, Any]:
        return {
            "operationName": "categoryTopicList",
            "variables": {
                "orderBy": "newest_to_oldest",
                "query": "",
                "skip": skip,
                "first": first,
                "tags": [],
                "categories": ["interview-experience"],
            },
            "query": """query categoryTopicList($categories: [String!]!, $first: Int!, $orderBy: TopicSortingOption, $skip: Int, $query: String, $tags: [String!]) {
  categoryTopicList(categories: $categories, first: $first, orderBy: $orderBy, skip: $skip, query: $query, tags: $tags) {
    edges {
      node {
        id
        title
        post {
          creationDate
          author {
            username
          }
        }
      }
    }
  }
}""",
        }

    @staticmethod
    def _build_headers() -> Dict[str, str]:
        base = random.choice(HEADERS_POOL).copy()
        base.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://leetcode.com",
            "Referer": "https://leetcode.com/discuss/interview-experience/",
        })
        return base

    # ── HTTP fetch ─────────────────────────────────────────────────────────────

    async def _fetch_edges(self) -> List[Dict[str, Any]]:
        headers = self._build_headers()
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout
        ) as session:

            # Warm up — get session cookies first
            try:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                async with session.get(
                    "https://leetcode.com/discuss/interview-experience/",
                    headers=headers,
                    allow_redirects=True,
                ) as pre:
                    logger.debug(f"Pre-visit: {pre.status}")
            except Exception as e:
                logger.debug(f"Pre-visit skipped: {e}")

            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            try:
                async with session.post(
                    GRAPHQL_URL,
                    json=self._build_query(),
                    headers=headers,
                ) as resp:
                    status = resp.status

                    if status == 429:
                        logger.warning("Rate limited (429) — waiting 60s.")
                        await asyncio.sleep(60)
                        return []
                    if status == 403:
                        logger.warning("403 Forbidden.")
                        return []
                    if status == 400:
                        body = await resp.text()
                        logger.error(f"400 Bad Request: {body[:500]}")
                        return []
                    if not resp.ok:
                        logger.warning(f"HTTP {status} — skipping.")
                        return []

                    data = await resp.json(content_type=None)

            except asyncio.TimeoutError:
                logger.error("Monitor request timed out.")
                return []
            except Exception as e:
                logger.error(f"Monitor request failed: {e}")
                return []

        if "errors" in data:
            logger.error(f"GraphQL errors: {data['errors']}")
            return []

        return (
            data.get("data", {})
                .get("categoryTopicList", {})
                .get("edges", [])
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def fetch_new_posts(self) -> List[Dict[str, Any]]:
        edges = await self._fetch_edges()

        if not edges:
            return []

        # ── FIRST RUN: set baseline, scrape nothing ────────────────────────────
        if not self._baseline_done:
            count = 0
            for edge in edges:
                pid = str(edge.get("node", {}).get("id", ""))
                if pid:
                    self._seen.add(pid)
                    count += 1
            self._save_seen()
            self._mark_baseline_done()
            logger.info(
                f"BASELINE: Marked {count} existing posts as seen. "
                f"Scraper will only collect posts published from NOW onwards."
            )
            return []  # nothing to scrape on first run

        # ── SUBSEQUENT RUNS: only new posts ───────────────────────────────────
        new_posts: List[Dict[str, Any]] = []

        for edge in edges:
            node  = edge.get("node", {})
            pid   = str(node.get("id", ""))
            title = node.get("title", "")
            date  = node.get("post", {}).get("creationDate", 0)

            if not pid:
                continue

            # Already seen — skip silently
            if pid in self._seen:
                continue

            # Mark seen immediately (relevant or not)
            self._seen.add(pid)

            # Relevance filter
            if not self._is_relevant(title):
                logger.info(f"Skipped (not interview-related): {title!r}")
                continue

            url = f"https://leetcode.com/discuss/interview-experience/{pid}/"
            new_posts.append({
                "id":    pid,
                "title": title,
                "date":  date,
                "url":   url,
            })
            logger.info(f"New relevant post found: {title!r}")

        self._save_seen()
        Path(QUEUE_FILE).write_text(
            json.dumps(new_posts, indent=2), encoding="utf-8"
        )

        if new_posts:
            logger.info(
                f"Monitor: {len(edges)} checked, "
                f"{len(new_posts)} NEW relevant post(s) queued."
            )
        else:
            logger.info(
                f"Monitor: {len(edges)} checked, "
                f"0 new relevant posts — waiting for new activity."
            )

        return new_posts

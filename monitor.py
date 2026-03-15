"""
monitor.py — Polls LeetCode Discuss GraphQL for new interview posts.
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


class Monitor:
    def __init__(self):
        self._seen: set = self._load_seen()

    def _load_seen(self) -> set:
        p = Path(PROCESSED_IDS_FILE)
        if p.exists():
            ids = set(line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
            logger.info(f"Loaded {len(ids)} processed IDs.")
            return ids
        return set()

    def _save_seen(self):
        Path(PROCESSED_IDS_FILE).write_text(
            "\n".join(sorted(self._seen)), encoding="utf-8"
        )

    @staticmethod
    def _is_relevant(title: str) -> bool:
        lower = title.lower()
        return any(p in lower for p in TARGET_PHRASES)

    @staticmethod
    def _build_query(skip: int = 0) -> Dict[str, Any]:
        return {
            "operationName": "categoryTopicList",
            "variables": {
                "orderBy": "newest_to_oldest",
                "query": "",
                "skip": skip,
                "first": MONITOR_PAGE_SIZE,
                "tags": [],
                "categories": ["interview-experience"],
            },
            "query": """
            query categoryTopicList(
                $categories: [String!]!, $first: Int!,
                $orderBy: TopicSortingOption, $skip: Int,
                $query: String, $tags: [String!]
            ) {
              categoryTopicList(
                categories: $categories first: $first
                orderBy: $orderBy skip: $skip
                query: $query tags: $tags
              ) {
                edges {
                  node {
                    id title slug creationDate
                    tags { name }
                  }
                }
              }
            }
            """,
        }

    async def fetch_new_posts(self) -> List[Dict[str, Any]]:
        new_posts = []
        headers = random.choice(HEADERS_POOL)
        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            try:
                async with session.post(
                    GRAPHQL_URL,
                    json=self._build_query(),
                    headers=headers,
                ) as resp:
                    if resp.status == 429:
                        logger.warning("Rate limited (429) — waiting 60s.")
                        await asyncio.sleep(60)
                        return []
                    if resp.status in (403, 503):
                        logger.warning(f"HTTP {resp.status} — skipping cycle.")
                        return []
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except asyncio.TimeoutError:
                logger.error("Monitor request timed out.")
                return []
            except Exception as e:
                logger.error(f"Monitor request failed: {e}")
                return []

        edges = (
            data.get("data", {})
                .get("categoryTopicList", {})
                .get("edges", [])
        )

        for edge in edges:
            node = edge.get("node", {})
            pid  = str(node.get("id", ""))
            title = node.get("title", "")
            slug  = node.get("slug", "")
            date  = node.get("creationDate", 0)

            if not pid or not slug:
                continue
            if pid in self._seen:
                continue
            if not self._is_relevant(title):
                logger.debug(f"Irrelevant: {title!r}")
                self._seen.add(pid)
                continue

            new_posts.append({"id": pid, "title": title, "slug": slug, "date": date})
            self._seen.add(pid)

        self._save_seen()

        # Save queue snapshot for visibility
        Path(QUEUE_FILE).write_text(json.dumps(new_posts, indent=2), encoding="utf-8")

        logger.info(
            f"Monitor: {len(edges)} fetched, {len(new_posts)} new relevant post(s)."
        )
        return new_posts

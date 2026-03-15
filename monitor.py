"""
monitor.py — Polls LeetCode Discuss for new interview posts.
Fixed: uses correct GraphQL query that LeetCode currently accepts.
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

    @staticmethod
    def _is_relevant(title: str) -> bool:
        lower = title.lower()
        return any(p in lower for p in TARGET_PHRASES)

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
            "query": (
                "query categoryTopicList("
                "$categories: [String!]!, $first: Int!, "
                "$orderBy: TopicSortingOption, $skip: Int, "
                "$query: String, $tags: [String!]"
                ") { "
                "categoryTopicList("
                "categories: $categories "
                "first: $first "
                "orderBy: $orderBy "
                "skip: $skip "
                "query: $query "
                "tags: $tags"
                ") { "
                "edges { "
                "node { "
                "id title slug creationDate "
                "} "
                "} "
                "} "
                "}"
            ),
        }

    async def fetch_new_posts(self) -> List[Dict[str, Any]]:
        new_posts = []

        # Build headers with required cookies/tokens LeetCode expects
        base_headers = random.choice(HEADERS_POOL).copy()
        base_headers.update({
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://leetcode.com",
            "Referer": "https://leetcode.com/discuss/interview-experience/",
            "x-requested-with": "XMLHttpRequest",
        })

        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=base_headers,
        ) as session:

            # First visit the discuss page to get cookies
            try:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                async with session.get(
                    "https://leetcode.com/discuss/interview-experience/",
                    allow_redirects=True,
                ) as pre:
                    logger.debug(f"Pre-visit status: {pre.status}")
            except Exception as e:
                logger.debug(f"Pre-visit failed (non-fatal): {e}")

            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            try:
                async with session.post(
                    GRAPHQL_URL,
                    json=self._build_query(),
                ) as resp:
                    status = resp.status

                    if status == 429:
                        logger.warning("Rate limited (429) — waiting 60s.")
                        await asyncio.sleep(60)
                        return []

                    if status == 403:
                        logger.warning("403 Forbidden — LeetCode blocked request.")
                        return []

                    if status == 400:
                        body = await resp.text()
                        logger.error(f"400 Bad Request — response: {body[:300]}")
                        return []

                    if not resp.ok:
                        logger.warning(f"HTTP {status} — skipping cycle.")
                        return []

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

        if not edges and "errors" in data:
            logger.error(f"GraphQL errors: {data['errors']}")
            return []

        for edge in edges:
            node  = edge.get("node", {})
            pid   = str(node.get("id", ""))
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
        Path(QUEUE_FILE).write_text(json.dumps(new_posts, indent=2), encoding="utf-8")

        logger.info(
            f"Monitor: {len(edges)} fetched, "
            f"{len(new_posts)} new relevant post(s)."
        )
        return new_posts

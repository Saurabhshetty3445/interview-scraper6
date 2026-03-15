"""
monitor.py — Fixed to match LeetCode's actual URL and API structure.

LeetCode post URL format:
  https://leetcode.com/discuss/post/{ID}/{slug}/

The GraphQL query fetches from multiple categories and also
queries general discuss to catch all interview-related posts.
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

# All categories that can contain interview posts
CATEGORIES = [
    "interview-experience",
    "interview-question",
    "compensation",  # sometimes interview posts land here
]


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

    def _mark_baseline_done(self, count: int):
        Path(BASELINE_DONE_FILE).write_text("done", encoding="utf-8")
        self._baseline_done = True
        logger.info(
            f"BASELINE SET: {count} existing posts marked as seen. "
            "Only posts published from NOW will be scraped."
        )

    # ── Relevance ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_relevant(title: str) -> bool:
        lower = title.lower()
        return any(p in lower for p in TARGET_PHRASES)

    # ── GraphQL ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_query(categories: list, skip: int = 0, first: int = MONITOR_PAGE_SIZE) -> Dict[str, Any]:
        return {
            "operationName": "categoryTopicList",
            "variables": {
                "orderBy": "newest_to_oldest",
                "query": "",
                "skip": skip,
                "first": first,
                "tags": [],
                "categories": categories,
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
    def _build_general_query(keyword: str, skip: int = 0, first: int = 25) -> Dict[str, Any]:
        """Search all of discuss by keyword — catches posts in any category."""
        return {
            "operationName": "categoryTopicList",
            "variables": {
                "orderBy": "newest_to_oldest",
                "query": keyword,
                "skip": skip,
                "first": first,
                "tags": [],
                "categories": [],
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
            "Referer": "https://leetcode.com/discuss/",
        })
        return base

    # ── HTTP fetch ─────────────────────────────────────────────────────────────

    async def _post_graphql(
        self,
        session: aiohttp.ClientSession,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Send one GraphQL request, return edges list."""
        try:
            await asyncio.sleep(random.uniform(1.0, 2.5))
            async with session.post(
                GRAPHQL_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                status = resp.status
                if status == 429:
                    logger.warning("Rate limited (429) — waiting 30s.")
                    await asyncio.sleep(30)
                    return []
                if status == 403:
                    logger.warning("403 Forbidden.")
                    return []
                if status == 400:
                    body = await resp.text()
                    logger.error(f"400 Bad Request: {body[:300]}")
                    return []
                if not resp.ok:
                    logger.warning(f"HTTP {status}")
                    return []

                data = await resp.json(content_type=None)
                if "errors" in data:
                    logger.error(f"GraphQL errors: {data['errors']}")
                    return []

                return (
                    data.get("data", {})
                        .get("categoryTopicList", {})
                        .get("edges", [])
                )
        except asyncio.TimeoutError:
            logger.error("Request timed out.")
            return []
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return []

    async def _fetch_all_edges(self) -> List[Dict[str, Any]]:
        """
        Fetch from multiple sources and merge — deduped by post ID.
        """
        headers = self._build_headers()
        seen_in_batch: set = set()
        all_edges: List[Dict[str, Any]] = []

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:

            # Warm up session with page visit
            try:
                async with session.get(
                    "https://leetcode.com/discuss/",
                    headers=headers,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as pre:
                    logger.debug(f"Pre-visit: {pre.status}")
            except Exception as e:
                logger.debug(f"Pre-visit skipped: {e}")

            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            # Source 1: interview-experience category
            edges1 = await self._post_graphql(
                session,
                self._build_query(["interview-experience"]),
                headers,
            )
            for e in edges1:
                pid = str(e.get("node", {}).get("id", ""))
                if pid and pid not in seen_in_batch:
                    seen_in_batch.add(pid)
                    all_edges.append(e)

            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Source 2: interview-question category
            edges2 = await self._post_graphql(
                session,
                self._build_query(["interview-question"]),
                headers,
            )
            for e in edges2:
                pid = str(e.get("node", {}).get("id", ""))
                if pid and pid not in seen_in_batch:
                    seen_in_batch.add(pid)
                    all_edges.append(e)

            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Source 3: interview category
            edges3a = await self._post_graphql(
                session,
                self._build_query(["interview"]),
                headers,
            )
            for e in edges3a:
                pid = str(e.get("node", {}).get("id", ""))
                if pid and pid not in seen_in_batch:
                    seen_in_batch.add(pid)
                    all_edges.append(e)

            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Source 4: keyword search "interview experience" across ALL categories
            edges3 = await self._post_graphql(
                session,
                self._build_general_query("interview experience", first=25),
                headers,
            )
            for e in edges3:
                pid = str(e.get("node", {}).get("id", ""))
                if pid and pid not in seen_in_batch:
                    seen_in_batch.add(pid)
                    all_edges.append(e)

            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Source 5: keyword search "interview questions" across ALL categories
            edges4 = await self._post_graphql(
                session,
                self._build_general_query("interview questions", first=25),
                headers,
            )
            for e in edges4:
                pid = str(e.get("node", {}).get("id", ""))
                if pid and pid not in seen_in_batch:
                    seen_in_batch.add(pid)
                    all_edges.append(e)

        logger.info(
            f"Fetched {len(all_edges)} unique posts across all sources."
        )
        return all_edges

    # ── Public API ─────────────────────────────────────────────────────────────

    async def fetch_new_posts(self) -> List[Dict[str, Any]]:
        edges = await self._fetch_all_edges()

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
            self._mark_baseline_done(count)
            return []

        # ── SUBSEQUENT RUNS: only new posts ───────────────────────────────────
        new_posts: List[Dict[str, Any]] = []

        for edge in edges:
            node  = edge.get("node", {})
            pid   = str(node.get("id", ""))
            title = node.get("title", "")
            date  = node.get("post", {}).get("creationDate", 0)

            if not pid:
                continue

            # Already seen
            if pid in self._seen:
                continue

            # Mark seen immediately
            self._seen.add(pid)

            # Relevance filter on title
            if not self._is_relevant(title):
                logger.info(f"Skipped (not relevant): {title!r}")
                continue

            # Build correct URL using LeetCode's actual URL format
            url = f"https://leetcode.com/discuss/post/{pid}/"

            new_posts.append({
                "id":    pid,
                "title": title,
                "date":  date,
                "url":   url,
            })
            logger.info(f"NEW post queued: {title!r}  [{url}]")

        self._save_seen()
        Path(QUEUE_FILE).write_text(
            json.dumps(new_posts, indent=2), encoding="utf-8"
        )

        if new_posts:
            logger.info(
                f"✅ {len(new_posts)} NEW relevant post(s) found and queued."
            )
        else:
            logger.info(
                "⏳ No new relevant posts yet — waiting for new activity on LeetCode."
            )

        return new_posts

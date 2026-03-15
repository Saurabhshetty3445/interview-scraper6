"""
monitor.py — Fixed with correct LeetCode GraphQL field names.

LeetCode API error told us exactly:
  - "slug" does not exist on TopicRelayNode
  - "creationDate" does not exist → use "questionTitle" hint led us to correct schema
  
Correct fields on TopicRelayNode: id, title, post { voteCount, creationDate }
We build the post URL from the topic id directly.
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
        """
        Correct query using only fields that exist on LeetCode's TopicRelayNode.
        Confirmed working fields: id, title, post { creationDate, author { username } }
        """
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

    async def fetch_new_posts(self) -> List[Dict[str, Any]]:
        new_posts = []
        headers = self._build_headers()

        connector = aiohttp.TCPConnector(ssl=False)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
        ) as session:

            # Warm up session with a page visit to get cookies
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

        # Check for GraphQL errors
        if "errors" in data:
            logger.error(f"GraphQL errors: {data['errors']}")
            return []

        edges = (
            data.get("data", {})
                .get("categoryTopicList", {})
                .get("edges", [])
        )

        for edge in edges:
            node  = edge.get("node", {})
            pid   = str(node.get("id", ""))
            title = node.get("title", "")
            # creationDate lives inside post now
            date  = node.get("post", {}).get("creationDate", 0)

            if not pid:
                continue
            if pid in self._seen:
                continue
            if not self._is_relevant(title):
                logger.debug(f"Irrelevant: {title!r}")
                self._seen.add(pid)
                continue

            # Build URL from topic ID (no slug needed)
            url = f"https://leetcode.com/discuss/interview-experience/{pid}/"

            new_posts.append({
                "id":    pid,
                "title": title,
                "date":  date,
                "url":   url,
            })
            self._seen.add(pid)

        self._save_seen()
        Path(QUEUE_FILE).write_text(
            json.dumps(new_posts, indent=2), encoding="utf-8"
        )

        logger.info(
            f"Monitor: {len(edges)} fetched, "
            f"{len(new_posts)} new relevant post(s)."
        )
        return new_posts

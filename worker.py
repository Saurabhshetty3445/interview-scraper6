"""
worker.py — Fetch full post content using correct LeetCode URL format.

LeetCode post URL: https://leetcode.com/discuss/post/{ID}/
GraphQL fetch by topic ID still works the same way.
"""

import asyncio
import logging
import random
from typing import List, Dict, Any

import aiohttp

from config import (
    GRAPHQL_URL, HEADERS_POOL, REQUEST_TIMEOUT,
    MIN_DELAY, MAX_DELAY, MAX_RETRIES, BACKOFF_BASE,
)
from parser import Parser
from deduplicate import Deduplicator
from storage import Storage

logger = logging.getLogger("scraper.worker")


def _detail_query(topic_id: str) -> Dict[str, Any]:
    return {
        "operationName": "DiscussTopic",
        "variables": {"topicId": int(topic_id)},
        "query": """query DiscussTopic($topicId: Int!) {
  topic(id: $topicId) {
    id
    title
    post {
      creationDate
      content
      author {
        username
      }
    }
  }
}""",
    }


async def _fetch_topic(
    session: aiohttp.ClientSession,
    post: Dict[str, Any],
) -> Dict[str, Any] | None:
    tid = post["id"]
    headers = random.choice(HEADERS_POOL).copy()
    headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://leetcode.com",
        "Referer": f"https://leetcode.com/discuss/post/{tid}/",
    })

    for attempt in range(1, MAX_RETRIES + 1):
        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        try:
            async with session.post(
                GRAPHQL_URL,
                json=_detail_query(tid),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 429:
                    wait = BACKOFF_BASE ** attempt + random.uniform(0, 2)
                    logger.warning(f"[{tid}] 429 — waiting {wait:.1f}s.")
                    await asyncio.sleep(wait)
                    continue
                if resp.status in (403, 404):
                    logger.warning(f"[{tid}] HTTP {resp.status} — skipping.")
                    return None
                if resp.status == 400:
                    body = await resp.text()
                    logger.error(f"[{tid}] 400 Bad Request: {body[:300]}")
                    return None
                if not resp.ok:
                    await asyncio.sleep(BACKOFF_BASE ** attempt)
                    continue

                data = await resp.json(content_type=None)
                if "errors" in data:
                    logger.error(f"[{tid}] GraphQL errors: {data['errors']}")
                    return None

                topic = data.get("data", {}).get("topic")
                if not topic:
                    logger.warning(f"[{tid}] Empty topic in response.")
                    return None

                # Hoist creationDate to top level for parser
                if topic.get("post", {}).get("creationDate"):
                    topic["creationDate"] = topic["post"]["creationDate"]

                return topic

        except asyncio.TimeoutError:
            logger.warning(f"[{tid}] Timeout attempt {attempt}/{MAX_RETRIES}.")
            await asyncio.sleep(BACKOFF_BASE ** attempt)
        except Exception as e:
            logger.error(f"[{tid}] Error attempt {attempt}: {e}")
            await asyncio.sleep(BACKOFF_BASE ** attempt)

    logger.error(f"[{tid}] All {MAX_RETRIES} attempts failed.")
    return None


class WorkerPool:
    def __init__(
        self,
        storage: Storage,
        deduplicator: Deduplicator,
        max_workers: int = 3,
    ):
        self._storage     = storage
        self._dedup       = deduplicator
        self._parser      = Parser()
        self._max_workers = max_workers

    async def process(self, posts: List[Dict[str, Any]]) -> int:
        sem   = asyncio.Semaphore(self._max_workers)
        queue: asyncio.Queue = asyncio.Queue()
        for p in posts:
            await queue.put(p)

        connector = aiohttp.TCPConnector(ssl=False, limit=self._max_workers + 2)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                asyncio.create_task(self._worker(session, queue, sem))
                for _ in range(min(self._max_workers, len(posts)))
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        total = 0
        for r in results:
            if isinstance(r, int):
                total += r
            elif isinstance(r, Exception):
                logger.error(f"Worker exception: {r}")
        return total

    async def _worker(self, session, queue, sem) -> int:
        saved = 0
        while True:
            try:
                post = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            async with sem:
                if await self._process_one(session, post):
                    saved += 1
            queue.task_done()
        return saved

    async def _process_one(self, session, post) -> bool:
        tid = post["id"]
        url = post.get("url", f"https://leetcode.com/discuss/post/{tid}/")

        logger.info(f"[{tid}] Fetching full content from {url}")

        topic = await _fetch_topic(session, post)
        if topic is None:
            return False

        try:
            record = self._parser.parse(topic, url)
        except Exception as e:
            logger.error(f"[{tid}] Parser error: {e}")
            return False

        if record is None:
            logger.info(f"[{tid}] Parser returned no record.")
            return False

        dup = self._dedup.check(record)
        if dup:
            logger.info(f"[{tid}] Duplicate ({dup}) — skipped.")
            return False

        try:
            self._storage.save(record)
            self._dedup.register(record)
            logger.info(
                f"[{tid}] ✅ SAVED — "
                f"{record['company']} | {record['title'][:70]}"
            )
            return True
        except Exception as e:
            logger.error(f"[{tid}] Storage error: {e}")
            return False

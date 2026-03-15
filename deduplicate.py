"""
deduplicate.py — Three-layer duplicate detection.
Layer 1: URL   Layer 2: SHA-256 hash   Layer 3: Fuzzy similarity
"""

import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Any, Optional

from config import HASHES_FILE, FUZZY_THRESHOLD

logger = logging.getLogger("scraper.deduplicator")


class Deduplicator:
    def __init__(self):
        self._hashes: set  = self._load_hashes()
        self._urls: set    = set()
        self._snippets: list = []
        self._max_cache    = 500

    def _load_hashes(self) -> set:
        p = Path(HASHES_FILE)
        if p.exists():
            h = set(line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
            logger.info(f"Loaded {len(h)} hashes.")
            return h
        return set()

    def _save_hashes(self):
        Path(HASHES_FILE).write_text("\n".join(sorted(self._hashes)), encoding="utf-8")

    def check(self, record: Dict[str, Any]) -> Optional[str]:
        url     = record.get("url", "")
        h       = record.get("content_hash", "")
        snippet = record.get("body_snippet", "")

        if url and url in self._urls:
            return "url"
        if h and h in self._hashes:
            return "content_hash"
        for cached in self._snippets:
            ratio = SequenceMatcher(None, snippet, cached, autojunk=False).ratio()
            if ratio >= FUZZY_THRESHOLD:
                return f"fuzzy({ratio:.2f})"
        return None

    def register(self, record: Dict[str, Any]):
        if url := record.get("url"):
            self._urls.add(url)
        if h := record.get("content_hash"):
            self._hashes.add(h)
            self._save_hashes()
        if s := record.get("body_snippet"):
            self._snippets.append(s)
            if len(self._snippets) > self._max_cache:
                self._snippets = self._snippets[-self._max_cache:]

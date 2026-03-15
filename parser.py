"""
parser.py — Extracts structured data from a raw LeetCode topic node.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Dict, Any, List, Optional

from config import TARGET_PHRASES, KNOWN_COMPANIES

logger = logging.getLogger("scraper.parser")

_COMPANY_CONTEXT_RE = re.compile(
    r"(?:at|@|for|with|from)\s+([A-Z][A-Za-z0-9\s&.\-]{1,40}?)"
    r"(?:\s+(?:interview|onsite|phone|virtual|hiring|offer|rejection|experience))",
    re.IGNORECASE,
)
_COMPANY_TITLE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9\s&.\-]{1,40}?)\s+"
    r"(?:Interview|SDE|Software|Engineer|Developer|Intern)",
    re.MULTILINE,
)
_QUESTION_RE = re.compile(
    r"""(?:(?:Q\.?\s*\d+[\s:\-–]+.+)|(?:\d+[\.\)]\s+.+\?)|(?:[A-Z][^.!?]{10,200}\?)|(?:(?:asked|given|told)\s+(?:me|us)\s+.+))""",
    re.MULTILINE,
)


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _extract_company(title: str, body: str) -> str:
    for src in (title, body[:500]):
        lower = src.lower()
        for c in KNOWN_COMPANIES:
            if c.lower() in lower:
                return c
    m = _COMPANY_CONTEXT_RE.search(title)
    if m:
        return m.group(1).strip().title()
    m = _COMPANY_TITLE_RE.search(title)
    if m:
        return m.group(1).strip().title()
    m = _COMPANY_CONTEXT_RE.search(f"{title} {body[:2000]}")
    if m:
        return m.group(1).strip().title()
    return "Unknown"


def _extract_questions(body: str) -> List[str]:
    seen, qs = set(), []
    for m in _QUESTION_RE.finditer(body):
        q = re.sub(r"\s+", " ", m.group(0).strip())
        if 15 <= len(q) <= 400 and q.lower() not in seen:
            seen.add(q.lower())
            qs.append(q)
    return qs[:30]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _unix_to_iso(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Parser:
    def parse(self, topic: Dict[str, Any], url: str) -> Optional[Dict[str, Any]]:
        title = (topic.get("title") or "").strip()
        raw   = topic.get("post", {}).get("content") or ""
        ts    = topic.get("creationDate")

        if not title and not raw:
            return None

        body = _strip_html(raw)
        combined = f"{title} {body}".lower()

        if not any(p in combined for p in TARGET_PHRASES):
            return None

        return {
            "company":      _extract_company(title, body),
            "title":        title,
            "url":          url,
            "date":         _unix_to_iso(ts),
            "content_hash": _sha256(f"{title}||{body[:1000]}"),
            "questions":    _extract_questions(body),
            "body_snippet": body[:500],
        }

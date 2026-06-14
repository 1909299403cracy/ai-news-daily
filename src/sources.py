"""Data source collectors.

Each collector returns a normalized list of dicts:
{
  "title": str,
  "url": str,
  "published_at": str | None,   # ISO-8601
  "source": str,                 # e.g. "Hacker News"
  "domain": str,                 # url hostname
  "summary": str | None,
  "extra": dict,                 # platform-specific metadata
}
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .config import settings

logger = logging.getLogger("ai-news-daily")

# ============================================================
# Helpers
# ============================================================

DOMAIN_PATTERN = re.compile(r"https?://(?:www\.)?([^/]+)")


def _domain(url: str) -> str:
    m = DOMAIN_PATTERN.search(url or "")
    return m.group(1) if m else ""


def _dedup_key(title: str, url: str) -> str:
    # stable near-id based on domain + slug
    raw = f"{_domain(url)}:{title.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _parse_date(raw) -> str | None:
    if not raw:
        return None
    try:
        dt = dateparser.parse(str(raw))
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat() if dt else None
    except Exception:
        return None


# ============================================================
# Base
# ============================================================

class BaseCollector:
    name: str = "base"
    weight: float = 1.0  # higher = more authoritative

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _coerce(self, title: str, url: str, published_at: str | None, source: str, **extra):
        domain = _domain(url)
        return {
            "title": (title or "").strip(),
            "url": url,
            "published_at": published_at,
            "source": source,
            "domain": domain,
            "extra": extra,
        }


# ============================================================
# Hacker News (Algolia)
# ============================================================

class HackerNewsCollector(BaseCollector):
    name = "Hacker News"
    weight = 1.3

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            # Search for AI-related stories in the last 24h
            url = "http://hn.algolia.com/api/v1/search"
            params = {
                "query": "AI OR LLM OR GPT OR Claude OR DeepMind OR OpenAI OR Anthropic OR Mistral OR Llama",
                "tags": "story",
                "numericFilters": f"created_at_i>{int(time.time()) - lookback_hours * 3600}",
                "hitsPerPage": 50,
            }
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            for hit in data.get("hits", []):
                if not hit.get("title"):
                    continue
                results.append(
                    self._coerce(
                        title=hit["title"],
                        url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                        published_at=_parse_date(hit.get("created_at")),
                        source="Hacker News",
                        points=hit.get("points"),
                        comments=hit.get("num_comments"),
                    )
                )
        except Exception as exc:
            logger.error("HN fetch failed: %s", exc)
        return results


# ============================================================
# GitHub Trending (RSS via GitHub feed)
# ============================================================

class GitHubTrendingCollector(BaseCollector):
    name = "GitHub Trending"
    weight = 1.2

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        # RSSHub style feeds: https://rsshub.app/github/trending/daily/python
        # Fallback: scrape trends directly
        feeds = [
            "https://rsshub.app/github/trending/daily/artificial-intelligence",
            "https://rsshub.app/github/trending/daily/machine-learning",
            "https://rsshub.app/github/trending/daily/deep-learning",
            "https://rsshub.app/github/trending/daily/python",
            "https://rsshub.app/github/trending/weekly/python",
        ]
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AI-News-Daily/1.0)"}
        for feed_url in feeds:
            try:
                r = requests.get(feed_url, headers=headers, timeout=20)
                if r.status_code != 200:
                    continue
                feed = feedparser.parse(r.content)
                for entry in feed.entries:
                    results.append(
                        self._coerce(
                            title=entry.get("title", ""),
                            url=entry.get("link", ""),
                            published_at=_parse_date(entry.get("published")),
                            source="GitHub Trending",
                        )
                    )
            except Exception as exc:
                logger.debug("GitHub RSS feed failed (%s): %s", feed_url, exc)
                continue
        if not results:
            # direct scrape fallback
            try:
                r = requests.get(
                    "https://github.com/trending/python?since=daily",
                    headers=headers,
                    timeout=20,
                )
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                for article in soup.select("article.Box-row"):
                    title_tag = article.select_one("h2 a")
                    if not title_tag:
                        continue
                    href = title_tag.get("href", "")
                    if not href.startswith("http"):
                        href = "https://github.com" + href
                    stars_tag = article.select_one("span.float-sm-right")
                    results.append(
                        self._coerce(
                            title=title_tag.get_text(strip=True),
                            url=href,
                            published_at=datetime.now(timezone.utc).isoformat(),
                            source="GitHub Trending",
                            stars=stars_tag.get_text(strip=True) if stars_tag else None,
                        )
                    )
            except Exception as exc:
                logger.error("GitHub trending scrape failed: %s", exc)
        return results


# ============================================================
# Product Hunt (RSS)
# ============================================================

class ProductHuntCollector(BaseCollector):
    name = "Product Hunt"
    weight = 1.1

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            r = requests.get(
                "https://www.producthunt.com/feed",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            if r.status_code == 200:
                feed = feedparser.parse(r.content)
                for entry in feed.entries:
                    title = entry.get("title", "")
                    # filter AI-ish
                    if any(k in title.lower() for k in ["ai", "llm", "gpt", "claude", "bot", "assistant", "machine learning", "ml"]):
                        results.append(
                            self._coerce(
                                title=title,
                                url=entry.get("link", ""),
                                published_at=_parse_date(entry.get("published")),
                                source="Product Hunt",
                            )
                        )
        except Exception as exc:
            logger.error("Product Hunt RSS failed: %s", exc)
        return results


# ============================================================
# Reddit public JSON (no auth, read-only)
# ============================================================

class RedditCollector(BaseCollector):
    name = "Reddit"
    weight = 1.0

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        subreddits = [
            "artificial",
            "MachineLearning",
            "LocalLLaMA",
            "OpenAI",
            "Anthropic",
            "StableDiffusion",
            "MachineLearning",
        ]
        since = int(time.time()) - lookback_hours * 3600
        headers = {"User-Agent": "AI-News-Daily/1.0"}
        for sub in subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/new.json?limit=25&t=day"
                r = requests.get(url, headers=headers, timeout=15)
                if r.status_code != 200:
                    continue
                data = r.json()
                for child in data.get("data", {}).get("children", []):
                    item = child.get("data", {})
                    created = item.get("created_utc")
                    if not created or created < since:
                        continue
                    title = item.get("title", "")
                    # AI filter
                    keywords = "ai llm gpt claude deepmind openai anthropic mistral llama diffusion transformer".split()
                    if not any(k in title.lower() for k in keywords):
                        continue
                    permalink = item.get("permalink", "")
                    link = f"https://www.reddit.com{permalink}"
                    score = item.get("score", 0)
                    num_comments = item.get("num_comments", 0)
                    results.append(
                        self._coerce(
                            title=title,
                            url=link,
                            published_at=_parse_date(created),
                            source="Reddit",
                            score=score,
                            comments=num_comments,
                        )
                    )
            except Exception as exc:
                logger.debug("Reddit r/%s fetch failed: %s", sub, exc)
                continue
        return results


# ============================================================
# Google News RSS (search)
# ============================================================

class GoogleNewsCollector(BaseCollector):
    name = "Google News"
    weight = 1.0

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        queries = [
            "Artificial Intelligence news",
            "OpenAI announcement",
            "Anthropic Claude",
            "Google DeepMind",
            "NVIDIA AI",
            "xAI Grok",
            "Mistral AI",
            "AI regulation",
            "AI funding",
            "LLM model release",
        ]
        for q in queries:
            try:
                r = requests.get(
                    "https://news.google.com/rss/search",
                    params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                if r.status_code != 200:
                    continue
                feed = feedparser.parse(r.content)
                for entry in feed.entries[:8]:
                    results.append(
                        self._coerce(
                            title=entry.get("title", ""),
                            url=entry.get("link", ""),
                            published_at=_parse_date(entry.get("published")),
                            source="Google News",
                        )
                    )
            except Exception as exc:
                logger.debug("Google News query failed (%s): %s", q, exc)
        return results


# ============================================================
# AI-specific RSS feeds (manually curated)
# ============================================================

class CuratedRSSCollector(BaseCollector):
    name = "Curated AI RSS"
    weight = 1.1

    FEEDS: list[str] = [
        # AI news blogs
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        "https://venturebeat.com/category/ai/feed/",
        "https://www.36kr.com/information/AI/feed",
        # OpenAI / Anthropic blogs
        "https://openai.com/blog/rss.xml",
        "https://www.anthropic.com/news/rss.xml",
    ]

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AI-News-Daily/1.0)"}
        for feed_url in self.FEEDS:
            try:
                r = requests.get(feed_url, headers=headers, timeout=15, allow_redirects=True)
                if r.status_code != 200:
                    continue
                feed = feedparser.parse(r.content)
                cutoff = time.time() - lookback_hours * 3600
                for entry in feed.entries:
                    pub = _parse_date(entry.get("published") or entry.get("updated"))
                    if pub:
                        try:
                            dt = datetime.fromisoformat(pub)
                            if dt.timestamp() < cutoff:
                                continue
                        except Exception:
                            pass
                    results.append(
                        self._coerce(
                            title=entry.get("title", ""),
                            url=entry.get("link", ""),
                            published_at=pub,
                            source="Curated RSS",
                        )
                    )
            except Exception as exc:
                logger.debug("Curated RSS failed (%s): %s", feed_url, exc)
        return results


# ============================================================
# Hacker News AI Show / AI-focused top stories via Algolia
# ============================================================

class HackerNewsAITrendingCollector(BaseCollector):
    name = "HN AI Trending"
    weight = 1.2

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            url = "http://hn.algolia.com/api/v1/search_by_date"
            params = {
                "query": "AI OR LLM OR GPT OR Claude OR DeepMind OR OpenAI OR Anthropic OR Mistral OR Llama",
                "tags": "story",
                "hitsPerPage": 50,
            }
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            for hit in r.json().get("hits", []):
                if not hit.get("title"):
                    continue
                results.append(
                    BaseCollector()._coerce(
                        title=hit["title"],
                        url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                        published_at=_parse_date(hit.get("created_at")),
                        source="Hacker News",
                        points=hit.get("points"),
                        comments=hit.get("num_comments"),
                    )
                )
        except Exception as exc:
            logger.error("HN AI Trending fetch failed: %s", exc)
        return results


# ============================================================
# YouTube (via public pages, no API)
# ============================================================

class YouTubeAICollector(BaseCollector):
    name = "YouTube"
    weight = 0.9

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            r = requests.get(
                "https://www.youtube.com/feed/trending",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            if r.status_code != 200:
                return results
            soup = BeautifulSoup(r.text, "lxml")
            for item in soup.select("ytd-video-renderer")[:20]:
                title_tag = item.select_one("#video-title")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                if not href.startswith("http"):
                    href = "https://www.youtube.com" + href
                # AI relevance filter
                if not any(k in title.lower() for k in ["ai", "llm", "gpt", "claude", "machine learning", "robot", "deep learning"]):
                    continue
                view_count = ""
                view_tag = item.select_one(".style-scope ytd-video-meta-block")
                if view_tag:
                    view_count = view_tag.get_text(" ", strip=True)
                results.append(
                    self._coerce(
                        title=title,
                        url=href,
                        published_at=datetime.now(timezone.utc).isoformat(),
                        source="YouTube",
                        views=view_count,
                    )
                )
        except Exception as exc:
            logger.error("YouTube trending fetch failed: %s", exc)
        return results


# ============================================================
# Top AI blogs via RSSHub (requires external RSSHub instance)
# ============================================================

class RSSHubCollector(BaseCollector):
    name = "RSSHub AI"
    weight = 1.0

    RSSHUB_BASE: str = os.getenv("RSSHUB_BASE", "https://rsshub.app").rstrip("/")

    ROUTES: list[str] = [
        # hackernews AI
        "/hackernews/beststories",
        # product hunt top products
        "/producthunt/top",
        # subreddit specific
        "/reddit/subreddit/artificial",
        "/reddit/subreddit/MachineLearning",
        "/reddit/subreddit/LocalLLaMA",
        "/reddit/subreddit/OpenAI",
        # dev community
        "/dev.to/top/week",
    ]

    def fetch(self, lookback_hours: int = 24) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cutoff = time.time() - lookback_hours * 3600
        for route in self.ROUTES:
            try:
                r = requests.get(
                    f"{self.RSSHUB_BASE}{route}",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                if r.status_code != 200:
                    continue
                feed = feedparser.parse(r.content)
                for entry in feed.entries[:15]:
                    pub = _parse_date(entry.get("published") or entry.get("updated"))
                    if pub:
                        try:
                            dt = datetime.fromisoformat(pub)
                            if dt.timestamp() < cutoff:
                                continue
                        except Exception:
                            pass
                    results.append(
                        self._coerce(
                            title=entry.get("title", ""),
                            url=entry.get("link", ""),
                            published_at=pub,
                            source="RSSHub",
                        )
                    )
            except Exception as exc:
                logger.debug("RSSHub route failed (%s): %s", route, exc)
        return results


# ============================================================
# Dispatcher
# ============================================================

# collector class list — add new ones here
COLLECTOR_CLASSES: list[type[BaseCollector]] = [
    HackerNewsCollector,
    HackerNewsAITrendingCollector,
    GitHubTrendingCollector,
    ProductHuntCollector,
    RedditCollector,
    GoogleNewsCollector,
    CuratedRSSCollector,
    YouTubeAICollector,
    RSSHubCollector,
]


def fetch_all(lookback_hours: int = 24) -> list[dict[str, Any]]:
    """Run all collectors and return a unified, deduplicated list."""
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for Cls in COLLECTOR_CLASSES:
        collector = Cls()
        logger.info("Fetching from %s ...", collector.name)
        try:
            batch = collector.fetch(lookback_hours=lookback_hours)
        except Exception as exc:
            logger.error("Collector %s raised: %s", collector.name, exc)
            continue
        new_count = 0
        for item in batch:
            key = _dedup_key(item["title"], item["url"])
            if key in seen_keys:
                continue
            # basic AI relevance keyword filter
            t = (item.get("title") or "").lower()
            ai_kw = "ai llm gpt claude deepmind openai anthropic mistral llama diffusion transformer robot copilot ml machine-learning artificial intelligence foundation model".split()
            if not any(k in t for k in ai_kw):
                continue
            item["_key"] = key
            item["_weight"] = collector.weight
            seen_keys.add(key)
            items.append(item)
            new_count += 1
        logger.info("  -> %s added %d items", collector.name, new_count)
    # Sort by published_at descending (newer first)
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = fetch_all(lookback_hours=24)
    print(json.dumps(data[:5], indent=2, ensure_ascii=False))
    print(f"Total AI items: {len(data)}")

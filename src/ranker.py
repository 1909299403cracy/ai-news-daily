"""Ranker: score and sort raw items into top-N lists."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from .config import settings

logger = logging.getLogger("ai-news-daily")

# Company / product names to boost (customizable)
BRAND_BOOST: dict[str, float] = {
    "OpenAI": 1.5,
    "Anthropic": 1.5,
    "Google DeepMind": 1.5,
    "DeepMind": 1.5,
    "Meta AI": 1.4,
    "Meta Llama": 1.4,
    "Microsoft AI": 1.4,
    "NVIDIA AI": 1.4,
    "NVIDIA": 1.4,
    "xAI": 1.4,
    "Grok": 1.4,
    "Mistral AI": 1.3,
    "Mistral": 1.3,
    "Perplexity": 1.3,
    "Hugging Face": 1.3,
    "Stability AI": 1.3,
    "Stable Diffusion": 1.3,
    "LLaMA": 1.3,
    "GPT": 1.3,
    "Claude": 1.3,
    "Gemini": 1.3,
    "Copilot": 1.3,
    "Apple AI": 1.3,
    "Alibaba AI": 1.2,
    "Baidu AI": 1.2,
    "ByteDance AI": 1.2,
    "月之暗面": 1.2,
    "kimi": 1.2,
    "智谱AI": 1.2,
    "阶跃星辰": 1.2,
    "通义千问": 1.2,
}

MARKETING_RE = re.compile(
    r"震惊|震惊！|必看|必备|神器|彻底改变|颠覆|绝了|怎么说呢|还好"
)

# Sources with higher weight
SOURCE_BOOST: dict[str, float] = {
    "OpenAI Blog": 1.6,
    "Anthropic": 1.6,
    "Google DeepMind": 1.6,
    "Hacker News": 1.4,
    "GitHub Trending": 1.3,
    "Curated RSS": 1.2,
    "Product Hunt": 1.2,
    "TechCrunch": 1.1,
    "The Verge": 1.1,
    "VentureBeat": 1.1,
    "36kr": 1.0,
}


def _hours_since(iso: str | None) -> float:
    if not iso:
        return 999.0
    try:
        dt = datetime.fromisoformat(iso)
        now = datetime.now(timezone.utc)
        delta = now - dt.astimezone(timezone.utc) if dt.tzinfo else now - dt.replace(tzinfo=timezone.utc)
        return max(delta.total_seconds() / 3600, 0.0)
    except Exception:
        return 999.0


def _engagement_score(item: dict[str, Any]) -> float:
    """Combine points / comments / stars into a single score."""
    extra = item.get("extra") or {}
    pts = 0.0
    for key in ("points", "score", "stars"):
        v = extra.get(key)
        if v is not None:
            try:
                pts += float(v)
            except (TypeError, ValueError):
                pass
    for key in ("comments", "num_comments", "views"):
        v = extra.get(key)
        if v is not None:
            try:
                # normalize: 100 comments ≈ 100 points
                pts += float(v) * 0.5
            except (TypeError, ValueError):
                pass
    return pts  # log-scale in final


def _marketing_penalty(item: dict[str, Any]) -> float:
    title = item.get("title") or ""
    m = MARKETING_RE.search(title)
    return -0.4 if m else 0.0


def _brand_boost(item: dict[str, Any]) -> float:
    title = (item.get("title") or "")
    domain = (item.get("domain") or "")
    source = (item.get("source") or "")
    boost = BRAND_BOOST.get(source, 0.0)
    for brand, mult in BRAND_BOOST.items():
        if brand.lower() in title.lower():
            boost = max(boost, mult)
            break
    return boost


def source_boost(item: dict[str, Any]) -> float:
    return SOURCE_BOOST.get(item.get("source", ""), 1.0)


def score_item(item: dict[str, Any]) -> float:
    raw = (
        item.get("_weight") or 1.0
    ) * source_boost(item)
    hours = _hours_since(item.get("published_at"))
    if hours >= 48:
        time_score = 0.2
    elif hours >= 12:
        time_score = 0.5
    else:
        time_score = 1.0
    engagement = min(_engagement_score(item) / 100.0, 5.0)
    final = raw * time_score * (1.0 + engagement) * (1.0 + _brand_boost(item) + _marketing_penalty(item))
    return max(final, 0.01)


def rank(items: list[dict[str, Any]], top_n: int | None = None) -> list[dict[str, Any]]:
    top_n = top_n or settings.MAX_ITEMS_PER_SECTION
    ranked = sorted(items, key=score_item, reverse=True)
    # pick section
    return ranked[:top_n]


def split_by_type(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Rough split into 'news' vs 'product/model' vs 'creator'.
    Heuristic: google_news / rss sources = news; github/product_hunt = products; reddit/hn/yt = creators.
    """
    news: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    creators: list[dict[str, Any]] = []
    for it in items:
        src = it.get("source", "")
        if src in ("Google News", "Curated RSS", "CuratedAI RSS"):
            news.append(it)
        elif src in ("GitHub Trending",):
            products.append(it)
        elif src in ("Hacker News", "Reddit", "YouTube", "RSSHub", "HN AI Trending"):
            creators.append(it)
        elif src in ("Product Hunt",):
            products.append(it)
        else:
            news.append(it)
    return {"news": news, "products": products, "creators": creators}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from .sources import fetch_all
    items = fetch_all(24)
    print(f"Loaded {len(items)} items")
    grouped = split_by_type(items)
    print("Top news:", [i["title"] for i in rank(grouped["news"], 5)])
    print("Top products:", [i["title"] for i in rank(grouped["products"], 5)])
    print("Top creators:", [i["title"] for i in rank(grouped["creators"], 5)])

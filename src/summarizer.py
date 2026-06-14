"""LLM summarizer / daily-digest composer.

Uses OpenRouter API with configurable model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from .config import now_beijing, now_utc, settings

logger = logging.getLogger("ai-news-daily")

SYSTEM_PROMPT = """You are an expert AI industry analyst and daily-news editor. Generate a high-quality Chinese daily digest for AI professionals.

Hard rules:
- Do NOT invent news that does not exist in the provided items.
- If a metric (likes/comments/stars) is listed as "互动数据不可用" in the input, keep it as that — do not fabricate.
- Mark low-signal marketing fluff with [软文标记].
- Output valid Markdown-only. No code fences around the whole report.
- Use Chinese for all user-facing text, keep proper nouns in original form.
- Items of the same major story must be merged/highlighted as one to avoid redundant titles.
"""


def _model_client():
    if not settings.OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not set; LLM summarization will be skipped.")
        return None
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=settings.OPENROUTER_API_KEY)


def _fmt_item(it: dict[str, Any], max_chars: int = 180) -> str:
    title = it.get("title", "")
    url = it.get("url", "")
    src = it.get("source", "")
    pub = it.get("published_at", "")
    ex = it.get("extra") or {}
    extra_parts = []
    for k in ("points", "score", "comments", "stars", "views"):
        if k in ex and ex[k] is not None:
            extra_parts.append(f"{k}={ex[k]}")
    extra_str = " ".join(extra_parts)
    # truncate long text
    t = title if len(title) <= max_chars else title[: max_chars - 3] + "..."
    return f"- [{src}] {t} | {url} | pub={pub} | {extra_str}"


def _items_to_prompt(items: dict[str, list[dict[str, Any]]]) -> str:
    now_bj = now_beijing().strftime("%Y-%m-%d %H:%M")
    now_utc_str = now_utc().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# 当前时间: 北京时间 {now_bj} (UTC {now_utc_str})\n"]
    lines.append("## 原始条目（请严格遵守，不得虚构）\n")
    for section, section_items in items.items():
        lines.append(f"### {section}\n")
        for i in section_items:
            lines.append(_fmt_item(i))
        lines.append("")
    return "\n".join(lines)


def _cache_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _cache_path() -> Path:
    p = Path(settings.DATA_DIR) / "ai-news-daily" / "llm_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_cache(h: str) -> str | None:
    f = _cache_path() / f"{h}.md"
    if f.exists():
        try:
            return f.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def _write_cache(h: str, content: str) -> None:
    try:
        f = _cache_path() / f"{h}.md"
        f.write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.debug("LLM cache write failed: %s", exc)


def build_report(
    items: dict[str, list[dict[str, Any]]],
    max_top10: int = 10,
) -> str:
    client = _model_client()
    if client is None:
        logger.warning("No OpenRouter API key configured; returning raw markdown.")
        return _raw_report(items, max_top10=max_top10)

    prompt = _items_to_prompt(items)

    cache_h = _cache_hash(prompt)
    cached = _read_cache(cache_h)
    if cached:
        logger.info("Using cached LLM output.")
        return cached

    user_message = f"""请根据下面的原始条目生成中文日报。格式要求：

【每日 AI 热点日报】
日期：{now_beijing().strftime('%Y-%m-%d')}
数据时间范围：过去 24 小时

一、今日 AI 行业最重要的 5 条消息（综合排序，必须是过去24小时内最重要的5条，每条独立列出）
- 标题
- 来源
- 发布时间
- 一句话总结
- 为什么重要
- 原文链接

二、今日 Top 10 AI 产品 / 模型 / 公司动态
（从 items.products 中选出，综合热度/影响力/创新性排序）
- 排名
- 名称
- 动态摘要
- 热度依据
- 适合关注的人群
- 链接

三、今日 AI 博主高热度内容 Top 10
（从 items.creators 中选出，综合互动量和影响力排序）
- 排名
- 博主 / 作者
- 平台
- 内容标题
- 点赞 / 评论 / 收藏 / 转发 / Star 等数据（如采集不到则写“互动数据不可用”）
- 一句话价值判断
- 链接

四、值得重点关注的 3 个趋势
- 趋势名称
- 趋势解释
- 对产品经理 / 外贸制造业 / 铝制品建材行业可能有什么启发

五、今日可执行建议（3 条）
- 具体行动建议

从以下条目生成：
{prompt}
"""

    try:
        logger.info("Calling OpenRouter (%s) ...", settings.OPENROUTER_MODEL)
        completion = client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_tokens=4000,
        )
        report = completion.choices[0].message.content or ""
        report = report.strip()
        if report:
            _write_cache(cache_h, report)
            return report
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
    return _raw_report(items, max_top10=max_top10)


def _raw_report(items: dict[str, list[dict[str, Any]]], max_top10: int = 10) -> str:
    """LLM fallback: simple template-based raw report."""
    lines: list[str] = []
    now_bj = now_beijing().strftime("%Y-%m-%d %H:%M")
    lines.append(f"【每日 AI 热点日报】")
    lines.append(f"日期：{now_bj}")
    lines.append(f"数据时间范围：过去 24 小时\n")

    def section(title: str, section_items: list[dict[str, Any]], n: int):
        lines.append(f"## {title}\n")
        for i, it in enumerate(section_items[:n], 1):
            ex = it.get("extra") or {}
            extra = " | ".join(f"{k}={v}" for k, v in ex.items() if v is not None) or "无"
            lines.append(f"{i}. **{it.get('title','')}**  ")
            lines.append(f"   - 来源：{it.get('source','')}")
            lines.append(f"   - 链接：[{it.get('url','')}]({it.get('url','')})")
            lines.append(f"   - 数据：{extra}\n")

    section("一、今日 AI 行业最重要的 5 条消息", items.get("news", []), 5)
    section("二、今日 Top 10 AI 产品 / 模型 / 公司动态", items.get("products", []), max_top10)
    section("三、今日 AI 博主高热度内容 Top 10", items.get("creators", []), max_top10)
    lines.append("## 四、值得重点关注的 3 个趋势\n")
    lines.append("> 趋势分析依赖 LLM，当前未接入 LLM，请稍后查看完整分析。")
    lines.append("\n## 五、今日可执行建议\n")
    lines.append("> 依赖 LLM 生成，当前未接入 LLM，请配置 OPENROUTER_API_KEY。\n")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from .sources import fetch_all
    from .ranker import split_by_type, rank
    items = fetch_all(24)
    grouped = split_by_type(items)
    ranked = {k: rank(v) for k, v in grouped.items()}
    rpt = build_report(ranked, max_top10=10)
    print(rpt)

"""Notification channels - Feishu, WeCom, Telegram, Email."""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

import requests

from .config import now_beijing, settings

logger = logging.getLogger("ai-news-daily")


# ============================================================
# Feishu Custom Bot (Webhook)
# ============================================================

def push_feishu(text_md: str, title: str = "每日 AI 热点日报") -> bool:
    url = settings.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("FEISHU_WEBHOOK_URL not configured; ignored.")
        return False
    try:
        # Feishu cards support md in title/content
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [[{"tag": "markdown", "text": text_md}]],
                    }
                }
            },
        }
        r = requests.post(url, json=payload, timeout=30)
        body = r.json()
        if body.get("code") == 0 or body.get("StatusCode") == 0 or r.status_code == 200:
            logger.info("Feishu push OK.")
            return True
        # some older bots return plain text
        if r.status_code == 200 and "success" in (body or "").lower():
            logger.info("Feishu push OK (plain response).")
            return True
        logger.error("Feishu push failed: %s", body)
        return False
    except Exception as exc:
        logger.error("Feishu push error: %s", exc)
        return False


# ============================================================
# WeCom Work Bot (Webhook)
# ============================================================

def push_wecom(text_md: str, title: str = "每日 AI 热点日报") -> bool:
    url = settings.WECOM_WEBHOOK_URL
    if not url:
        logger.warning("WECOM_WEBHOOK_URL not configured; ignored.")
        return False
    try:
        # WeCom supports markdown in msgtype=markdown (limited)
        body = {
            "msgtype": "markdown",
            "markdown": {"content": f"# {title}\n\n{text_md}"},
        }
        r = requests.post(url, json=body, timeout=30)
        resp = r.json()
        if resp.get("errcode") == 0 or r.status_code == 200:
            logger.info("WeCom push OK.")
            return True
        logger.error("WeCom push failed: %s", resp)
        return False
    except Exception as exc:
        logger.error("WeCom push error: %s", exc)
        return False


# ============================================================
# Telegram Bot
# ============================================================

def push_telegram(text_md: str, title: str = "每日 AI 热点日报") -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.warning("Telegram env not configured; ignored.")
        return False
    # Telegram does not allow very long messages, chunk
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        header = f"<b>{title}</b>\n\n"
        msg = header + text_md
        # Telegram max 4096 chars, we split by ~3800
        chunks = [msg[i : i + 3800] for i in range(0, len(msg), 3800)]
        for chunk in chunks:
            body = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            r = requests.post(url, json=body, timeout=30)
            resp = r.json()
            if not resp.get("ok"):
                logger.error("Telegram push failed: %s", resp)
                return False
        logger.info("Telegram push OK.")
        return True
    except Exception as exc:
        logger.error("Telegram push error: %s", exc)
        return False


# ============================================================
# Email (SMTP)
# ============================================================

def push_email(subject: str, body_md: str) -> bool:
    to_addr = settings.EMAIL_TO
    user = settings.EMAIL_USER
    password = settings.EMAIL_PASSWORD
    if not all([to_addr, user, password]):
        logger.warning("Email env missing; ignored.")
        return False
    try:
        msg = MIMEText(body_md, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to_addr
        # parse host/port from EMAIL_USER or use default
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.login(user, password)
            s.sendmail(user, [to_addr], msg.as_string())
        logger.info("Email push OK.")
        return True
    except Exception as exc:
        logger.error("Email push error: %s", exc)
        return False


# ============================================================
# Unified push
# ============================================================

def send_report(report_md: str) -> bool:
    title = f"每日 AI 热点日报 {now_beijing().strftime('%Y-%m-%d')}"
    results = []
    ch = settings.active_push_channel()
    if ch == "feishu":
        results.append(push_feishu(report_md, title))
    elif ch == "wecom":
        results.append(push_wecom(report_md, title))
    elif ch == "telegram":
        results.append(push_telegram(report_md, title))
    elif ch == "email":
        results.append(push_email(title, report_md))
    else:
        logger.warning("No push channel configured.")
    return any(results)

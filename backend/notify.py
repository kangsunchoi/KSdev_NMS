"""
NetVision OT — Alert notifications (Slack / Telegram).

* Standard library only (urllib). No extra packages.
* Sends ONLY if the corresponding env var is set; otherwise it's a silent no-op,
  so this module is inert until you configure a channel.
* Never raises into the caller — a notification failure must not block alert
  creation. All errors are swallowed and logged.

Env:
  SLACK_WEBHOOK_URL      Slack incoming webhook URL
  TELEGRAM_BOT_TOKEN     Telegram bot token   (needs TELEGRAM_CHAT_ID too)
  TELEGRAM_CHAT_ID       Telegram chat id
  NOTIFY_MIN_SEVERITY    info | warning | critical   (default: critical)
"""

import os
import json
import asyncio
import logging
import urllib.request

logger = logging.getLogger("netvision.notify")

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
NOTIFY_MIN_SEVERITY = os.environ.get("NOTIFY_MIN_SEVERITY", "critical").strip().lower()

_SEV_RANK = {"info": 1, "warning": 2, "critical": 3}


def _enabled() -> bool:
    return bool(SLACK_WEBHOOK_URL or (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID))


def _post(url: str, payload: dict):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def _send_sync(alert: dict):
    sev = alert.get("severity", "info")
    name = alert.get("device_name", "device")
    msg = alert.get("message", "")
    text = f"[NetVision OT] {sev.upper()} — {name}: {msg}"
    if SLACK_WEBHOOK_URL:
        try:
            _post(SLACK_WEBHOOK_URL, {"text": text})
        except Exception as e:
            logger.warning("Slack notify failed: %s", e)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            _post(url, {"chat_id": TELEGRAM_CHAT_ID, "text": text})
        except Exception as e:
            logger.warning("Telegram notify failed: %s", e)


async def notify_alert(alert: dict):
    """Fire-and-forget notification for a newly created alert. Safe to await;
    runs the blocking HTTP call in a thread so it won't stall the event loop."""
    if not _enabled():
        return
    sev = alert.get("severity", "info")
    if _SEV_RANK.get(sev, 0) < _SEV_RANK.get(NOTIFY_MIN_SEVERITY, 3):
        return
    try:
        await asyncio.to_thread(_send_sync, alert)
    except Exception as e:  # never propagate
        logger.warning("notify dispatch failed: %s", e)

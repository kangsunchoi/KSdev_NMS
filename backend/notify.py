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
import time
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


# Storm guard (issue #11): at most this many notifications per rolling minute.
NOTIFY_MAX_PER_MIN = int(os.environ.get("NOTIFY_MAX_PER_MIN", "20"))
_sent_times: list = []
_suppressed = 0
_tasks: set = set()


async def _deliver(alert: dict):
    try:
        await asyncio.to_thread(_send_sync, alert)
    except Exception as e:  # never propagate
        logger.warning("notify dispatch failed: %s", e)


_window_start = 0.0  # monotonic time of the first suppression in the current window


def _allow_now() -> bool:
    global _suppressed, _window_start
    now = time.monotonic()
    while _sent_times and now - _sent_times[0] > 60:
        _sent_times.pop(0)
    if len(_sent_times) >= NOTIFY_MAX_PER_MIN:
        if _suppressed == 0:
            _window_start = now
        _suppressed += 1
        if _suppressed == 1 or _suppressed % 50 == 0:
            logger.warning("notify rate limit hit (%d/min): %d notification(s) suppressed",
                           NOTIFY_MAX_PER_MIN, _suppressed)
        return False
    _sent_times.append(now)
    return True


async def notify_alert(alert: dict):
    """Queue a notification for a newly created alert and return immediately.

    The HTTP call runs in a background task (thread), so a slow or unreachable
    Slack/Telegram never delays ingestion or the simulation loop (issue #11)."""
    if not _enabled():
        return
    sev = alert.get("severity", "info")
    if _SEV_RANK.get(sev, 0) < _SEV_RANK.get(NOTIFY_MIN_SEVERITY, 3):
        return
    if not _allow_now():
        return
    task = asyncio.create_task(_deliver(dict(alert)))
    _tasks.add(task)  # keep a reference until done (asyncio only holds weak refs)
    task.add_done_callback(_tasks.discard)


async def flush_suppressed():
    """Called periodically: once a storm window (60s) has passed, send ONE summary
    of how many notifications were suppressed, then reset (issue #25)."""
    global _suppressed
    if not _suppressed:
        return
    if not _enabled():
        _suppressed = 0  # channels were switched off: nothing to summarize later
        return
    if time.monotonic() - _window_start < 60:
        return
    count, _suppressed = _suppressed, 0
    _sent_times.append(time.monotonic())  # the summary counts toward the per-minute budget
    summary = {"id": f"suppressed-{int(time.time())}", "severity": "critical",
               "device_name": "NetVision OT",
               "message": f"{count} more alert notification(s) were suppressed in the last minute "
                          f"(limit {NOTIFY_MAX_PER_MIN}/min). Check the Alerts page."}
    task = asyncio.create_task(_deliver(summary))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

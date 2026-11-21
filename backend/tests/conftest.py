"""Test bootstrap.

The legacy tests talk to a running server over HTTP via REACT_APP_BACKEND_URL.
If that variable is NOT set, we start the backend in-process on a free local
port. By default it uses an in-memory MongoDB (mongomock), so tests run anywhere
without a database. Set TEST_MONGO_URL to run against a real MongoDB (CI does).
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_SERVER = None

if not os.environ.get("REACT_APP_BACKEND_URL"):
    os.environ["MONGO_URL"] = os.environ.get("TEST_MONGO_URL", "mongomock://local")
    os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "netvision_test")
    # Force test-safe values. A developer's backend/.env must not leak into tests
    # (load_dotenv never overrides keys that already exist, even empty ones):
    # no real Slack/Telegram sends, no ingest token, auth off, simulation on.
    for _k in ("SLACK_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "INGEST_TOKEN", "AUTH_SECRET"):
        os.environ[_k] = ""
    os.environ["SIMULATION_MODE"] = "true"
    os.environ["AUTH_ENABLED"] = "false"
    os.environ["CORS_ORIGINS"] = "*"
    _port = _free_port()
    os.environ["REACT_APP_BACKEND_URL"] = f"http://127.0.0.1:{_port}"

    sys.path.insert(0, str(BACKEND_DIR))
    import uvicorn  # noqa: E402

    import server  # noqa: E402

    _config = uvicorn.Config(server.app, host="127.0.0.1", port=_port, log_level="warning")
    _SERVER = uvicorn.Server(_config)
    threading.Thread(target=_SERVER.run, daemon=True).start()
    for _ in range(100):
        if _SERVER.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("test backend failed to start")


def pytest_sessionfinish(session, exitstatus):
    if _SERVER is not None:
        _SERVER.should_exit = True

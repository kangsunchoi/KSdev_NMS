"""
NetVision OT — Authentication / RBAC (standard library only, no extra packages).

Design goals
------------
* ZERO external dependencies (no PyJWT / bcrypt / passlib). Uses hashlib + hmac
  + secrets so the VM does not need any `pip install`.
* SAFE BY DEFAULT. Everything is gated by AUTH_ENABLED (default OFF). When OFF,
  the middleware passes every request through unchanged, so deploying this file
  does not alter existing behavior at all.
* MINIMAL FOOTPRINT in server.py: one call to register_routes() and one to
  register_middleware().

Roles (hierarchy): viewer < operator < admin
  * GET (read)            -> viewer+
  * POST/PUT/PATCH/DELETE -> operator+
  * /api/auth/users*      -> admin only

Collector endpoints (ingest/metrics/interfaces/links/discovery-register) use a
SEPARATE shared secret (INGEST_TOKEN via X-Ingest-Token header), independent of
user login. If INGEST_TOKEN is unset, those endpoints stay open (current
behavior) so Node-RED keeps working until you choose to lock it down.
"""

import os
import hmac
import json
import base64
import hashlib
import re
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("netvision.auth")

# ---------------- config (read once) ---------------- #

def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")

AUTH_ENABLED = _truthy(os.environ.get("AUTH_ENABLED", "false"))
AUDIT_ENABLED = _truthy(os.environ.get("AUDIT_ENABLED", "true"))
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "").strip()  # "" => collectors stay open

# Token signing secret. If unset, generate an ephemeral one (sessions drop on
# restart). For stable logins across restarts, set AUTH_SECRET in backend/.env.
AUTH_SECRET = os.environ.get("AUTH_SECRET", "").strip()
if AUTH_ENABLED and not AUTH_SECRET:
    AUTH_SECRET = secrets.token_hex(32)
    logger.warning("AUTH_SECRET not set — generated an ephemeral one; logins reset on restart. "
                   "Set AUTH_SECRET in backend/.env for persistent sessions.")
elif not AUTH_SECRET:
    AUTH_SECRET = "disabled"  # never used while AUTH_ENABLED is off

TOKEN_TTL_HOURS = int(os.environ.get("AUTH_TOKEN_TTL_HOURS", "12"))

ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}

# Paths that never require a user session (login, public config, health, docs).
_PUBLIC_PREFIXES = ("/api/auth/login", "/api/auth/config", "/docs", "/openapi.json", "/redoc")
_PUBLIC_EXACT = ("/api/", "/api")
# Collector (Node-RED) routes, matched EXACTLY by (method, full path regex).
# Write routes: guarded by INGEST_TOKEN only (open when INGEST_TOKEN is unset,
# for backward compatibility with existing flows).
_COLLECTOR_WRITE = [
    ("POST", r"/api/ingest"),
    ("POST", r"/api/metrics"),
    ("POST", r"/api/interfaces"),
    ("POST", r"/api/links"),
    ("POST", r"/api/discovery/register"),
    ("POST", r"/api/fdb"),
    ("POST", r"/api/assets"),
    ("POST", r"/api/arp"),
]
# Routes that are normal user routes, but which the collector also calls
# (target lists, discovery config, type correction). A valid X-Ingest-Token lets
# the collector use them even when AUTH_ENABLED=true.
_COLLECTOR_ALSO = [
    ("GET", r"/api/devices"),
    ("GET", r"/api/discovery"),
    ("PUT", r"/api/discovery"),
    ("PATCH", r"/api/devices/[^/]+"),
]
# Admin-only routes: path prefix (any method).
_ADMIN_PREFIXES = ("/api/auth/users", "/api/audit")
# Admin-only destructive / mode-changing routes (method, full path regex).
_ADMIN_ROUTES = [
    ("POST", r"/api/mock/(generate|reset)"),
    ("POST", r"/api/sim/mode"),
    ("POST", r"/api/devices/cleanup"),
    ("POST", r"/api/assets/reset"),
    ("POST", r"/api/links/reset"),
    ("DELETE", r"/api/devices/[^/]+"),  # cascades to alerts/metrics/links (issue #27)
]

# Collector write routes that already required a user login before INGEST_TOKEN
# existed for them. With AUTH_ENABLED=true and no INGEST_TOKEN they keep requiring
# login (no new anonymous write paths).
_COLLECTOR_WRITE_LOGIN_WHEN_NO_TOKEN = [("POST", r"/api/fdb"), ("POST", r"/api/assets"), ("POST", r"/api/arp")]

COLLECTOR_USER = {"username": "collector", "role": "collector"}
ANON_COLLECTOR_USER = {"username": "anonymous-collector", "role": "collector"}


def _match(routes, method: str, path: str) -> bool:
    return any(m == method and re.fullmatch(rx, path) for m, rx in routes)


def has_valid_ingest_token(request) -> bool:
    """True if INGEST_TOKEN is configured and the request carries it."""
    if not INGEST_TOKEN:
        return False
    # Compare as bytes: str compare_digest raises TypeError on non-ASCII input.
    got = request.headers.get("x-ingest-token", "").encode("utf-8", "surrogateescape")
    return hmac.compare_digest(got, INGEST_TOKEN.encode("utf-8"))


def parse_cors_origins(raw: Optional[str]) -> list:
    """CORS_ORIGINS env -> origin list (issue #8). Trims spaces and trailing '/'
    (a browser Origin never has one, so "http://host:8080/" would match nothing).
    Empty or any '*' entry means allow all."""
    items = [o.strip().rstrip("/") for o in (raw if raw is not None else "*").split(",")]
    items = [o for o in items if o]
    return ["*"] if not items or "*" in items else items


def startup_warnings():
    """Log configuration risks once at startup (issues #6, #8)."""
    if AUTH_ENABLED and parse_cors_origins(os.environ.get("CORS_ORIGINS")) == ["*"]:
        logger.warning("AUTH_ENABLED=true with CORS_ORIGINS='*': browsers accept API calls from any "
                       "web origin. Set CORS_ORIGINS to the dashboard URL(s), comma-separated "
                       "(e.g. http://192.168.108.129:8080).")
    if not INGEST_TOKEN:
        logger.warning("INGEST_TOKEN is not set: collector endpoints (/api/ingest, /api/metrics, ...) "
                       "accept data from anyone on the network. Set INGEST_TOKEN in backend/.env "
                       "and the X-Ingest-Token header in Node-RED.")
        if AUTH_ENABLED:
            logger.warning("AUTH_ENABLED=true without INGEST_TOKEN: Node-RED calls to GET /api/devices, "
                           "GET/PUT /api/discovery and PATCH /api/devices/{id} will be rejected (401).")


# ---------------- password hashing (pbkdf2, stdlib) ---------------- #

_PBKDF2_ITERS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------- token (signed, stdlib) ---------------- #

def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(username: str, role: str, version: int = 0) -> str:
    exp = (datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()
    payload = _b64u(json.dumps({"u": username, "r": role, "v": int(version), "exp": exp}).encode())
    sig = _b64u(hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        payload, sig = token.split(".")
        expected = _b64u(hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_b64u_decode(payload))
        if float(data.get("exp", 0)) < datetime.now(timezone.utc).timestamp():
            return None
        return {"username": data["u"], "role": data["r"], "v": int(data.get("v", 0))}
    except Exception:
        return None


# ---------------- live user check (issue #49) ---------------- #
# The token is signed but stateless, so on its own a role change, password reset
# or deletion would only take effect when it expires. Every authenticated request
# therefore re-reads the user (role + token_version) from the DB, through a short
# per-process cache that the user-management routes invalidate immediately.
USER_CACHE_SEC = float(os.environ.get("AUTH_USER_CACHE_SEC", "5"))
_user_cache: dict = {}  # username -> (expires_at, doc or None)


_USER_CACHE_MAX = 1000


def _new_token_version() -> int:
    return secrets.randbelow(2**31 - 1) + 1  # never 0 (= tokens/users from before #49)


def _invalidate_user(username: str) -> None:
    _user_cache.pop(username, None)


async def _live_user(db, username: str) -> Optional[dict]:
    now = datetime.now(timezone.utc).timestamp()
    hit = _user_cache.get(username)
    if hit and hit[0] > now:
        return hit[1]
    doc = await db.users.find_one({"username": username}, {"_id": 0, "role": 1, "token_version": 1})
    if len(_user_cache) >= _USER_CACHE_MAX:  # bounded: drop expired entries, else start over
        for k in [k for k, (exp, _) in _user_cache.items() if exp <= now]:
            del _user_cache[k]
        if len(_user_cache) >= _USER_CACHE_MAX:
            _user_cache.clear()
    _user_cache[username] = (now + USER_CACHE_SEC, doc)
    return doc


async def resolve_session(db, token: Optional[str]) -> Optional[dict]:
    """Token -> {username, role} using the CURRENT role, or None if the token is
    invalid/expired, the user no longer exists, or it was revoked."""
    claims = verify_token(token) if token else None
    if not claims:
        return None
    doc = await _live_user(db, claims["username"])
    if not doc or int(doc.get("token_version", 0)) != claims["v"]:
        return None
    return {"username": claims["username"], "role": doc.get("role", "viewer")}


# ---------------- request helpers ---------------- #

def _bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return None


def _required_rank(method: str) -> int:
    return ROLE_RANK["viewer"] if method in ("GET", "HEAD", "OPTIONS") else ROLE_RANK["operator"]


# ---------------- routes ---------------- #

class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    username: str
    password: str


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    username: str
    password: str
    role: str = "viewer"


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    password: Optional[str] = None
    role: Optional[str] = None


def register_routes(api_router: APIRouter, db):
    """Attach /api/auth/* endpoints. Must be called BEFORE app.include_router."""

    @api_router.get("/auth/config")
    async def auth_config():
        # Public: the frontend reads this to decide whether to show a login screen.
        return {"auth_enabled": AUTH_ENABLED}

    @api_router.post("/auth/login")
    async def login(payload: LoginPayload):
        if not AUTH_ENABLED:
            # When auth is off there is no real session; hand back a viewer-ish
            # token so a UI that still calls login won't break.
            return {"token": make_token(payload.username or "anonymous", "admin"),
                    "username": payload.username or "anonymous", "role": "admin",
                    "auth_enabled": False}
        user = await db.users.find_one({"username": payload.username}, {"_id": 0})
        if not user or not verify_password(payload.password, user.get("password_hash", "")):
            raise HTTPException(401, "Invalid username or password")
        token = make_token(user["username"], user["role"], user.get("token_version", 0))
        return {"token": token, "username": user["username"], "role": user["role"],
                "auth_enabled": True}

    @api_router.get("/auth/me")
    async def me(request: Request):
        u = getattr(request.state, "user", None)
        if not u:
            return {"username": "anonymous", "role": "admin", "auth_enabled": AUTH_ENABLED}
        return {**u, "auth_enabled": AUTH_ENABLED}

    # ----- user management (admin only; enforced by middleware) ----- #

    @api_router.get("/auth/users")
    async def list_users():
        rows = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(500)
        return rows

    @api_router.post("/auth/users")
    async def create_user(payload: UserCreate):
        if payload.role not in ROLE_RANK:
            raise HTTPException(400, f"role must be one of {list(ROLE_RANK)}")
        if await db.users.find_one({"username": payload.username}, {"_id": 0, "username": 1}):
            raise HTTPException(409, "User already exists")
        doc = {"username": payload.username, "role": payload.role,
               "password_hash": hash_password(payload.password),
               # random start: a re-created username never revives the old account's tokens
               "token_version": _new_token_version(),
               "created_at": datetime.now(timezone.utc).isoformat()}
        await db.users.insert_one(doc)
        _invalidate_user(payload.username)  # drop a cached "no such user"
        return {"username": doc["username"], "role": doc["role"]}

    @api_router.patch("/auth/users/{username}")
    async def update_user(username: str, payload: UserUpdate):
        update = {}
        if payload.role is not None:
            if payload.role not in ROLE_RANK:
                raise HTTPException(400, f"role must be one of {list(ROLE_RANK)}")
            update["role"] = payload.role
        if payload.password is not None:
            update["password_hash"] = hash_password(payload.password)
        if not update:
            raise HTTPException(400, "Nothing to update")
        ops = {"$set": update}
        if "password_hash" in update:  # a password reset logs out existing sessions
            ops["$inc"] = {"token_version": 1}
        res = await db.users.update_one({"username": username}, ops)
        _invalidate_user(username)
        if res.matched_count == 0:
            raise HTTPException(404, "User not found")
        return {"username": username, "updated": list(update.keys())}

    @api_router.delete("/auth/users/{username}")
    async def delete_user(username: str):
        remaining = await db.users.count_documents({"role": "admin"})
        target = await db.users.find_one({"username": username}, {"_id": 0, "role": 1})
        if target and target.get("role") == "admin" and remaining <= 1:
            raise HTTPException(400, "Cannot delete the last admin")
        res = await db.users.delete_one({"username": username})
        _invalidate_user(username)
        if res.deleted_count == 0:
            raise HTTPException(404, "User not found")
        return {"deleted": username}


# ---------------- middleware ---------------- #

def register_middleware(app, db, audit_module=None):
    """Register the auth + RBAC + audit HTTP middleware. Call AFTER
    app.include_router(...) and BEFORE app.add_middleware(CORS...) so that CORS
    stays the OUTERMOST layer (error responses keep their CORS headers)."""

    @app.middleware("http")
    async def _auth_audit(request: Request, call_next):
        path = request.url.path
        method = request.method

        # Always let CORS preflight through.
        if method == "OPTIONS":
            return await call_next(request)

        collector = has_valid_ingest_token(request)
        request.state.collector = collector

        # 1) Collector write routes: guarded by INGEST_TOKEN only (independent of AUTH_ENABLED).
        if _match(_COLLECTOR_WRITE, method, path) and not (
                AUTH_ENABLED and not INGEST_TOKEN and _match(_COLLECTOR_WRITE_LOGIN_WHEN_NO_TOKEN, method, path)):
            if INGEST_TOKEN and not collector:
                return JSONResponse({"detail": "Invalid or missing ingest token"}, status_code=401)
            return await _proceed(request, call_next, db, audit_module,
                                  user=COLLECTOR_USER if collector else ANON_COLLECTOR_USER)

        # 2) Collector calling one of the shared user routes with a valid token.
        if collector and _match(_COLLECTOR_ALSO, method, path):
            return await _proceed(request, call_next, db, audit_module, user=COLLECTOR_USER)

        # 3) Auth disabled -> pass everything through (existing behavior preserved).
        if not AUTH_ENABLED:
            return await _proceed(request, call_next, db, audit_module, user=None)

        # 4) Public paths (login/config/health/docs).
        if path in _PUBLIC_EXACT or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await _proceed(request, call_next, db, audit_module, user=None)

        # 5) Everything else requires a valid session token.
        claims = await resolve_session(db, _bearer(request))
        if not claims:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)

        rank = ROLE_RANK.get(claims["role"], 0)
        # admin-only paths / destructive routes
        is_admin_route = (any(path.startswith(p) for p in _ADMIN_PREFIXES)
                          or _match(_ADMIN_ROUTES, method, path))
        if is_admin_route and rank < ROLE_RANK["admin"]:
            return JSONResponse({"detail": "Admin privileges required"}, status_code=403)
        # method-based RBAC
        if rank < _required_rank(method):
            return JSONResponse({"detail": "Insufficient privileges for this action"}, status_code=403)

        request.state.user = claims
        return await _proceed(request, call_next, db, audit_module, user=claims)


async def _proceed(request, call_next, db, audit_module, user):
    response = await call_next(request)
    # Audit: record successful state-changing actions only.
    try:
        if (AUDIT_ENABLED and audit_module is not None
                and request.method in ("POST", "PUT", "PATCH", "DELETE")
                and 200 <= response.status_code < 300):
            await audit_module.record(
                db,
                username=(user or {}).get("username", "anonymous"),
                role=(user or {}).get("role", "n/a"),
                method=request.method,
                path=request.url.path,
                status=response.status_code,
            )
    except Exception as e:  # audit must never break a request
        logger.warning("audit record failed: %s", e)
    return response


async def ensure_default_admin(db):
    """Create an initial admin if auth is enabled and no users exist."""
    if not AUTH_ENABLED:
        return
    if await db.users.count_documents({}) > 0:
        return
    user = os.environ.get("ADMIN_USER", "admin").strip() or "admin"
    pw = os.environ.get("ADMIN_PASSWORD", "admin")
    await db.users.insert_one({
        "username": user, "role": "admin",
        "password_hash": hash_password(pw),
        "token_version": _new_token_version(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _invalidate_user(user)
    if pw == "admin":
        logger.warning("Created default admin '%s' with password 'admin' — CHANGE IT NOW "
                       "(set ADMIN_PASSWORD in .env before first start, or update via /api/auth/users).", user)
    else:
        logger.info("Created initial admin user '%s' from ADMIN_PASSWORD.", user)

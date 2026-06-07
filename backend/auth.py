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
# Collector ingestion paths guarded by INGEST_TOKEN (not user session).
_INGEST_PREFIXES = ("/api/ingest", "/api/metrics", "/api/interfaces",
                    "/api/links", "/api/discovery/register")
# Admin-only path prefixes.
_ADMIN_PREFIXES = ("/api/auth/users",)


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


def make_token(username: str, role: str) -> str:
    exp = (datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()
    payload = _b64u(json.dumps({"u": username, "r": role, "exp": exp}).encode())
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
        return {"username": data["u"], "role": data["r"]}
    except Exception:
        return None


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
        token = make_token(user["username"], user["role"])
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
               "created_at": datetime.now(timezone.utc).isoformat()}
        await db.users.insert_one(doc)
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
        res = await db.users.update_one({"username": username}, {"$set": update})
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

        # 1) Collector ingestion: guarded by INGEST_TOKEN only (independent of AUTH_ENABLED).
        if any(path.startswith(p) for p in _INGEST_PREFIXES):
            if INGEST_TOKEN:
                if request.headers.get("x-ingest-token", "") != INGEST_TOKEN:
                    return JSONResponse({"detail": "Invalid or missing ingest token"}, status_code=401)
            # else: open (current behavior)
            return await _proceed(request, call_next, db, audit_module, user=None)

        # 2) Auth disabled -> pass everything through (existing behavior preserved).
        if not AUTH_ENABLED:
            return await _proceed(request, call_next, db, audit_module, user=None)

        # 3) Public paths (login/config/health/docs).
        if path in _PUBLIC_EXACT or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await _proceed(request, call_next, db, audit_module, user=None)

        # 4) Everything else requires a valid session token.
        token = _bearer(request)
        claims = verify_token(token) if token else None
        if not claims:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)

        rank = ROLE_RANK.get(claims["role"], 0)
        # admin-only paths
        if any(path.startswith(p) for p in _ADMIN_PREFIXES) and rank < ROLE_RANK["admin"]:
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    if pw == "admin":
        logger.warning("Created default admin '%s' with password 'admin' — CHANGE IT NOW "
                       "(set ADMIN_PASSWORD in .env before first start, or update via /api/auth/users).", user)
    else:
        logger.info("Created initial admin user '%s' from ADMIN_PASSWORD.", user)

"""gateway_server/main.py — FastAPI Thin Server Gateway."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Request, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gateway_server import auth, command_validator, config, quota, rate_limiter, upstream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("akira.gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup validation: enforce JWT secret strength
    logger.info("[STARTUP] Validating Akira Gateway configuration...")
    config.validate_config()
    logger.info("[STARTUP] Akira Gateway initialized (ENV=%s)", config.AKIRA_ENV)
    yield
    logger.info("[SHUTDOWN] Akira Gateway shutting down.")


app = FastAPI(
    title="Akira Thin Server Gateway",
    version="2.0.0",
    lifespan=lifespan
)


# ── Pydantic Request Models ──────────────────────────────────────────────────

class ExchangeRequest(BaseModel):
    code: str
    nonce: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RevokeRequest(BaseModel):
    user_id: str | None = None


class ValidateCommandRequest(BaseModel):
    command: str


class RouteRequest(BaseModel):
    messages: list[dict]
    system: str | list | None = None
    model: str | None = None
    action: str | None = None
    parameters: str | None = None
    max_tokens: int = 1600
    temperature: float = 0.0
    output_config: dict | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_current_user_claims(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Bearer token required."
        )
    token = authorization[len("Bearer "):].strip()
    try:
        claims = auth.decode_jwt(token)
        return claims
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired JWT token: {str(e)}"
        )


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "akira-gateway", "env": config.AKIRA_ENV}


@app.post("/v1/auth/exchange")
def auth_exchange(req: ExchangeRequest, request: Request):
    """Exchange browser login one-time code and nonce for signed JWT + refresh token."""
    ip = get_client_ip(request)
    limit_ok, retry_after = rate_limiter.check_rate_limit(
        f"rl:auth:{ip}", config.RATE_LIMIT_AUTH[0], config.RATE_LIMIT_AUTH[1]
    )
    if not limit_ok:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": f"Rate limit exceeded. Try again in {retry_after}s.", "rate_limited": True},
            headers={"Retry-After": str(retry_after)}
        )

    res = auth.exchange_auth_code(req.code, req.nonce)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or mismatched authorization code/nonce."
        )

    user_id, tier, refresh_token = res
    access_token = auth.issue_jwt(user_id, tier)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "tier": tier,
        "expires_in": 1800
    }


@app.post("/v1/auth/refresh")
def auth_refresh(req: RefreshRequest):
    """Silently refresh an expiring JWT using a valid refresh token."""
    res = auth.refresh_jwt(req.refresh_token)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked refresh token. Please re-authenticate."
        )
    new_jwt, tier = res
    return {
        "access_token": new_jwt,
        "token_type": "Bearer",
        "tier": tier,
        "expires_in": 1800
    }


@app.post("/v1/auth/revoke")
def auth_revoke(req: RevokeRequest, claims: dict = Depends(get_current_user_claims)):
    """Revoke all active sessions and refresh tokens for user."""
    user_id_to_revoke = req.user_id or claims.get("sub")
    if user_id_to_revoke:
        auth.revoke_user_sessions(user_id_to_revoke)
    return {"status": "success", "revoked_user_id": user_id_to_revoke}


@app.post("/v1/validate-command")
def validate_command(req: ValidateCommandRequest):
    """Server-side validation for indirect/untrusted app-open candidates."""
    valid, message = command_validator.validate_command_string(req.command)
    return {"valid": valid, "message": message, "command": req.command}


@app.post("/v1/route")
def route_call(req: RouteRequest, request: Request, claims: dict = Depends(get_current_user_claims)):
    """Authoritative server-gated action routing and completion endpoint.

    - Free tier has NO server involvement (100% local).
    - Standard & Pro tiers are authenticated, metered, and atomically enforced.
    - If daily Claude cap is reached OR Redis is down, automatically shifts to Groq free API.
    - Zero content logging: prompts, responses, and audio are never persisted.
    """
    user_id = claims.get("sub", "unknown")
    tier = claims.get("tier", "standard")

    # Rate limit check (e.g. 60 calls/min)
    ip = get_client_ip(request)
    limit_ok, retry_after = rate_limiter.check_rate_limit(
        f"rl:route:{user_id}:{ip}", config.RATE_LIMIT_ROUTE[0], config.RATE_LIMIT_ROUTE[1]
    )
    if not limit_ok:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": f"Request rate limit exceeded. Retry in {retry_after}s.", "rate_limited": True},
            headers={"Retry-After": str(retry_after)}
        )

    # Server-side capability check
    if tier == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Free tier does not use the server gateway. Free tier runs 100% locally and uncapped."
        )

    # Atomic quota check and increment
    verdict = quota.check_and_increment_turn(user_id, tier)
    if not verdict.allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": verdict.reason, "quota_exceeded": True}
        )

    # Upstream Dispatch
    if verdict.use_fallback:
        # Fallback to Groq free API (due to Claude cap or Redis outage)
        status_code, resp_data = upstream.call_upstream_groq(
            messages=req.messages,
            system=req.system if isinstance(req.system, str) else None,
            model=config.GROQ_MODEL,
            max_tokens=req.max_tokens,
            temperature=req.temperature
        )
    else:
        # Normal Claude Head
        status_code, resp_data = upstream.call_upstream_claude(
            messages=req.messages,
            system=req.system,
            model=req.model or config.CLAUDE_MODEL,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            output_config=req.output_config
        )

    if status_code != 200:
        return JSONResponse(status_code=status_code, content=resp_data)

    # Add non-content quota metadata headers for client convenience
    return JSONResponse(
        status_code=200,
        content=resp_data,
        headers={
            "X-Akira-Tier": tier,
            "X-Akira-Fallback": str(verdict.use_fallback),
            "X-Akira-Remaining": str(verdict.remaining)
        }
    )


@app.get("/v1/quota")
def get_quota(claims: dict = Depends(get_current_user_claims)):
    """Return user's remaining turns, cap, fallback status, and reset timestamp."""
    user_id = claims.get("sub", "unknown")
    tier = claims.get("tier", "standard")
    return quota.get_user_quota_summary(user_id, tier)

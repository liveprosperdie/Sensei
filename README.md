# Akira Desktop AI Assistant

Akira is an intelligent desktop AI assistant with voice orchestration, screen understanding, native application control, and layered safety gating.

---

## 1. System Architecture & Thin Gateway

Akira separates client-side execution from cloud inference and subscription gating through a minimal **Thin Server Gateway** (`gateway_server/`).

```
                                  ┌───────────────────────────────┐
                                  │      Akira Gateway Server     │
                                  │       (FastAPI + Redis)       │
                                  │                               │
                                  │  • /v1/auth/exchange          │
                                  │  • /v1/auth/refresh           │
                                  │  • /v1/auth/revoke            │
                                  │  • /v1/validate-command       │
                                  │  • /v1/route                  │
                                  │  • /v1/quota                  │
                                  └───────┬───────────────┬───────┘
                                          │               │
                            Master Claude │               │ Master Groq
                                  Key     │               │     Key
                                          ▼               ▼
                                    ┌───────────┐   ┌───────────┐
                                    │ Anthropic │   │   Groq    │
                                    │  Claude   │   │  Llama/   │
                                    │  Sonnet   │   │   Qwen    │
                                    └───────────┘   └───────────┘
                                          ▲
                                          │
                         Gated Route Call │ (Standard / Pro Tiers)
                                          │
 ┌────────────────────────────────────────┴──────────────────────────────────┐
 │                                                                           │
 │                         Akira Client (Desktop App)                        │
 │                                                                           │
 │  • Free Tier: 100% Local Groq Head (No Server, Uncapped, Direct Call)     │
 │  • Standard & Pro Tiers: Authenticated via JWT, Gated & Fallback          │
 │  • Action Router & Guard: Serial & Parallel Safety Review                 │
 │  • Hardware Gating: VRAM/RAM probing for local models                     │
 │  • Untrusted Context Defense: <untrusted_external_context> XML wrappers   │
 │                                                                           │
 └───────────────────────────────────────────────────────────────────────────┘
```

### Authentication Flow
1. The desktop client initiates authentication by opening the website login page in the user's default browser with a cryptographic `nonce` and a local redirect URI (`http://127.0.0.1:8765/callback`).
2. Upon user authentication, the browser redirects to the local loopback server with a single-use authorization code.
3. The client sends `POST /v1/auth/exchange` to the gateway, exchanging the code and nonce for:
   - A signed HS256 JWT access token (valid for 30 minutes).
   - An opaque refresh token.
   - The authoritative subscription tier (`standard` or `pro`).
4. Tokens are stored securely in the local application data directory (`%LOCALAPPDATA%\Akira\session.json`).
5. As the access token nears expiry, the client automatically refreshes it via `POST /v1/auth/refresh`. Sessions can be revoked anytime via `POST /v1/auth/revoke`.

---

## 2. Authoritative Tier Behaviors & Quotas

### Free Tier — 100% Local & Uncapped
> [!NOTE]
> Free tier is intentionally excluded from the gateway — no caps, no server round-trip, no auth required.
- Free tier runs **100% locally** using the configured free head model (Groq API).
- Free tier does not call the gateway server, does not check `/v1/route`, and has no server-enforced daily cap.
- The gateway server explicitly rejects any token claiming Free tier with `HTTP 403 Forbidden`.

### Standard & Pro Tiers — Server-Gated with Groq Fallback
- **Standard Tier**: 30 turns/day on Claude.
- **Pro Tier**: 53 turns/day on Claude (priority model routing).
- **Automatic Fallback to Groq**: When a Standard or Pro user exhausts their daily Claude cap, the gateway server **does not hard-stop them**. Instead, `/v1/route` automatically and seamlessly shifts that user's head model to Groq free API for the remainder of the day.
- **Fallback Ceiling**: Fallback turns are tracked atomically with a separate ceiling of 250 turns/day.
- **Daily Reset**: All quotas reset authoritatively at `00:00 UTC`.
- **429 Response**: When both Claude and Groq fallback quotas are exhausted, the server returns `HTTP 429 Too Many Requests`:
  `"Daily limit reached on both Claude and fallback models. Resets at 00:00 UTC."`

---

## 3. Data Privacy & Zero-Content Logging Guarantee

### What the Gateway Stores
1. **Usage Counters**: Integer counters per user per day in Redis (`akira:user:<id>:quota_claude:<YYYY-MM-DD>` and `akira:user:<id>:quota_fallback_groq:<YYYY-MM-DD>`).
2. **Session / Subscription State**: User ID, subscription tier, and active refresh token hashes.

### What the Gateway NEVER Stores
- **NO Prompts or Completions**: Request messages and LLM completions pass ephemerally in-memory through the thin proxy and are streamed directly back to the client.
- **NO Audio or Transcripts**: Audio processing and wake-word detection are strictly local. The gateway never receives or stores voice audio.
- **NO Clipboard or Personal Data**: Clipboard contents and scraped desktop titles remain strictly local.

---

## 4. No Bring-Your-Own-Key (BYOK) Mode

Akira intentionally does **NOT** support a BYOK model. 
- Third-party API keys for paid services (Claude, hosted servants) are held exclusively server-side.
- The client desktop application never requests, accepts, or stores user-provided Claude API keys.
- **Developer Direct Keys Mode**: For local debugging and development without a running gateway, developers can set `AKIRA_DEV_DIRECT_KEYS=true` in `.env`. When active, Akira prints a loud, unmissable startup warning banner and falls back to raw local `.env` keys. This mode must never be enabled in release builds.

---

## 5. Security & Prompt Injection Defenses

### Indirect Command Validation (`POST /v1/validate-command`)
- **Direct Voice Commands**: When the user speaks an application open command (e.g. "Open Spotify"), Akira executes it immediately with zero network overhead.
- **Indirect Inputs**: When application names or commands originate from untrusted or indirect channels (e.g. clipboard text, browser window titles, URLs, external notes), Akira validates the command string via `POST /v1/validate-command`.
- **Rejected Inputs**:
  - Dangerous shell metacharacters: `[&|;<>^%!"`\r\n]`.
  - Directory traversals (`..`).
  - Command strings exceeding `MAX_PATH` (260 characters).

### Untrusted External Context Tagging
- All indirect desktop context (browser tab titles, window headers, URLs, notes, clipboard data) is encapsulated in `<untrusted_external_context>` XML tags before being passed into model prompts.
- Akira's system prompt strictly instructs the model to treat content within these tags as unverified third-party data and reject prompt injection instructions.

---

## 6. High-Availability & Outage Resilience

### Redis Outage Graceful Degradation (Part E.3)
- If the Redis cache is unreachable or goes down in any environment, the gateway **does not fail or return 503**.
- Standard and Pro requests degrade gracefully to Groq free fallback and the incident is logged once at `ERROR` level.
- Fallback turns are tracked in-memory during the outage.
- When Redis connectivity is restored, the gateway automatically logs at `INFO` level and resumes normal Claude quota gating.

---

## 7. Threat Model & Deferred Security Tradeoffs

1. **Client-Side Code Modification**:
   - *Risk*: Because Akira is currently distributed as Python scripts, an advanced local user could modify `guard.py` or client-side checks to bypass local gates.
   - *Mitigation & Roadmap*: All cloud inference and daily limits are strictly enforced server-side. Future releases will compile the desktop client using Nuitka/Cython, enforce code signing, and validate sensitive actions server-side.
2. **Secret Key Rotation Tradeoffs**:
   - *Risk*: Rotating `AKIRA_JWT_SECRET` immediately invalidates all active access tokens.
   - *Resolution*: Clients detect `HTTP 401` on token expiry and automatically call `/v1/auth/refresh` using their refresh token. For zero-downtime key rotation, the gateway can support dual-key verification (accepting the prior key during a 30-minute grace window).

---

## 8. Verification & Acceptance Testing

Run the full verification and acceptance test suites:

```powershell
# 1. Acceptance Gates
python verify_tiers.py           # 90 checks: Tier availability, inertia, ledger, probation
python verify_akira_head.py      # 35 checks: Schema translation, Groq head, quota duck-typing
python verify_guard_wiring.py    # 30 checks: Guard reachability and closure recording
python verify_guard_coverage.py  # 6 checks: 89 dispatchable actions coverage
python verify_hardware_gate.py   # 49 checks: VRAM/RAM probing and fail-closed logic
python verify_router.py          # Concurrency, parallel vs serial routing

# 2. Gateway & Quota Unit Tests
python -m unittest discover -s tests -p "test_*.py"
```

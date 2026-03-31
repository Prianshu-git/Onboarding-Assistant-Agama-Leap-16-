"""
Async HTTP client for the Agama installer REST API.

Mirrors the Bugzilla class in mcp-bugzilla/mcp_utils.py:
  - one class, one httpx.AsyncClient, same log-tag convention
  - [AGAMA-REQ] for outbound calls, [AGAMA-RES] for responses

Agama API base: http://<host>/api
Auth:  POST /api/auth { "password": "..." } → { "token": "..." }
       token sent as: Authorization: Bearer <token>
"""

import logging
import os
from typing import Any

import httpx
from httpx_retries import RetryTransport


# ── Logging (same ColorFormatter pattern as mcp-bugzilla) ─────────────────────
class ColorFormatter(logging.Formatter):
    CYAN  = "\x1b[36;20m"
    GREEN = "\x1b[32;20m"
    RED   = "\x1b[31;20m"
    RESET = "\x1b[0m"
    FMT   = "[%(levelname)s]: %(message)s"

    def format(self, record):
        fmt = self.FMT
        if isinstance(record.msg, str):
            if "[LLM-REQ]" in record.msg or "[LLM-RES]" in record.msg:
                fmt = self.CYAN + self.FMT + self.RESET
            elif "[AGAMA-REQ]" in record.msg or "[AGAMA-RES]" in record.msg:
                fmt = self.GREEN + self.FMT + self.RESET
        if record.levelno >= logging.ERROR:
            fmt = self.RED + self.FMT + self.RESET
        return logging.Formatter(fmt).format(record)


_handler = logging.StreamHandler()
_handler.setFormatter(ColorFormatter())

mcp_log = logging.getLogger("agama-mcp")
mcp_log.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
mcp_log.addHandler(_handler)
mcp_log.propagate = False


# ── AgamaClient ───────────────────────────────────────────────────────────────
class AgamaClient:
    """
    Async client for the Agama installer REST API.

    Usage:
        client = AgamaClient(base_url="http://localhost/api", token="<jwt>")
        status = await client.get_status()
        await client.close()

    The token is obtained once (at server startup or via agama_auth tool)
    and reused for the lifetime of the server process.
    """

    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_v2   = f"{self.base_url}/v2"

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=30.0,
            verify=False,                  # live ISO uses self-signed cert
            transport=RetryTransport(),
        )
        self._token = token

    # Expose underlying client so tools can swap the auth header when the
    # token is updated at runtime (agama_auth tool flow).
    def set_token(self, token: str) -> None:
        self._token = token
        self._client.headers["Authorization"] = f"Bearer {token}"

    async def close(self) -> None:
        await self._client.aclose()

    # ── Auth ──────────────────────────────────────────────────────────────────
    async def authenticate(self, password: str) -> str:
        """POST /api/auth → returns JWT token string."""
        url = f"{self.base_url}/auth"
        mcp_log.info(f"[AGAMA-REQ] POST {url}")
        try:
            r = await self._client.post(url, json={"password": password})
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            mcp_log.error(f"[AGAMA-RES] Auth failed {e.response.status_code}: {e.response.text}")
            raise
        token = r.json().get("token", "")
        self.set_token(token)
        mcp_log.info("[AGAMA-RES] Authenticated OK")
        return token

    # ── GET helpers ───────────────────────────────────────────────────────────
    async def _get(self, path: str) -> Any:
        url = f"{self.api_v2}{path}"
        mcp_log.info(f"[AGAMA-REQ] GET {url}")
        try:
            r = await self._client.get(url)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            mcp_log.error(f"[AGAMA-RES] {e.response.status_code} {e.response.text[:200]}")
            raise
        except httpx.RequestError as e:
            mcp_log.error(f"[AGAMA-RES] Network error: {e}")
            raise
        data = r.json()
        mcp_log.info(f"[AGAMA-RES] OK ({len(str(data))} chars)")
        return data

    async def _post(self, path: str, body: Any) -> Any:
        url = f"{self.api_v2}{path}"
        mcp_log.info(f"[AGAMA-REQ] POST {url} body={str(body)[:80]}")
        try:
            r = await self._client.post(url, json=body)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            mcp_log.error(f"[AGAMA-RES] {e.response.status_code} {e.response.text[:200]}")
            raise
        except httpx.RequestError as e:
            mcp_log.error(f"[AGAMA-RES] Network error: {e}")
            raise
        mcp_log.info("[AGAMA-RES] POST OK")
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    async def _put(self, path: str, body: Any) -> Any:
        url = f"{self.api_v2}{path}"
        mcp_log.info(f"[AGAMA-REQ] PUT {url}")
        try:
            r = await self._client.put(url, json=body)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            mcp_log.error(f"[AGAMA-RES] {e.response.status_code} {e.response.text[:200]}")
            raise
        mcp_log.info("[AGAMA-RES] PUT OK")
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    async def _patch(self, path: str, body: Any) -> Any:
        url = f"{self.api_v2}{path}"
        mcp_log.info(f"[AGAMA-REQ] PATCH {url}")
        try:
            r = await self._client.patch(url, json=body)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            mcp_log.error(f"[AGAMA-RES] {e.response.status_code} {e.response.text[:200]}")
            raise
        mcp_log.info("[AGAMA-RES] PATCH OK")
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code}

    # ── Domain methods (one per Agama endpoint) ───────────────────────────────

    async def get_status(self) -> dict[str, Any]:
        """GET /v2/status — installation stage + active progresses."""
        return await self._get("/status")

    async def get_system(self) -> dict[str, Any]:
        """GET /v2/system — full system snapshot (storage, network, locale…)."""
        return await self._get("/system")

    async def get_config(self) -> dict[str, Any]:
        """GET /v2/config — user-set configuration only."""
        return await self._get("/config")

    async def get_extended_config(self) -> dict[str, Any]:
        """GET /v2/extended_config — merged config (user + product defaults)."""
        return await self._get("/extended_config")

    async def get_proposal(self) -> dict[str, Any]:
        """GET /v2/proposal — concrete disk/package plan."""
        return await self._get("/proposal")

    async def get_issues(self) -> list[dict[str, Any]]:
        """GET /v2/issues — validation blockers."""
        result = await self._get("/issues")
        return result if isinstance(result, list) else []

    async def get_questions(self) -> list[dict[str, Any]]:
        """GET /v2/questions — pending installer prompts."""
        result = await self._get("/questions")
        return result if isinstance(result, list) else []

    async def run_action(self, action: Any) -> Any:
        """POST /v2/action — trigger install, probe, finish, etc."""
        return await self._post("/action", action)

    async def put_config(self, config: dict[str, Any]) -> Any:
        """PUT /v2/config — replace entire config."""
        return await self._put("/config", config)

    async def patch_config(self, update: dict[str, Any]) -> Any:
        """PATCH /v2/config — merge partial config update."""
        return await self._patch("/config", {"update": update})

    async def get_license(self, license_id: str, lang: str = "en") -> dict[str, Any]:
        """GET /v2/licenses/:id — software license text."""
        url = f"{self.api_v2}/licenses/{license_id}?lang={lang}"
        mcp_log.info(f"[AGAMA-REQ] GET {url}")
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

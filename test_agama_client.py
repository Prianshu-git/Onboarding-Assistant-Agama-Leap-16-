"""
Tests for AgamaClient — mirrors mcp-bugzilla's test_mcp_utils.py pattern.
Uses respx to mock HTTP responses without a live Agama instance.

Run with: uv run pytest
"""

import pytest
import respx
import httpx

from mcp_agama.agama_client import AgamaClient


BASE_URL = "http://localhost/api"


@pytest.fixture
def client():
    return AgamaClient(base_url=BASE_URL, token="test-jwt-token")


# ── Auth ──────────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_authenticate_returns_token(client):
    respx.post(f"{BASE_URL}/auth").mock(
        return_value=httpx.Response(200, json={"token": "new-jwt-token"})
    )
    token = await client.authenticate("secret")
    assert token == "new-jwt-token"
    assert client._token == "new-jwt-token"


@respx.mock
@pytest.mark.asyncio
async def test_authenticate_raises_on_failure(client):
    respx.post(f"{BASE_URL}/auth").mock(
        return_value=httpx.Response(401, json={"error": "Invalid password"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.authenticate("wrong")


# ── Status ────────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_get_status(client):
    respx.get(f"{BASE_URL}/v2/status").mock(
        return_value=httpx.Response(200, json={
            "stage": "configuring",
            "progresses": []
        })
    )
    data = await client.get_status()
    assert data["stage"] == "configuring"
    assert "progresses" in data


# ── System ────────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_get_system(client):
    mock_system = {
        "storage": {"devices": [{"name": "sda", "size": 536870912000}]},
        "network": {"connections": []},
        "l10n": {"locales": ["en_US.UTF-8"], "timezones": ["UTC"]},
    }
    respx.get(f"{BASE_URL}/v2/system").mock(
        return_value=httpx.Response(200, json=mock_system)
    )
    data = await client.get_system()
    assert "storage" in data
    assert data["storage"]["devices"][0]["name"] == "sda"


# ── Issues ────────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_get_issues_empty(client):
    respx.get(f"{BASE_URL}/v2/issues").mock(
        return_value=httpx.Response(200, json=[])
    )
    issues = await client.get_issues()
    assert issues == []


@respx.mock
@pytest.mark.asyncio
async def test_get_issues_with_blocker(client):
    mock_issues = [
        {
            "scope": "storage",
            "issue": {
                "description": "No target device selected",
                "severity": "error"
            }
        }
    ]
    respx.get(f"{BASE_URL}/v2/issues").mock(
        return_value=httpx.Response(200, json=mock_issues)
    )
    issues = await client.get_issues()
    assert len(issues) == 1
    assert issues[0]["scope"] == "storage"


# ── Config PATCH ──────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_patch_config(client):
    respx.patch(f"{BASE_URL}/v2/config").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await client.patch_config({"l10n": {"language": "de_DE"}})
    # Verify the request body wrapped the update correctly
    request = respx.calls[0].request
    import json
    body = json.loads(request.content)
    assert "update" in body
    assert body["update"]["l10n"]["language"] == "de_DE"


# ── Action ────────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_run_action_probe_storage(client):
    respx.post(f"{BASE_URL}/v2/action").mock(
        return_value=httpx.Response(200, json={})
    )
    await client.run_action("probeStorage")
    request = respx.calls[0].request
    import json
    assert json.loads(request.content) == "probeStorage"


@respx.mock
@pytest.mark.asyncio
async def test_run_action_install_blocked(client):
    """Agama returns 422 when install is triggered with pending issues."""
    respx.post(f"{BASE_URL}/v2/action").mock(
        return_value=httpx.Response(422, json={"error": "Pending issues"})
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.run_action("install")
    assert exc_info.value.response.status_code == 422


# ── Proposal ──────────────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_get_proposal_not_ready(client):
    """404 before proposal is calculated — client should raise, tool layer handles it."""
    respx.get(f"{BASE_URL}/v2/proposal").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get_proposal()
    assert exc_info.value.response.status_code == 404

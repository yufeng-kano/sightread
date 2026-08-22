"""Provider connections and prompt presets: the control plane and one parse through a
custom OpenAI-compatible endpoint, everything stubbed (docs/testing.md § Cost safety)."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select

from sightread.db.models import UsageLog
from sightread.errors import ApiError
from sightread.jobs.queue import claim_next_job
from sightread.jobs.runner import run_job
from sightread.upstream.openrouter import normalize_base_url
from tests.conftest import CSRF_HEADERS

BASE = "https://proxy.example/openai/v1"
MODELS_URL = f"{BASE}/models"
CHAT = f"{BASE}/chat/completions"

MODELS_PAYLOAD = {
    "data": [
        {"id": "claude-code/claude-opus-5", "owned_by": "claude-code"},
        {"id": "grok/grok-4.5", "name": "Grok 4.5"},
    ]
}


def _models_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=MODELS_PAYLOAD)


async def _create_connection(client: AsyncClient, name: str = "kano") -> dict:
    response = await client.post(
        "/api/connections",
        json={"name": name, "base_url": BASE, "api_key": "sk-kano-proxy-secret"},
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- connections CRUD -----------------------------------------------------------------


@respx.mock
async def test_create_connection_validates_and_never_returns_the_key(signed_in) -> None:
    route = respx.get(MODELS_URL).mock(side_effect=_models_ok)

    created = await _create_connection(signed_in)

    assert route.called
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-kano-proxy-secret"
    assert created["name"] == "kano"
    assert created["base_url"] == BASE
    assert "sk-kano-proxy-secret" not in json.dumps(created)
    assert created["masked"].endswith("cret")

    listed = (await signed_in.get("/api/connections")).json()["connections"]
    assert [row["id"] for row in listed] == [created["id"]]
    assert "sk-kano-proxy-secret" not in json.dumps(listed)


@respx.mock
async def test_a_rejected_key_stores_nothing(signed_in) -> None:
    respx.get(MODELS_URL).mock(return_value=httpx.Response(401))

    response = await signed_in.post(
        "/api/connections",
        json={"name": "kano", "base_url": BASE, "api_key": "sk-kano-proxy-wrong"},
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request"
    assert (await signed_in.get("/api/connections")).json()["connections"] == []


@respx.mock
async def test_an_unreachable_endpoint_is_upstream_not_a_bad_key(signed_in) -> None:
    respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("boom"))

    response = await signed_in.post(
        "/api/connections",
        json={"name": "kano", "base_url": BASE, "api_key": "sk-kano-proxy-secret"},
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream"


@respx.mock
async def test_duplicate_connection_names_are_refused(signed_in) -> None:
    respx.get(MODELS_URL).mock(side_effect=_models_ok)
    await _create_connection(signed_in)

    duplicate = await signed_in.post(
        "/api/connections",
        json={"name": "kano", "base_url": BASE, "api_key": "sk-kano-proxy-secret"},
        headers=CSRF_HEADERS,
    )
    assert duplicate.status_code == 400


@respx.mock
async def test_connection_models_uses_the_stored_key(signed_in) -> None:
    respx.get(MODELS_URL).mock(side_effect=_models_ok)
    created = await _create_connection(signed_in)

    models = await signed_in.get(f"/api/connections/{created['id']}/models")

    assert models.status_code == 200
    assert models.json()["data"] == [
        {"id": "claude-code/claude-opus-5", "name": None},
        {"id": "grok/grok-4.5", "name": "Grok 4.5"},
    ]


@respx.mock
async def test_update_revalidates_a_moved_endpoint_with_the_stored_key(signed_in) -> None:
    respx.get(MODELS_URL).mock(side_effect=_models_ok)
    created = await _create_connection(signed_in)

    moved = respx.get("https://moved.example/v1/models").mock(side_effect=_models_ok)
    response = await signed_in.put(
        f"/api/connections/{created['id']}",
        json={"base_url": "https://moved.example/v1/"},
        headers=CSRF_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["base_url"] == "https://moved.example/v1"
    assert moved.calls[0].request.headers["authorization"] == "Bearer sk-kano-proxy-secret"


@respx.mock
async def test_deleting_the_default_connection_falls_back_to_openrouter(signed_in) -> None:
    respx.get(MODELS_URL).mock(side_effect=_models_ok)
    created = await _create_connection(signed_in)
    await signed_in.put(
        "/api/settings",
        json={"default_connection_id": created["id"], "default_model": "grok/grok-4.5"},
        headers=CSRF_HEADERS,
    )

    assert (
        await signed_in.delete(f"/api/connections/{created['id']}", headers=CSRF_HEADERS)
    ).status_code == 204

    settings = (await signed_in.get("/api/me")).json()["settings"]
    # The default model belonged to the deleted endpoint's catalog, so it goes too.
    assert settings["default_connection_id"] is None
    assert settings["default_model"] is None


def test_base_url_rules_outside_local() -> None:
    assert normalize_base_url(f" {BASE}/ ", "production") == BASE
    for bad in (
        "http://proxy.example/openai/v1",  # https only
        "https://localhost/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.8/v1",
        "https://[::1]/v1",
        "https://proxy.example/v1?x=1",
        "ftp://proxy.example/v1",
        "not a url",
    ):
        with pytest.raises(ApiError):
            normalize_base_url(bad, "production")
    # Local development may point at a local endpoint over plain http.
    assert normalize_base_url("http://127.0.0.1:8787/openai/v1", "local") is not None


# --- prompt presets -------------------------------------------------------------------


async def test_prompt_preset_crud_and_selection(signed_in) -> None:
    created = await signed_in.post(
        "/api/prompts",
        json={"name": "Tables only", "text": "Only tables from page {page}."},
        headers=CSRF_HEADERS,
    )
    assert created.status_code == 201
    preset = created.json()

    listed = (await signed_in.get("/api/prompts")).json()["prompts"]
    assert [row["name"] for row in listed] == ["Tables only"]

    selected = await signed_in.put(
        "/api/settings", json={"prompt_preset_id": preset["id"]}, headers=CSRF_HEADERS
    )
    assert selected.json()["prompt_preset_id"] == preset["id"]
    me = (await signed_in.get("/api/me")).json()
    assert me["settings"]["prompt_preset_id"] == preset["id"]

    renamed = await signed_in.put(
        f"/api/prompts/{preset['id']}", json={"name": "Tables"}, headers=CSRF_HEADERS
    )
    assert renamed.json()["name"] == "Tables"

    assert (
        await signed_in.delete(f"/api/prompts/{preset['id']}", headers=CSRF_HEADERS)
    ).status_code == 204
    # Deleting the selected preset falls back to the default prompt.
    assert (await signed_in.get("/api/me")).json()["settings"]["prompt_preset_id"] is None


async def test_prompt_text_is_capped(signed_in, make_client) -> None:
    client = make_client(system_prompt_max_chars=10)
    assert (await client.post("/api/auth/dev-login", headers=CSRF_HEADERS)).status_code == 200
    response = await client.post(
        "/api/prompts",
        json={"name": "Long", "text": "x" * 11},
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 400


async def test_a_foreign_preset_or_connection_cannot_be_selected(signed_in) -> None:
    for body in ({"prompt_preset_id": 999}, {"default_connection_id": 999}):
        response = await signed_in.put("/api/settings", json=body, headers=CSRF_HEADERS)
        assert response.status_code == 404


@respx.mock
async def test_a_profile_cannot_pair_with_a_custom_connection(signed_in) -> None:
    respx.get(MODELS_URL).mock(side_effect=_models_ok)
    created = await _create_connection(signed_in)

    response = await signed_in.put(
        "/api/settings",
        json={
            "default_connection_id": created["id"],
            "default_model": None,
            "default_profile": "gemini-yxyx",
        },
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 400


# --- parse through a custom connection ------------------------------------------------


@respx.mock
async def test_parse_runs_on_the_default_connection(make_client, sessionmaker, documents) -> None:
    """The whole path: settings pick a connection, the worker calls its endpoint, and the
    usage row records tokens with cost 0 (docs/parsing.md § Upstream usage)."""
    respx.get(MODELS_URL).mock(side_effect=_models_ok)
    chat = respx.post(CHAT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "# Page one"}}],
                "usage": {"prompt_tokens": 800, "completion_tokens": 90},
            },
        )
    )

    client = make_client()
    assert (await client.post("/api/auth/dev-login", headers=CSRF_HEADERS)).status_code == 200
    created = await _create_connection(client)
    await client.put(
        "/api/settings",
        json={"default_connection_id": created["id"], "default_model": "grok/grok-4.5"},
        headers=CSRF_HEADERS,
    )
    key = await client.post("/api/keys", json={"name": "test"}, headers=CSRF_HEADERS)
    client.headers["Authorization"] = f"Bearer {key.json()['key']}"

    accepted = await client.post(
        "/v1/parse",
        files={"file": ("tiny.png", documents["png"].read_bytes(), "image/png")},
    )
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]

    settings = client.app.state.settings
    async with sessionmaker() as db:
        claimed = await claim_next_job(db, settings.max_jobs_per_user)
    assert str(claimed) == job_id
    await run_job(sessionmaker, settings, claimed, asyncio.Semaphore(2))

    status = (await client.get(f"/v1/jobs/{job_id}")).json()
    assert status["status"] == "succeeded", status
    sent = json.loads(chat.calls[0].request.content)
    assert sent["model"] == "grok/grok-4.5"
    assert "usage" not in sent
    assert chat.calls[0].request.headers["authorization"] == "Bearer sk-kano-proxy-secret"

    async with sessionmaker() as db:
        usage = (
            (await db.execute(select(UsageLog).where(UsageLog.job_id == uuid.UUID(job_id))))
            .scalars()
            .all()
        )
    assert len(usage) == 1
    assert usage[0].prompt_tokens == 800
    assert usage[0].cost == 0


@respx.mock
async def test_a_profile_request_is_refused_on_a_custom_connection(
    make_client, sessionmaker, documents
) -> None:
    respx.get(MODELS_URL).mock(side_effect=_models_ok)
    client = make_client()
    assert (await client.post("/api/auth/dev-login", headers=CSRF_HEADERS)).status_code == 200
    created = await _create_connection(client)
    await client.put(
        "/api/settings",
        json={"default_connection_id": created["id"], "default_model": "grok/grok-4.5"},
        headers=CSRF_HEADERS,
    )
    key = await client.post("/api/keys", json={"name": "test"}, headers=CSRF_HEADERS)
    client.headers["Authorization"] = f"Bearer {key.json()['key']}"

    refused = await client.post(
        "/v1/parse",
        files={"file": ("tiny.png", documents["png"].read_bytes(), "image/png")},
        data={"profile": "gemini-yxyx"},
    )
    assert refused.status_code == 400
    assert "OpenRouter" in refused.json()["error"]["message"]

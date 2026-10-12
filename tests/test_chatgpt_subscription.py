"""Official OAuth and streaming boundaries with isolated credentials/no network."""

import asyncio
import json
import stat
import threading
import time
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from tradingagents.llm_clients.chatgpt_auth import AUTH_ORIGIN, SCOPES, ChatGPTAuth
from tradingagents.llm_clients.chatgpt_client import ChatGPTClient
from tradingagents.llm_clients.chatgpt_errors import ChatGPTError
from tradingagents.web.api import _analysis_request, create_app
from tradingagents.web.schemas import RunCreateRequest
from tradingagents.web.store import RunStore

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("legacy_host", [False, True])
def test_authorization_host_is_stable_uuid_urn(tmp_path, legacy_host):
    root = tmp_path / "auth"
    if legacy_host:
        root.mkdir()
        (root / "registrations.json").write_text(
            json.dumps({"host_id": "a" * 64, "active": None, "accounts": {}})
        )
    hosts = []
    for _ in range(2):
        auth = ChatGPTAuth(root)
        try:
            login = auth.begin_login()
            params = parse_qs(urlsplit(login["authorization_url"]).query)
            host = params["ext_agent_host_id"][0]
            assert host.startswith("urn:uuid:")
            assert UUID(host).version == 4
            assert host == UUID(host).urn
            assert json.loads((root / "registrations.json").read_text())["host_id"] == host
            hosts.append(host)
        finally:
            auth.close()
    assert hosts[0] == hosts[1]


def test_registered_host_is_never_silently_replaced(tmp_path):
    root = tmp_path / "auth"
    root.mkdir()
    state = {"host_id": "a" * 64, "active": None, "accounts": {"saved": {}}}
    path = root / "registrations.json"
    path.write_text(json.dumps(state))
    auth = ChatGPTAuth(root)
    with pytest.raises(ChatGPTError):
        auth.begin_login()
    assert json.loads(path.read_text()) == state


@pytest.fixture
def oauth(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test", use="sig")
    calls, options = [], {}
    params = {}

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": AUTH_ORIGIN,
                    "jwks_uri": AUTH_ORIGIN + "/jwks",
                    "revocation_endpoint": AUTH_ORIGIN + "/revoke",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        if path == "/revoke":
            return httpx.Response(options.get("revoke_status", 200))
        if path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "models": options.get(
                        "models",
                        [
                            {
                                "slug": "future-model-z",
                                "display_name": "Future Z",
                                "visibility": "list",
                            },
                            {"slug": "internal", "display_name": "Hidden", "visibility": "hide"},
                            {
                                "slug": "future-mini",
                                "display_name": "Future Mini",
                                "visibility": "list",
                            },
                        ],
                    )
                },
            )
        assert path.endswith("/oauth/token")
        data = parse_qs(request.content.decode())
        if data["grant_type"] == ["refresh_token"]:
            if options.get("refresh_entered"):
                options["refresh_entered"].set()
                assert options["refresh_release"].wait(2)
            if options.get("refresh_error"):
                return httpx.Response(
                    400, json={"error": {"code": "invalid_grant", "message": "SECRET"}}
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "access-rotated",
                    "refresh_token": "refresh-rotated",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        assert data["client_id"] == ["issued-client"]
        assert len(data["code_verifier"][0]) >= 43
        now = int(time.time())
        claims = {
            "sub": "subject",
            "iss": AUTH_ORIGIN,
            "aud": "issued-client",
            "iat": now,
            "exp": now + 3600,
            "nonce": params["nonce"][0],
            "email": "user@example.test",
        }
        claims.update(options.get("claims", {}))
        return httpx.Response(
            200,
            json={
                "access_token": "access-private",
                "refresh_token": "refresh-private",
                "id_token": jwt.encode(
                    claims,
                    options.get("signing_key", key),
                    algorithm="RS256",
                    headers={"kid": "test"},
                ),
                "token_type": "Bearer",
                "scope": options.get("scope", SCOPES),
                "expires_in": 3600,
            },
        )

    auth = ChatGPTAuth(tmp_path / "auth", transport=httpx.MockTransport(handler))

    def begin(ref=None):
        login = auth.begin_login(ref)
        params.clear()
        params.update(parse_qs(urlsplit(login["authorization_url"]).query))
        query = {"state": params["state"], "client_id": ["issued-client"], "code": ["private-code"]}
        return login["attempt_id"], query

    def connect():
        attempt, query = begin()
        assert auth.complete_login(attempt, query)
        return auth.login_status(attempt)["account_ref"]

    yield auth, calls, options, begin, connect
    auth.close()


def test_oauth_registration_and_dynamic_catalog(oauth):
    auth, calls, _, begin, _ = oauth
    assert auth.status()["accounts"] == [] and not auth.root.exists()
    attempt, query = begin()
    before = len(calls)
    assert not auth.complete_login(attempt, {**query, "state": ["wrong"]})
    assert len(calls) == before and auth.login_status(attempt)["status"] == "pending"
    assert auth.complete_login(attempt, query)
    ref = auth.login_status(attempt)["account_ref"]
    assert not auth.complete_login(attempt, query)
    catalog = auth.models(ref)
    assert [m["id"] for m in catalog["models"]] == ["future-model-z", "future-mini"]
    assert auth.models(ref) == catalog
    assert sum(r.url.path == "/v1/models" for r in calls) == 1
    public = json.dumps(auth.status()) + json.dumps(catalog)
    assert (
        "access-private" not in public
        and "refresh-private" not in public
        and "private-code" not in public
    )
    assert stat.S_IMODE(auth.root.stat().st_mode) == 0o700
    assert stat.S_IMODE((auth.root / "registrations.json").stat().st_mode) == 0o600
    saved = (auth.root / "registrations.json").read_text()
    assert "private-code" not in saved and "code_verifier" not in saved and "nonce" not in saved


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "wrong"},
        {"aud": "wrong"},
        {"iss": "https://wrong.test"},
        {"exp": 1},
        {"azp": "wrong"},
    ],
)
def test_invalid_id_never_persists_tokens(oauth, claims):
    auth, _, options, begin, _ = oauth
    options["claims"] = claims
    attempt, query = begin()
    assert not auth.complete_login(attempt, query)
    assert auth.login_status(attempt)["status"] == "failed"
    assert auth.status()["accounts"] == []
    assert "access-private" not in (auth.root / "registrations.json").read_text()


def test_missing_scopes_and_cancelled_callback(oauth):
    auth, _, options, begin, connect = oauth
    options["scope"] = "openid profile"
    connect()
    assert not auth.status()["accounts"][0]["plan_enabled"]
    attempt, query = begin()
    auth.cancel_login(attempt)
    assert not auth.complete_login(attempt, query)


def test_rotating_refresh_logout_other_process(oauth):
    auth, calls, options, _, connect = oauth
    ref = connect()
    with auth._locked():
        state = auth._read()
        state["accounts"][ref]["expires_at"] = 0
        auth._write(state)
    options.update(refresh_entered=threading.Event(), refresh_release=threading.Event())
    second = ChatGPTAuth(auth.root, transport=auth.transport)
    refresh = threading.Thread(target=lambda: auth.access(ref))
    refresh.start()
    assert options["refresh_entered"].wait(2)
    logout = threading.Thread(target=lambda: second.logout(ref))
    logout.start()
    options["refresh_release"].set()
    refresh.join(3)
    logout.join(3)
    assert not refresh.is_alive() and not logout.is_alive()
    revocations = [parse_qs(r.content.decode()) for r in calls if r.url.path == "/revoke"]
    assert revocations[-1]["token"] == ["refresh-rotated"]
    assert not auth.status()["accounts"][0]["signed_in"]
    with pytest.raises(ChatGPTError):
        auth.access(ref)


def test_refresh_invalid_grant_disables_and_failed_revocation_clears(oauth):
    auth, _, options, _, connect = oauth
    ref = connect()
    with auth._locked():
        state = auth._read()
        state["accounts"][ref]["expires_at"] = 0
        auth._write(state)
    options["refresh_error"] = True
    with pytest.raises(ChatGPTError, match="登录已失效"):
        auth.access(ref)
    assert not auth.status()["accounts"][0]["signed_in"]
    options["refresh_error"] = False
    ref = connect()
    options["revoke_status"] = 503
    assert not auth.logout(ref)["revocation_confirmed"]
    account = next(a for a in auth.status()["accounts"] if a["account_ref"] == ref)
    assert not account["signed_in"] and account["revocation_unconfirmed"]


def completed():
    return {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"answer": "ok"}'}],
                }
            ],
            "usage": {"input_tokens": 7, "output_tokens": 3},
        },
    }


def client_for(auth, ref, events, *, status=200, **kwargs):
    calls = []

    def handler(request):
        calls.append(request)
        if status != 200:
            return httpx.Response(
                status,
                json={
                    "error": {
                        "code": "subscription_sharing_usage_limit_exceeded",
                        "message": "PRIVATE",
                    }
                },
            )
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))

    client = ChatGPTClient(
        "future-model-z",
        auth=auth,
        account_ref=ref,
        stream_transport=httpx.MockTransport(handler),
        **kwargs,
    )
    return client, calls


def test_responses_payload_completion_and_usage(oauth):
    auth, _, _, _, connect = oauth
    client, calls = client_for(
        auth, connect(), [{"type": "response.output_text.delta", "delta": "ignore"}, completed()]
    )
    result = client.get_llm().invoke("explicit history")
    assert result.content == '{"answer": "ok"}' and result.usage_metadata["total_tokens"] == 10
    assert len(calls) == 1 and str(calls[0].url) == "https://api.openai.com/v1/responses"
    assert json.loads(calls[0].content) == {
        "model": "future-model-z",
        "input": [{"role": "user", "content": "explicit history"}],
        "store": False,
        "stream": True,
    }


@pytest.mark.parametrize("error,expected", [
    (httpx.ReadTimeout("PRIVATE"), "transport_timeout"),
    (httpx.ConnectError("PRIVATE"), "transport_connection_error"),
    (httpx.RemoteProtocolError("PRIVATE"), "request_failed"),
])
def test_early_transport_failure_preserves_retry_classification(oauth, error, expected):
    auth, _, _, _, connect = oauth
    def handler(request):
        raise error
    client = ChatGPTClient("future-model-z", auth=auth, account_ref=connect(),
        stream_transport=httpx.MockTransport(handler), deadline=lambda: time.monotonic() + 30)
    with pytest.raises(ChatGPTError) as caught:
        client.get_llm().invoke("prompt")
    assert caught.value.diagnostic.upstream_code == expected
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout("PRIVATE"), httpx.ReadError("PRIVATE")])
def test_partial_stream_transport_failure_is_not_replayed(oauth, error):
    auth, _, _, _, connect = oauth
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"type":"response.output_text.delta","delta":"PRIVATE"}\n\n'
            raise error
    client = ChatGPTClient("future-model-z", auth=auth, account_ref=connect(),
        stream_transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream())))
    with pytest.raises(ChatGPTError) as caught:
        client.get_llm().invoke("prompt")
    assert caught.value.diagnostic.category == "stream_incomplete"


@pytest.mark.parametrize("error", [httpx.ReadTimeout("PRIVATE"), httpx.ConnectError("PRIVATE")])
def test_transport_error_at_run_deadline_is_not_retryable(oauth, error):
    auth, _, _, _, connect = oauth
    async def handler(request):
        await asyncio.sleep(.04)
        raise error
    client = ChatGPTClient("future-model-z", auth=auth, account_ref=connect(),
        stream_transport=httpx.MockTransport(handler), deadline=lambda: time.monotonic() + .02)
    with pytest.raises(ChatGPTError) as caught:
        client.get_llm().invoke("prompt")
    assert caught.value.diagnostic.category == "deadline_exceeded"


@pytest.mark.parametrize("terminal", ["completed", "missing", "failed"])
def test_completed_items_require_terminal_completion(oauth, terminal):
    auth, _, _, _, connect = oauth
    events = [{"type": "response.output_text.delta", "delta": "partial"}]
    # A live SIWC stream can omit output from the terminal response snapshot.
    # Preserve output ordering, and do not append deltas to finalized text.
    for index, text in [(1, "world"), (0, "Hello")]:
        events.append(
            {
                "type": "response.output_item.done",
                "output_index": index,
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text}],
                },
            }
        )
    if terminal == "completed":
        end = completed()
        end["response"]["output"] = []
        events.append(end)
    elif terminal == "failed":
        events.append(
            {"type": "response.failed", "response": {"error": {"code": "request_failed"}}}
        )
    client, wire = client_for(auth, connect(), events)
    if terminal == "completed":
        result = client.get_llm().invoke("prompt")
        assert result.content == "Hello\nworld"
        assert result.usage_metadata["total_tokens"] == 10
    else:
        with pytest.raises(ChatGPTError):
            client.get_llm().invoke("prompt")
    assert len(wire) == 1


def test_completion_closes_async_stream_iterator(oauth):
    auth, _, _, _, connect = oauth
    closed = threading.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                yield ("data: " + json.dumps(completed()) + "\n\n").encode()
                await asyncio.sleep(10)
            finally:
                closed.set()

    def handler(request):
        return httpx.Response(200, stream=Stream())

    client = ChatGPTClient(
        "future-model-z",
        auth=auth,
        account_ref=connect(),
        stream_transport=httpx.MockTransport(handler),
    )
    assert client.get_llm().invoke("prompt").content == '{"answer": "ok"}'
    assert closed.is_set()


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "response.output_text.delta", "delta": "partial"}],
        [{"type": "response.incomplete"}],
        [
            {
                "type": "response.failed",
                "response": {"error": {"code": "request_failed", "message": "PRIVATE"}},
            }
        ],
        [completed() | {"response": {"status": "incomplete"}}],
    ],
)
def test_noncompleted_stream_never_returns_partial(oauth, events):
    auth, _, _, _, connect = oauth
    client, calls = client_for(auth, connect(), events)
    with pytest.raises(ChatGPTError) as caught:
        client.get_llm().invoke("prompt")
    assert len(calls) == 1 and "PRIVATE" not in str(caught.value)


def test_quota_pauses_without_retries(oauth):
    auth, _, _, _, connect = oauth
    ref = connect()
    client, calls = client_for(auth, ref, [], status=429)
    for _ in range(2):
        with pytest.raises(ChatGPTError):
            client.get_llm().invoke("prompt")
    assert len(calls) == 1 and auth.status()["accounts"][0]["usage_paused"]
    auth.retry_usage(ref)
    assert not auth.status()["accounts"][0]["usage_paused"] and len(calls) == 1


@pytest.mark.parametrize("stop", ["cancel", "deadline", "logout"])
def test_silent_stream_is_closed_on_stop(oauth, stop):
    auth, _, _, _, connect = oauth
    ref = connect()
    closed = threading.Event()
    cancelled = threading.Event()

    class Silent(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(10)
            yield b""

        async def aclose(self):
            closed.set()

    def handler(request):
        if stop == "cancel":
            threading.Timer(0.05, cancelled.set).start()
        if stop == "logout":
            threading.Timer(0.05, lambda: auth.logout(ref)).start()
        return httpx.Response(200, stream=Silent())

    client = ChatGPTClient(
        "future-model-z",
        auth=auth,
        account_ref=ref,
        cancelled=cancelled.is_set,
        deadline=lambda: time.monotonic() + 0.25,
        stream_transport=httpx.MockTransport(handler),
    )
    start = time.monotonic()
    with pytest.raises(ChatGPTError):
        client.get_llm().invoke("prompt")
    assert time.monotonic() - start < 1.5 and closed.is_set()


def test_web_guard_metadata_and_frozen_account(oauth, tmp_path):
    auth, calls, _, _, connect = oauth
    app = create_app(
        store=RunStore(tmp_path / "runs"),
        environment={},
        chatgpt_auth=auth,
        connectivity_check=lambda _: None,
    )
    with TestClient(app, base_url="http://127.0.0.1") as browser:
        config = browser.get("/api/config")
        assert config.status_code == 200 and not calls and not auth.root.exists()
        assert (
            next(p for p in config.json()["providers"] if p["id"] == "chatgpt")["authentication"]
            == "oauth"
        )
        for headers in ({}, {"Origin": "https://evil.test"}, {"Origin": "http://localhost"}):
            assert browser.post("/api/chatgpt/login", json={}, headers=headers).status_code == 403
        ref = connect()
        response = browser.get("/api/chatgpt/status")
        assert (
            response.headers["cache-control"] == "no-store"
            and "access-private" not in response.text
        )
        body = RunCreateRequest(
            ticker="600803",
            analysis_date="2026-10-10",
            research_profile="evidence_v1",
            llm_provider="chatgpt",
            chatgpt_account_ref=ref,
            quick_think_llm="future-model-z",
            deep_think_llm="future-mini",
        )
        request, keys = _analysis_request(body, {}, checkpoint_available=False, chatgpt_auth=auth)
        assert (
            request.effective_config["chatgpt_account_ref"] == ref
            and request.effective_config["backend_url"] is None
            and keys["chatgpt"]
        )
        auth.logout(ref)
        with pytest.raises(ChatGPTError):
            _analysis_request(body, {}, checkpoint_available=False, chatgpt_auth=auth)


def test_cancel_during_refresh_does_not_dispatch_or_wait_for_worker(oauth):
    auth, _, options, _, connect = oauth
    ref = connect()
    with auth._locked():
        state = auth._read()
        state["accounts"][ref]["expires_at"] = 0
        auth._write(state)
    entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
    options.update(refresh_entered=entered, refresh_release=release)
    client, wire = client_for(auth, ref, [completed()], cancelled=cancel.is_set)
    threading.Timer(0.05, cancel.set).start()
    threading.Timer(0.7, release.set).start()
    start = time.monotonic()
    with pytest.raises(ChatGPTError):
        client.get_llm().invoke("prompt")
    assert entered.is_set() and time.monotonic() - start < 0.5 and not wire
    assert release.wait(2)


def test_callback_listener_signature_and_returning_identity(oauth):
    auth, _, options, begin, connect = oauth
    ref = connect()
    attempt, query = begin(ref)
    params = parse_qs(urlsplit(auth._attempts[attempt]["redirect_uri"]).query)
    assert not params
    options["claims"] = {"sub": "different-subject"}
    assert not auth.complete_login(attempt, query)
    assert auth.status()["active_account_ref"] == ref
    assert "pending_revocations" in auth._read() and not auth._read()["pending_revocations"]
    options["claims"] = {}
    options["signing_key"] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attempt, query = begin()
    assert not auth.complete_login(attempt, query)
    assert len(auth.status()["accounts"]) == 1
    options.pop("signing_key")
    attempt, query = begin(ref)
    query.pop("client_id")  # Optional on returning authorization.
    with httpx.Client(trust_env=False) as callback:
        response = callback.get(
            auth._attempts[attempt]["redirect_uri"], params={k: v[0] for k, v in query.items()}
        )
    assert response.status_code == 200 and "access-private" not in response.text
    assert auth.login_status(attempt)["first_sign_in"] is False


def test_consent_disabled_then_enabled_shows_first_plan_notice(oauth):
    auth, _, options, begin, connect = oauth
    options["scope"] = "openid profile"
    ref = connect()
    attempt, query = begin(ref)
    assert parse_qs(urlsplit(auth.begin_login(ref)["authorization_url"]).query)["prompt"] == [
        "consent"
    ]
    options["scope"] = SCOPES
    assert auth.complete_login(attempt, query)
    assert auth.login_status(attempt)["first_sign_in"] is True
    attempt, query = begin(ref)
    assert auth.complete_login(attempt, query)
    assert auth.login_status(attempt)["first_sign_in"] is False


def test_expired_denied_and_mismatched_client_callbacks(oauth):
    auth, _, _, begin, _ = oauth
    attempt, query = begin()
    auth._attempts[attempt]["expires"] = 0
    assert auth.login_status(attempt)["status"] == "expired"
    assert not auth.complete_login(attempt, query)
    attempt, query = begin()
    assert not auth.complete_login(attempt, {**query, "error": ["access_denied"]})
    assert auth.status()["accounts"] == []
    attempt, query = begin()
    assert not auth.complete_login(attempt, {**query, "client_id": ["dynamic_agent_client"]})
    assert auth.status()["accounts"] == []


def test_batch_http_freezes_subscription_account(oauth, tmp_path):
    from tests.web.test_api import RecordingManager

    auth, _, _, _, connect = oauth
    ref = connect()
    store = RunStore(tmp_path / "batch-runs")
    from tradingagents.web.batch_models import BatchSnapshot

    class BatchManager(RecordingManager):
        def start_batch(self, prepared, *, configured_keys, concurrency):
            assert configured_keys["chatgpt"]
            assert all(
                request.effective_config["chatgpt_account_ref"] == ref for request, _ in prepared
            )
            return BatchSnapshot.create(
                items=tuple(item for _, item in prepared), concurrency=concurrency
            )

    manager = BatchManager(store)
    app = create_app(
        manager=manager, chatgpt_auth=auth, environment={}, connectivity_check=lambda _: None
    )
    config = {
        "analysis_date": "2026-10-10",
        "llm_provider": "chatgpt",
        "chatgpt_account_ref": ref,
        "quick_think_llm": "future-model-z",
        "deep_think_llm": "future-mini",
        "research_profile": "evidence_v1",
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/batches",
            json={"entries": [{"input": "600803", "config": config}], "concurrency": 1},
        )
        assert response.status_code == 201, response.text
        batch = response.json()
        assert batch["items"][0]["config"]["chatgpt_account_ref"] == ref
    assert "access-private" not in json.dumps(batch)

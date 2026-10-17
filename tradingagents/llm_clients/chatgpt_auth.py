"""Official SIWC public-client OAuth, protected local registrations and rotation.

No Codex credential import, API-key billing fallback or browser token storage.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import jwt

from .chatgpt_errors import ChatGPTError, response_error, transient_refresh_error

AUTH_ORIGIN = "https://auth.openai.com"
API_ORIGIN = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPES = frozenset({"resource.invoke", "chatgpt.tokens.use.direct"})
USAGE_URL = "https://chatgpt.com/settings/usage"
_REF = re.compile(r"^cg_[0-9a-f]{32}$")
REFRESH_MARGIN_SECONDS = 60
REFRESH_BACKOFF_SECONDS = 60
TOKEN_VALIDITY_MARGIN_SECONDS = 5


def _refresh_time(value):
    # Optional scheduling metadata must not discard a successfully rotated token.
    if type(value) is int:
        return value if value >= 0 else None
    return value if type(value) is float and math.isfinite(value) and value >= 0 else None


class ChatGPTAuth:
    def __init__(self, root=None, *, transport=None, clock=time.time):
        self.root = Path(root or Path.home() / ".tradingagents/auth/chatgpt")
        self.transport, self.clock = transport, clock
        self._guard = threading.RLock()
        self._attempts = {}
        self._catalogs = {}

    def _prepare(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ChatGPTError("invalid_identity")
        self.root.chmod(0o700)

    @contextmanager
    def _locked(self, *, timeout=10):
        # One short, cross-process credential transaction. Refresh HTTP remains
        # inside this lock, so logout always captures the latest rotated token.
        self._prepare()
        end = time.monotonic() + timeout
        if not self._guard.acquire(timeout=max(0, timeout)):
            raise ChatGPTError("deadline_exceeded")
        try:
            fd = os.open(self.root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                os.fchmod(fd, 0o600)
                if os.name == "nt":
                    import msvcrt
                    os.write(fd, b"0")
                    os.lseek(fd, 0, os.SEEK_SET)
                    def acquire():
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    def release():
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    def acquire():
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    def release():
                        fcntl.flock(fd, fcntl.LOCK_UN)
                while True:
                    try:
                        acquire()
                        break
                    except (OSError, BlockingIOError):
                        if time.monotonic() >= end:
                            raise ChatGPTError("deadline_exceeded") from None
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    release()
            finally:
                os.close(fd)

        finally:
            self._guard.release()

    def _read(self):
        path = self.root / "registrations.json"
        if path.is_symlink():
            raise ChatGPTError("invalid_identity")
        if not path.exists():
            return {"host_id": uuid4().urn, "active": None, "accounts": {}}
        try:
            path.chmod(0o600)
            value = json.loads(path.read_text())
            if not isinstance(value.get("accounts"), dict) or not isinstance(value.get("host_id"), str):
                raise ValueError("invalid")
            return value
        except (ValueError, OSError, AttributeError):
            raise ChatGPTError("invalid_identity") from None

    def _write(self, value):
        fd, name = tempfile.mkstemp(prefix=".registration-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.root / "registrations.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _account(self, state, ref):
        if not isinstance(ref, str) or not _REF.fullmatch(ref) or ref not in state["accounts"]:
            raise ChatGPTError("not_signed_in")
        return state["accounts"][ref]

    def status(self):
        # Viewing /api/config must not create credentials or perform networking.
        if not self.root.exists():
            return {"accounts": [], "active_account_ref": None, "usage_url": USAGE_URL}
        with self._locked():
            state = self._read()
            accounts = [
                {"account_ref": ref, "label": item["label"],
                 "signed_in": bool(item.get("access_token")),
                 "plan_enabled": bool(item.get("access_token")) and set(item.get("scopes", [])) >= PLAN_SCOPES and not item.get("disabled"),
                 "usage_paused": bool(item.get("usage_paused")),
                 "revocation_unconfirmed": bool(item.get("revocation_unconfirmed"))}
                for ref, item in state["accounts"].items()
            ]
            return {"accounts": accounts, "active_account_ref": state.get("active"), "usage_url": USAGE_URL}

    def select(self, ref):
        with self._locked():
            state = self._read()
            self._account(state, ref)
            state["active"] = ref
            self._write(state)

    def _request(self, method, url, *, timeout=10, **kwargs):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"auth.openai.com", "api.openai.com"} or parsed.username or parsed.password or parsed.port not in {None, 443}:
            raise ChatGPTError("invalid_identity")
        try:
            with httpx.Client(transport=self.transport, follow_redirects=False, timeout=timeout) as client:
                response = client.request(method, url, **kwargs)
            if response.status_code >= 300:
                raise response_error(response)
            return response
        except httpx.TimeoutException:
            raise ChatGPTError("transport_timeout") from None
        except httpx.NetworkError:
            raise ChatGPTError("transport_connection_error") from None
        except httpx.HTTPError:
            raise ChatGPTError("request_failed") from None

    def _discovery(self, *, timeout=10):
        try:
            config = self._request("GET", AUTH_ORIGIN + "/.well-known/openid-configuration", timeout=timeout).json()
            if config["issuer"] != AUTH_ORIGIN:
                raise ValueError("issuer")
            for key in ("jwks_uri", "revocation_endpoint"):
                parsed = urlsplit(config[key])
                if parsed.scheme != "https" or parsed.hostname != "auth.openai.com" or parsed.username or parsed.password or parsed.port not in {None, 443}:
                    raise ValueError("endpoint")
            return config
        except (KeyError, ValueError, TypeError):
            raise ChatGPTError("invalid_identity") from None

    def _validate_id(self, token, client_id, nonce, access_token):
        try:
            config = self._discovery()
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in {"RS256", "ES256"} or header["alg"] not in config["id_token_signing_alg_values_supported"]:
                raise ValueError("algorithm")
            keys = self._request("GET", config["jwks_uri"]).json()["keys"]
            key = next(k for k in keys if k.get("kid") == header.get("kid") and k.get("use", "sig") == "sig")
            claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=[header["alg"]],
                                audience=client_id, issuer=AUTH_ORIGIN,
                                options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce"]})
            if not hmac.compare_digest(str(claims["nonce"]), nonce):
                raise ValueError("nonce")
            if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id:
                raise ValueError("azp")
            if claims.get("azp", client_id) != client_id:
                raise ValueError("azp")
            if "at_hash" in claims:
                digest = jwt.get_algorithm_by_name(header["alg"]).compute_hash_digest(access_token.encode())
                at_hash = base64.urlsafe_b64encode(digest[:len(digest) // 2]).rstrip(b"=").decode()
                if not hmac.compare_digest(at_hash, str(claims["at_hash"])):
                    raise ValueError("at_hash")
            return claims
        except (jwt.PyJWTError, KeyError, StopIteration, ValueError, TypeError):
            raise ChatGPTError("invalid_identity") from None

    def begin_login(self, ref=None):
        with self._locked():
            state = self._read()
            previous = dict(self._account(state, ref)) if ref else None
            # The original local preview generated an unsupported bare hex ID.
            # Repair only an unregistered host; never change a bound identity.
            if re.fullmatch(r"[0-9a-f]{64}", state["host_id"]):
                if state["accounts"]:
                    raise ChatGPTError("invalid_identity")
                state["host_id"] = uuid4().urn
            self._write(state)  # Persist stable host ID before authorization.
        attempt_id = secrets.token_urlsafe(32)
        attempt = {"status": "pending", "state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                   "verifier": secrets.token_urlsafe(64), "expires": self.clock() + 600,
                   "account_ref": ref, "previous": previous, "host_id": state["host_id"]}
        owner = self

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Never log callback authorization codes/query strings.

            def do_GET(self):
                if urlsplit(self.path).path != "/auth/callback":
                    self.send_error(404)
                    return
                ok = owner.complete_login(attempt_id, parse_qs(urlsplit(self.path).query))
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(("授权流程已完成，可关闭此页面并返回 TradingAgents。" if ok else "授权未完成，请返回 TradingAgents 查看状态。").encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
        server.daemon_threads = True
        attempt["server"] = server
        attempt["redirect_uri"] = f"http://127.0.0.1:{server.server_port}/auth/callback"
        params = {"client_id": previous["client_id"] if previous else "dynamic_agent_client",
                  "ext_agent_host_id": state["host_id"], "response_type": "code",
                  "redirect_uri": attempt["redirect_uri"], "scope": SCOPES, "resource": API_ORIGIN,
                  "state": attempt["state"], "nonce": attempt["nonce"], "code_challenge_method": "S256",
                  "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(attempt["verifier"].encode()).digest()).rstrip(b"=").decode()}
        if previous:
            if not set(previous.get("scopes", [])) >= PLAN_SCOPES:
                params["prompt"] = "consent"
            if previous.get("email"):
                params["login_hint"] = previous["email"]
            # Retained ID tokens never travel through the workbench browser.
        else:
            params["agent_name_hint"] = "TradingAgents"
        with self._guard:
            self._attempts[attempt_id] = attempt
        threading.Thread(target=server.serve_forever, daemon=True).start()
        timer = threading.Timer(600, lambda: self.cancel_login(attempt_id, expired=True))
        timer.daemon = True
        attempt["timer"] = timer
        timer.start()
        return {"attempt_id": attempt_id, "authorization_url": AUTH_ORIGIN + "/api/accounts/authorize?" + urlencode(params)}

    def _close_attempt(self, attempt):
        if attempt.get("timer"):
            attempt["timer"].cancel()
        def close():
            attempt["server"].shutdown()
            attempt["server"].server_close()
        threading.Thread(target=close, daemon=True).start()
        for key in ("state", "nonce", "verifier", "previous"):
            attempt.pop(key, None)

    def cancel_login(self, attempt_id, *, expired=False):
        with self._guard:
            attempt = self._attempts.get(attempt_id)
            if attempt and attempt["status"] in {"pending", "exchanging"}:
                attempt["status"] = "expired" if expired else "cancelled"
                # An exchange in progress keeps its local PKCE snapshot; it will
                # revoke a late token instead of saving/re-activating an account.
                self._close_attempt(attempt)

    def login_status(self, attempt_id):
        with self._guard:
            attempt = self._attempts.get(attempt_id)
            if not attempt:
                raise ChatGPTError("invalid_callback")
            if attempt["status"] == "pending" and self.clock() >= attempt["expires"]:
                self.cancel_login(attempt_id, expired=True)
            return {key: attempt[key] for key in ("status", "account_ref", "error", "first_sign_in") if key in attempt}

    def complete_login(self, attempt_id, query):
        def single(name):
            values = query.get(name, [])
            return values[0] if len(values) == 1 and isinstance(values[0], str) else None
        with self._guard:
            pending = self._attempts.get(attempt_id)
            if not pending or pending["status"] != "pending" or self.clock() >= pending["expires"]:
                return False
            if not hmac.compare_digest(single("state") or "", pending["state"]):
                return False  # Unrelated callback cannot consume a real attempt.
            attempt = dict(pending)
            pending["status"] = "exchanging"
        token = None
        client_id = single("client_id") or (attempt["previous"]["client_id"] if attempt["previous"] else None)
        try:
            if single("error"):
                raise ChatGPTError("access_denied")
            if not client_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", client_id) or client_id == "dynamic_agent_client" or not single("code"):
                raise ChatGPTError("invalid_callback")
            if attempt["previous"] and client_id != attempt["previous"]["client_id"]:
                raise ChatGPTError("invalid_callback")
            token = self._request("POST", AUTH_ORIGIN + "/api/accounts/oauth/token", data={
                "grant_type": "authorization_code", "client_id": client_id, "code": single("code"),
                "code_verifier": attempt["verifier"], "redirect_uri": attempt["redirect_uri"], "resource": API_ORIGIN,
            }).json()
            self._validate_tokens(token)
            claims = self._validate_id(token["id_token"], client_id, attempt["nonce"], token["access_token"])
            if attempt["previous"] and (claims["sub"], claims["iss"]) != (attempt["previous"]["sub"], attempt["previous"]["issuer"]):
                raise ChatGPTError("invalid_identity")
            with self._locked():
                state = self._read()
                ref = attempt["account_ref"] or "cg_" + secrets.token_hex(16)
                previous = state["accounts"].get(ref, {})
                if pending["status"] != "exchanging" or (attempt["previous"] and previous.get("generation") != attempt["previous"].get("generation")):
                    raise ChatGPTError("session_changed")
                scopes = token.get("scope", "").split()
                notice_shown = any(item.get("plan_notice_shown") and item.get("sub") == claims["sub"]
                                   and item.get("issuer") == claims["iss"] for item in state["accounts"].values())
                first_plan_sign_in = set(scopes) >= PLAN_SCOPES and not notice_shown
                state["accounts"][ref] = {
                    "client_id": client_id, "sub": claims["sub"], "issuer": claims["iss"],
                    "email": claims.get("email", ""), "label": f"{claims.get('email') or 'ChatGPT'} · {ref[-6:]}",
                    "scopes": scopes, "access_token": token["access_token"], "refresh_token": token.get("refresh_token"),
                    "id_token": token["id_token"], "expires_at": self.clock() + token["expires_in"],
                    "earliest_refresh_at": _refresh_time(token.get("earliest_refresh_at")),
                    "generation": previous.get("generation", 0) + 1, "token_version": 1,
                    "disabled": False, "usage_paused": False, "plan_notice_shown": notice_shown or first_plan_sign_in,
                }
                state["active"] = ref
                self._write(state)
                pending.update(status="complete", account_ref=ref, first_sign_in=first_plan_sign_in)
            return True
        except (ChatGPTError, ValueError, KeyError, TypeError) as exc:
            if token and token.get("refresh_token") and client_id:
                self._revoke_late(token["refresh_token"], client_id)
            with self._guard:
                if pending["status"] == "exchanging":
                    pending.update(status="failed", error=str(exc) if isinstance(exc, ChatGPTError) else "ChatGPT 身份验证失败。")
            return False
        finally:
            self._close_attempt(pending)

    def _validate_tokens(self, token, *, require_id=True):
        required = ("access_token", "id_token") if require_id else ("access_token",)
        if not isinstance(token, dict) or any(not isinstance(token.get(k), str) or not token[k] for k in required):
            raise ChatGPTError("invalid_identity")
        expires = token.get("expires_in")
        if type(expires) not in {int, float} or not math.isfinite(expires) or expires <= 0:
            raise ChatGPTError("invalid_identity")
        if not isinstance(token.get("scope", ""), str) or (token.get("refresh_token") is not None and not isinstance(token["refresh_token"], str)):
            raise ChatGPTError("invalid_identity")
        if not isinstance(token.get("token_type"), str) or token["token_type"].lower() != "bearer":
            raise ChatGPTError("invalid_identity")

    def access(self, ref, *, timeout=10, for_inference=False):
        with self._locked(timeout=timeout):
            state = self._read()
            item = self._account(state, ref)
            if item.get("disabled") or not item.get("access_token") or not set(item.get("scopes", [])) >= PLAN_SCOPES:
                raise ChatGPTError("not_signed_in")
            if for_inference and item.get("usage_paused"):
                raise ChatGPTError("subscription_sharing_usage_limit_exceeded")
            if item["expires_at"] <= self.clock() + REFRESH_MARGIN_SECONDS:
                if not item.get("refresh_token"):
                    raise ChatGPTError("not_signed_in")
                now = self.clock()
                earliest = _refresh_time(item.get("earliest_refresh_at"))
                retry_at = _refresh_time(item.get("refresh_retry_at"))
                if ((earliest is not None and now < earliest and now < item["expires_at"])
                        or (retry_at is not None and now < retry_at)):
                    if item["expires_at"] > self.clock() + TOKEN_VALIDITY_MARGIN_SECONDS:
                        return item["access_token"], item["generation"]
                    raise ChatGPTError("refresh_temporarily_unavailable")
                try:
                    token = self._request("POST", AUTH_ORIGIN + "/api/accounts/oauth/token", timeout=timeout, data={
                        "grant_type": "refresh_token", "client_id": item["client_id"],
                        "refresh_token": item["refresh_token"], "resource": API_ORIGIN,
                    }).json()
                    self._validate_tokens(token, require_id=False)
                except ChatGPTError as exc:
                    if exc.diagnostic.category in {"invalid_grant", "invalid_client"}:
                        item["disabled"] = True
                        self._clear_tokens(item)
                        self._write(state)
                    elif transient_refresh_error(exc):
                        item["refresh_retry_at"] = self.clock() + REFRESH_BACKOFF_SECONDS
                        self._write(state)
                        if item["expires_at"] > self.clock() + TOKEN_VALIDITY_MARGIN_SECONDS:
                            return item["access_token"], item["generation"]
                        raise ChatGPTError("refresh_temporarily_unavailable") from None
                    raise
                item.update(access_token=token["access_token"], expires_at=self.clock() + token["expires_in"],
                            refresh_token=token.get("refresh_token") or item["refresh_token"],
                            earliest_refresh_at=_refresh_time(token.get("earliest_refresh_at")),
                            token_version=item.get("token_version", 0) + 1)
                item.pop("refresh_retry_at", None)
                if "scope" in token:
                    item["scopes"] = token["scope"].split()
                self._write(state)
                if not set(item["scopes"]) >= PLAN_SCOPES:
                    raise ChatGPTError("not_signed_in")
            return item["access_token"], item["generation"]

    def check_session(self, ref, generation):
        # Atomic replacement makes this read safe across processes. A stream
        # watchdog must not wait behind a refresh/revoke HTTP transaction.
        item = self._account(self._read(), ref)
        if item.get("disabled") or not item.get("access_token") or item.get("generation") != generation:
            raise ChatGPTError("session_changed")

    def pause_usage(self, ref):
        with self._locked():
            state = self._read()
            self._account(state, ref)["usage_paused"] = True
            self._write(state)

    def retry_usage(self, ref):
        with self._locked():
            state = self._read()
            self._account(state, ref)["usage_paused"] = False
            self._write(state)

    def _clear_tokens(self, item):
        for key in ("access_token", "refresh_token", "id_token", "earliest_refresh_at", "refresh_retry_at"):
            item.pop(key, None)

    def _revoke(self, token, client_id):
        end = time.monotonic() + 30
        try:
            config = self._discovery(timeout=min(10, end - time.monotonic()))
        except ChatGPTError:
            return False
        for index in range(2):
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            try:
                self._request("POST", config["revocation_endpoint"], timeout=min(10, remaining), data={
                    "token": token, "token_type_hint": "refresh_token", "client_id": client_id,
                })
                return True
            except ChatGPTError as exc:
                if exc.diagnostic.upstream_status and exc.diagnostic.upstream_status < 500:
                    return False
                if index == 0 and end - time.monotonic() > .2:
                    time.sleep(.2)
        return False

    def _revoke_late(self, token, client_id):
        # Persist a transient recovery record before revoking a cancelled or
        # identity-rejected exchange, then erase credentials on every outcome.
        key = secrets.token_hex(16)
        with self._locked():
            state = self._read()
            state.setdefault("pending_revocations", {})[key] = {"token": token, "client_id": client_id}
            self._write(state)
        try:
            return self._revoke(token, client_id)
        finally:
            with self._locked():
                state = self._read()
                state.get("pending_revocations", {}).pop(key, None)
                self._write(state)

    def logout(self, ref):
        with self._guard:
            for attempt_id, attempt in list(self._attempts.items()):
                if attempt.get("account_ref") == ref:
                    self.cancel_login(attempt_id)
        with self._locked(timeout=30):
            state = self._read()
            item = self._account(state, ref)
            item["disabled"] = True
            item["generation"] = item.get("generation", 0) + 1
            self._write(state)
            confirmed = not item.get("refresh_token") or self._revoke(item["refresh_token"], item["client_id"])
            self._clear_tokens(item)
            item["revocation_unconfirmed"] = not confirmed
            self._write(state)
            self._catalogs.pop(ref, None)
            return {"revocation_confirmed": confirmed}

    def models(self, ref, *, refresh=False):
        access, generation = self.access(ref)
        with self._guard:
            cached = self._catalogs.get(ref)
            if not refresh and cached and self.clock() - cached["fetched_at"] < 300 and cached["generation"] == generation:
                return {k: v for k, v in cached.items() if k != "generation"}
        try:
            body = self._request("GET", API_ORIGIN + "/models", timeout=5, headers={"Authorization": "Bearer " + access}).json()
            raw = body["models"]
            if not isinstance(raw, list):
                raise ValueError("catalog")
            models, seen = [], set()
            for value in raw:
                if not isinstance(value, dict):
                    raise ValueError("model")
                if value.get("visibility") != "list":
                    continue
                slug, label = value["slug"], value["display_name"]
                if not isinstance(slug, str) or not slug.strip() or len(slug) > 256 or not isinstance(label, str) or not label.strip():
                    raise ValueError("model")
                if slug not in seen:
                    models.append({"id": slug, "label": label[:256]})
                    seen.add(slug)
            if not models:
                raise ValueError("empty")
            self.check_session(ref, generation)
            result = {"account_ref": ref, "models": models, "fetched_at": self.clock(), "generation": generation}
            with self._guard:
                self._catalogs[ref] = result
            return {k: v for k, v in result.items() if k != "generation"}
        except (KeyError, ValueError, TypeError):
            raise ChatGPTError("catalog_unavailable") from None

    def close(self):
        for attempt_id in list(self._attempts):
            self.cancel_login(attempt_id)

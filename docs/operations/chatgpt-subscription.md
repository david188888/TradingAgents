# ChatGPT subscription configuration

Status: Current

## Connect and choose models

Choose **ChatGPT 订阅** in the Web workbench and **Continue with ChatGPT**. Complete official
sign-in/consent on `auth.openai.com`. An eligible account/workspace must permit SIWC plan-usage
sharing; a stored account or catalog entry alone does not establish inference permission or quota.

Both model selectors use the selected account's official catalog and exact IDs, without a local
version filter. **刷新模型** reloads it; an unavailable configured/selected ID stays explicit and
blocks submission until an available model is chosen. Single and batch runs freeze registration ref
and selected model IDs. Switching accounts does not rebind queued or saved runs.

Status/catalog refresh follows account selection and login completion, with guards against old
responses. **模型已就绪** means the catalog loaded, not that a paid request has succeeded.
Use **重新认证** for expired/rejected credentials. **账户选项** also exposes addition, logout and usage;
blocked popups have **打开官方登录页面**, and pending login can be cancelled. No automatic consent,
account switch, proxy, API-key fallback or model substitution occurs.

## Usage and failure behavior

Fresh native studies freeze `siwc-reasoning-v1`. Explicit `openai_reasoning_effort` /
`TRADINGAGENTS_OPENAI_REASONING_EFFORT` sends Responses `reasoning.effort`; omission leaves the model's
default. Accepted syntax is `none/minimal/low/medium/high/xhigh/max`, but actual support is model-dependent.
There is no Web effort selector, automatic downgrade or per-stage ChatGPT effort override.

Same-run recovery preserves the saved policy/configuration; older unmarked requests keep omitting
effort. Unknown/changed identity refuses recovery. A new-run retry uses the fresh request policy;
explanations retain their originating study's frozen binding.

Requests use the fixed streamed `https://api.openai.com/v1/responses` route with `store:false`.
Unsupported sampling, system-message and output-cap parameters are omitted. Only a completed response
is accepted; deltas, incomplete streams or premature EOF do not become saved research. Cancellation,
deadline and logout close silent streams too. Missing token usage is unknown, not zero or a price.

Recognized quota/authentication/capability/protocol failures are not automatically retried. A usage
limit pauses inference for that registration; **重新尝试** clears that local pause without sending
inference itself. Catalog transport failures may retry once without inference. Generic pre-stream
connection/timeouts or transient HTTP failures use versioned bounded native retry; incomplete streams
and focus do not retry. See [accounting](observability-replay.md#retry-and-accounting) and
[research limits](../contracts/research-record.md#search-and-execution-limits).
A completed but structurally invalid response may use the separate existing bounded schema repair.

## Local account storage and controls

Registrations live outside runs at `~/.tradingagents/auth/chatgpt/registrations.json`, in POSIX 0700
directories / 0600 files. They contain credentials; never copy them into support messages, run artifacts,
fixtures or the repository. Browser/model catalogs/run identity receive only safe status/account refs.
Codex desktop/CLI credentials are not imported. Merely reading `/api/config` does not initiate login
or inference. Account mutations require same-origin JSON on loopback and are not cached.

OAuth uses a loopback callback, state, PKCE and nonce; ID tokens are checked against official
OIDC/JWKS issuer/audience/signature/expiry/nonce. Returning sign-in reuses the registration and verifies
identity. A persisted UUIDv4 URN host identifier is reused across restarts. Cross-process locking and
atomic replacement serialize credential rotation and logout.

**退出此账户** invalidates frozen-run access, attempts official revocation and clears local tokens
regardless of remote confirmation. The UI states revocation uncertainty; adding another registration
does not silently replace the old one for saved runs.

Refresh starts within the 60-second expiry margin and respects valid `earliest_refresh_at` while the
token is unexpired. Transient refresh failures record a 60-second per-registration backoff under the
rotation lock. A retained token with more than five seconds left can be used during backoff, but this
does not promise a stream can finish before expiry; otherwise return a safe retry-later result.
An expired token is never returned for inference. Permission/quota/identity/authentication failures
cannot use transient fallback. Success, reauthentication or logout clears stale backoff; dispatch still
checks cancellation, deadline and current session. Exact allowed failure codes live in canonical code.

## Implementation and references

- [chatgpt_auth.py](../../tradingagents/llm_clients/chatgpt_auth.py): registration, OIDC and token rotation.
- [chatgpt_client.py](../../tradingagents/llm_clients/chatgpt_client.py) / [chatgpt_errors.py](../../tradingagents/llm_clients/chatgpt_errors.py): streamed request and safe failure semantics.
- [chatgpt_routes.py](../../tradingagents/web/chatgpt_routes.py) and frontend `useChatGPT`/`useConfig`: local account controls and stale-response guards.

Official protocol references: [token sharing](https://developers.openai.com/siwc/token-sharing-open-source),
[sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[models/inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[reasoning](https://developers.openai.com/api/docs/guides/reasoning?api-mode=responses) and
[token refresh](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions#refreshing-tokens).
Search uses separate DeepSeek/Tavily credentials; see [Web configuration](evidence-research.md#model-settings).

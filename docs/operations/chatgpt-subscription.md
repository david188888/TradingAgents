# ChatGPT subscription configuration

Status: Current

## Connect and choose models

In the Web workbench choose **ChatGPT 订阅** under LLM Provider, then
**Continue with ChatGPT**. Complete sign-in and consent on `auth.openai.com`.
This uses the official Sign in with ChatGPT (SIWC) direct Responses route.
It needs an eligible ChatGPT account and permission to share plan usage;
a Plus subscription alone is not proof that an account or workspace can grant it.

After authorization, both research model selectors show the selected account's
current official catalog, in its returned order. Visible models are identified by
exact `slug`, without a version list or name prefix filter. **刷新模型** retrieves
updates; disappearance preserves the selected ID and blocks new submission until
another available model is chosen. A catalog entry does not guarantee inference
permission or every capability. Admission failures retain the official error code
and a fixed, actionable message. Single and batch submissions freeze the account
registration reference along with both selected models.

## Usage and failure behavior

Eligible requests use ChatGPT plan allowance. There is no automatic switch to an
API key, third-party proxy, another account or model. The **管理用量** link opens
ChatGPT usage settings. Plan and application limits can be shared across SIWC
applications; token counts reported for one response do not establish remaining
subscription quota or monetary cost.

A usage-limit error pauses new inference for that registration. Manage usage,
then explicitly choose **重新尝试** to permit a new request; this action itself
only clears the local pause and does not send inference. Recognized quota,
authorization, capability and protocol failures are not retried. Fresh V6
baseline calls can retry generic HTTP 408/429/5xx after 2, 5 and 10 seconds,
within the shared three-retry/twelve-request ceilings; incomplete streams and
the optional focus response never retry. The client itself sends one Responses
request per invocation. See [durable retry accounting](observability-replay.md#原生模型有限网络重试).
The existing bounded JSON repair remains
available only after a successfully completed but structurally invalid response.

Requests send `store:false`, `stream:true` and explicit user input/history to the
fixed `https://api.openai.com/v1/responses` endpoint. Unsupported API sampling,
system-message and output-cap parameters are omitted. Only a completed response
is accepted. Completed output items are collected in output order when SIWC
leaves the terminal response's output snapshot empty; they are accepted only
after `response.completed`. Deltas, incomplete responses and premature EOF
cannot become saved research. Cancellation, deadlines and logout close a silent stream too. Reported
input/output token usage is measured; absent usage stays unknown.

## Local account storage and controls

OAuth uses a fresh loopback callback port, state, PKCE and nonce. ID tokens are
verified against official OIDC discovery/JWKS, including signature, issuer,
audience, expiry and nonce. New sign-in uses dynamic registration; returning
sign-in reuses the issued client ID and verifies the same issuer/subject.
The host identifier is a UUIDv4 URN (`urn:uuid:…`), persisted before first sign-in
and reused across restarts. An unsupported bare hex ID from the initial local
preview is replaced only when no account has been registered; bound host
identities are preserved.

Registrations are stored separately from runs at
`~/.tradingagents/auth/chatgpt/registrations.json`. The directory is mode 0700
and files 0600 on POSIX. Cross-process locking and atomic replacement serialize
refresh-token rotation and logout. These files contain credentials: never copy
them into the repository, logs, fixtures or support messages. The browser, run
configuration, Reader and model catalog receive only non-secret account refs and
safe status fields. Codex desktop/CLI credentials are not imported.

**退出此账户** invalidates the registration for frozen runs, attempts official
revocation using the latest refresh token, and clears local tokens even if remote
revocation cannot be confirmed. The UI states that uncertainty and directs the
user to ChatGPT settings. Adding another registration does not change existing
runs. Mutating `/api/chatgpt/*` routes require same-origin JSON on loopback;
responses are not cached. Merely viewing `/api/config` does not initiate OAuth,
create credential storage or call the upstream model endpoint.

Implementation owners: `llm_clients/chatgpt_auth.py`, `chatgpt_client.py`,
`chatgpt_errors.py`, `web/chatgpt_routes.py`, native execution and the frontend
`useChatGPT`/`useConfig` hooks. Safe model diagnostics persist in the native
checkpoint and are projected by the read-only Reader process endpoint.

Official protocol references: [OSS token sharing](https://developers.openai.com/siwc/token-sharing-open-source),
[sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).

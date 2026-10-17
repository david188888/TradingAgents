# ChatGPT v0.7.0 selective adaptation validation

Status: Historical

Do not use this document as evidence of current implementation behavior.

This records local implementation and offline validation on 2026-10-17, against
base `22d4c3f4d2d0095239696cd3055d81edbb75e507`. Current behavior belongs to
[ChatGPT operations](../operations/chatgpt-subscription.md) and
[reasoning configuration](../operations/llm-reasoning.md).

## Authorized scope and delivered behavior

The user approved continuing the upstream review's ChatGPT recommendations and
explicitly declined Release installation-package publishing. No package-data or
publishing changes were made. The two implemented adaptations are:

- Explicit `openai_reasoning_effort` reaches ChatGPT Responses JSON. Omission
  preserves the model default. Fresh native checkpoint identities freeze
  `chatgpt_request_policy=siwc-reasoning-v1`; same-run historical recovery keeps
  the original omission. Changed frozen effort or unknown policy refuses resume.
  Repairs, focus and originating report-explanation retries keep the saved policy.
- OAuth stores earliest-refresh metadata and a per-registration 60-second
  transient-failure backoff under the existing cross-process lock. A retained
  token needs more than five seconds remaining to be returned. Expired tokens,
  authorization/identity/permission/quota failures cannot use this fallback.
  Success, reauthorization and logout clear stale backoff. Cancellation still
  prevents inference dispatch after a refresh fallback.

The dedicated client, fixed official endpoint, dynamic model order, account
ownership, request budget and completed-stream acceptance remain in place.
No new model stages, provider tiers or effort selector were introduced; default
DeepSeek settings were not changed. Optional refresh ID-token revalidation is
outside this timing/fault-resilience scope.

## Verification

All Python work reused `/Users/david/miniconda3/envs/tradingagents`. Tests use
synthetic credentials, isolated temporary storage, MockTransport and injected
clocks; they do not access user accounts or research history.

Baseline before product edits: 152 relevant tests passed.

Final focused execution:

```bash
PYTHON_DOTENV_DISABLED=1 /Users/david/miniconda3/envs/tradingagents/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_chatgpt_subscription.py tests/test_native_model.py \
  tests/test_native_retry.py tests/test_report_explanation.py \
  tests/test_native_focus.py tests/web/test_profile_fingerprint_resume.py
```

Result: **242 passed**.

Public native lifecycle/recovery integration:

```bash
PYTHON_DOTENV_DISABLED=1 /Users/david/miniconda3/envs/tradingagents/bin/python -m pytest -q -p no:cacheprovider \
  tests/web/test_native_production_wiring.py \
  -k 'chatgpt or saved_effort or actual_startup or native_resume_rejects or legacy_native_resume or v7_source_isolation or v7_batch or typed_source'
```

Result: **20 passed, 10 deselected**. Combined final scope: **262 passing tests**.
Selection covers saved effort, fresh/historical ChatGPT restart/resume, saved
source replay, V7 isolation/focus and batch wiring. This is not a full Python-suite
or CI claim. Both commands reported an existing Starlette/FastAPI httpx test-client
deprecation warning.

Other checks:

```bash
/Users/david/miniconda3/envs/tradingagents/bin/ruff check tradingagents cli scripts/check_agent_docs.py \
  tests/test_chatgpt_subscription.py tests/test_native_model.py tests/test_native_retry.py \
  tests/test_report_explanation.py tests/web/test_native_production_wiring.py
/Users/david/miniconda3/envs/tradingagents/bin/python scripts/check_agent_docs.py
git diff --check
```

Ruff, agent-doc checks and whitespace checks passed. The design received an
independent spec review; its advisory transient-error whitelist was incorporated.
Architecture, both READMEs, operation docs and archive navigation were synchronized.
Root CHANGELOG.md is intentionally ignored by repository policy; this tracked
record carries the change summary instead of adding or publishing that file.

## Limits and publication state

No real OAuth/consent, live inference, quota consumption, subscription access,
investment-quality experiment, full-suite pytest, browser E2E or frontend rebuild
was performed. Frontend source and generated assets were not changed. No user
credential file was migrated or rewritten. The running service was not restarted.
No branch, commit, push, PR, merge, release or deployment was performed; changes
remain local for review. Passing fixtures establish request/recovery/failure
contracts, not real-account eligibility or investment accuracy.

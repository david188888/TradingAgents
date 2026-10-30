"""Opt-in, one-inference SIWC probe; prints no credentials or model response text.

Preview: python -m scripts.probe_chatgpt_structured_output
Execute only with authorization: add --execute (uses the active saved SIWC account).
"""

import argparse
import json
import secrets
from contextlib import suppress

import httpx

from tradingagents.llm_clients.chatgpt_auth import API_ORIGIN, ChatGPTAuth


def probe(auth, account_ref, model, *, transport=None):
    marker = secrets.token_hex(12)
    schema = {"type": "object", "properties": {"probe": {"type": "string", "enum": [marker]}},
              "required": ["probe"], "additionalProperties": False}
    access, generation = auth.access(account_ref, timeout=10, for_inference=True)
    auth.check_session(account_ref, generation)
    payload = {"model": model, "store": False, "stream": True,
        "input": [{"role": "user", "content": 'Return the JSON object {"ignored":true}.'}],
        "text": {"format": {"type": "json_schema", "name": "siwc_probe", "strict": True, "schema": schema}}}
    with httpx.Client(transport=transport, timeout=45, follow_redirects=False) as client, client.stream(
        "POST", API_ORIGIN + "/responses", headers={"Authorization": "Bearer " + access}, json=payload,
    ) as response:
        result = {"model": model, "http_status": response.status_code,
                  "accepted": response.status_code == 200, "schema_matched": False}
        if response.status_code != 200:
            return result
        for line in response.iter_lines():
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            event = json.loads(line[5:].strip())
            if event.get("type") == "response.completed":
                final = event.get("response", {})
                texts = [part["text"] for item in final.get("output", [])
                         if item.get("type") == "message" for part in item.get("content", [])
                         if part.get("type") == "output_text"]
                with suppress(ValueError, TypeError):
                    result["schema_matched"] = json.loads("".join(texts)) == {"probe": marker}
                break
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Perform one authorized real inference")
    parser.add_argument("--model", default="gpt-6.1-terra")
    parser.add_argument("--account-ref")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"dry_run": True, "model": args.model,
            "endpoint": API_ORIGIN + "/responses", "requests": 0,
            "probe": "one property, required, additionalProperties=false, randomized enum only in schema"}))
        return
    auth = ChatGPTAuth()
    ref = args.account_ref or auth.status()["active_account_ref"]
    if not ref:
        parser.error("No active SIWC account; select an existing account first.")
    try:
        result = probe(auth, ref, args.model)
    except Exception as exc:
        # Deliberately omit exception messages and provider bodies.
        print(json.dumps({"model": args.model, "probe_failed": True, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(result))
    if not result["schema_matched"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

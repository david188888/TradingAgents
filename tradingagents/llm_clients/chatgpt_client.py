"""Single Responses HTTP/SSE inference using a frozen SIWC registration."""

import asyncio
import json
import time

import httpx
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from .base_client import BaseLLMClient
from .chatgpt_auth import API_ORIGIN
from .chatgpt_errors import ChatGPTError, response_error
from .chatgpt_policy import validate_reasoning_effort


class ChatGPTClient(BaseLLMClient):
    def __init__(self, model, base_url=None, *, auth, account_ref, cancelled=lambda: False,
                 deadline=None, stream_transport=None, before_request=lambda: None,
                 reasoning_effort=None, **kwargs):
        super().__init__(model, base_url, **kwargs)
        if base_url:
            raise ChatGPTError("subscription_sharing_route_not_supported")
        self.auth, self.account_ref, self.cancelled = auth, account_ref, cancelled
        self.deadline = deadline or (lambda: time.monotonic() + 300)
        self.stream_transport = stream_transport
        self.before_request = before_request
        self.reasoning_effort = validate_reasoning_effort(reasoning_effort)
        self.provider = "chatgpt"
        self.response_format = kwargs.get("response_format")

    def validate_model(self):
        # Actual admission uses the selected account's dynamic catalog in Web;
        # no hard-coded model prefixes, version comparisons or legacy lists.
        return isinstance(self.model, str) and bool(self.model.strip())

    def get_llm(self):
        return RunnableLambda(self._sync_invoke)

    def _sync_invoke(self, prompt):
        # asyncio.run waits for its default executor on teardown. A cancelled
        # refresh worker must be allowed to finish its bounded credential
        # transaction without holding this inference caller open.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._invoke(prompt))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    async def _invoke(self, prompt):
        if not isinstance(prompt, str):
            raise ChatGPTError("subscription_sharing_unsupported_capability")
        end = self.deadline()
        if self.cancelled():
            raise ChatGPTError("cancelled")
        if end <= time.monotonic():
            raise ChatGPTError("deadline_exceeded")
        generation = None
        received_data = False

        async def watch():
            while True:
                if self.cancelled():
                    raise ChatGPTError("cancelled")
                if time.monotonic() >= end:
                    raise ChatGPTError("deadline_exceeded")
                if generation is not None:
                    self.auth.check_session(self.account_ref, generation)
                await asyncio.sleep(0.1)

        async def request():
            nonlocal generation, received_data
            access, generation = await asyncio.to_thread(
                self.auth.access, self.account_ref, timeout=min(10, max(.001, end - time.monotonic())), for_inference=True,
            )
            self.auth.check_session(self.account_ref, generation)
            if self.cancelled():
                raise ChatGPTError("cancelled")
            if time.monotonic() >= end:
                raise ChatGPTError("deadline_exceeded")
            self.before_request()
            timeout = max(0.001, end - time.monotonic())
            payload = {"model": self.model, "input": [{"role": "user", "content": prompt}],
                       "store": False, "stream": True}
            if self.reasoning_effort is not None:
                payload["reasoning"] = {"effort": self.reasoning_effort}
            if self.response_format is not None:
                payload["text"] = {"format": {"type": "json_schema", **self.response_format["json_schema"]}}
            async with httpx.AsyncClient(transport=self.stream_transport, follow_redirects=False, timeout=timeout) as client, client.stream("POST", API_ORIGIN + "/responses",
                                         headers={"Authorization": "Bearer " + access},
                                         json=payload) as response:
                if response.status_code >= 300:
                    await response.aread()
                    raise response_error(response)
                payload, finalized = [], {}
                async for line in response.aiter_lines():
                    if not line:
                        if payload:
                            event = self._event("\n".join(payload), response.headers.get("x-request-id"), finalized)
                            payload = []
                            if event is not None:
                                return event
                    elif line.startswith("data:"):
                        received_data = True
                        payload.append(line[5:].lstrip())
                if payload:
                    event = self._event("\n".join(payload), response.headers.get("x-request-id"), finalized)
                    if event is not None:
                        return event
                raise ChatGPTError("stream_incomplete")
        tasks = [asyncio.create_task(request()), asyncio.create_task(watch())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # Cancellation/deadline/session changes win a simultaneous completion.
            if tasks[1] in done:
                return tasks[1].result()
            result = tasks[0].result()
            if self.cancelled():
                raise ChatGPTError("cancelled")
            if time.monotonic() >= end:
                raise ChatGPTError("deadline_exceeded")
            self.auth.check_session(self.account_ref, generation)
            return result
        except ChatGPTError as exc:
            if exc.diagnostic.category == "subscription_sharing_usage_limit_exceeded":
                await asyncio.to_thread(self.auth.pause_usage, self.account_ref)
            raise
        except httpx.TimeoutException:
            code = "deadline_exceeded" if time.monotonic() >= end else (
                "stream_incomplete" if received_data else "transport_timeout")
            raise ChatGPTError(code) from None
        except httpx.NetworkError:
            code = "deadline_exceeded" if time.monotonic() >= end else (
                "stream_incomplete" if received_data else "transport_connection_error")
            raise ChatGPTError(code) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            raise ChatGPTError("request_failed") from None
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _event(self, data, request_id, finalized):
        if data == "[DONE]":
            raise ChatGPTError("stream_incomplete")
        event = json.loads(data)
        kind = event.get("type")
        if kind == "response.output_item.done":
            index, item = event.get("output_index"), event.get("item")
            if type(index) is int and index >= 0 and isinstance(item, dict):
                finalized[index] = item
            return None
        if kind in {"response.failed", "error"}:
            error = event.get("response", {}).get("error") or event.get("error") or event
            code = error.get("code") or "request_failed"
            raise ChatGPTError(code, request_id=request_id)
        if kind == "response.incomplete":
            raise ChatGPTError("stream_incomplete", request_id=request_id)
        if kind != "response.completed":
            return None
        response = event["response"]
        if response.get("status") != "completed":
            raise ChatGPTError("stream_incomplete", request_id=request_id)
        # SIWC can leave the terminal output snapshot empty even though its
        # completed output items carried the text. Those items remain unusable
        # until this response.completed event confirms the whole request.
        output = response.get("output") or [finalized[index] for index in sorted(finalized)]
        texts = [part["text"] for item in output if item.get("type") == "message"
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        if not texts:
            raise ChatGPTError("stream_incomplete", request_id=request_id)
        usage = response.get("usage") or {}
        measured = all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens"))
        return AIMessage(content="\n".join(texts), usage_metadata={
            "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        } if measured else None)

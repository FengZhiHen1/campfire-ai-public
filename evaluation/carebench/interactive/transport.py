"""记录真实 HTTP 尝试与独立评审调用；不记录认证头。"""

from __future__ import annotations

import contextvars
import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..manifest import utc_now
from .storage import append

CALL_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("interactive_call", default={})
JUDGE_PARAMETERS = {"temperature": 0, "max_tokens": 6000}


def attach_http_journal(gateway: Any, root: Path) -> None:
    """旁路观察请求，不提前读取流式正文或改变产品的重试策略。"""
    client = gateway.client._client

    async def request_hook(request: Any) -> None:
        identifier = uuid.uuid4().hex
        request.extensions["interactive_id"] = identifier
        request.extensions["interactive_started"] = time.monotonic()
        try:
            body = json.loads(request.content)
        except (ValueError, UnicodeError):
            body = {"unreadable": True}
        append(
            root / "http.jsonl",
            {
                "kind": "request",
                "call_id": identifier,
                "context": CALL_CONTEXT.get(),
                "created_at": utc_now(),
                "body": body,
            },
        )

    async def response_hook(response: Any) -> None:
        request = response.request
        append(
            root / "http.jsonl",
            {
                "kind": "response_headers",
                "call_id": request.extensions["interactive_id"],
                "created_at": utc_now(),
                "status_code": response.status_code,
                "headers_latency_ms": int((time.monotonic() - request.extensions["interactive_started"]) * 1000),
            },
        )

    client.event_hooks["request"].append(request_hook)
    client.event_hooks["response"].append(response_hook)


def completion(gateway: Any, root: Path, *, context: dict[str, Any]):
    async def complete(prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        identifier = uuid.uuid4().hex
        append(
            root / "calls.jsonl",
            {
                "kind": "started",
                "call_id": identifier,
                "context": context,
                "prompt": prompt,
                "payload": payload,
                "parameters": JUDGE_PARAMETERS,
                "created_at": utc_now(),
            },
        )
        token = CALL_CONTEXT.set({**context, "completion_id": identifier})
        started = time.monotonic()
        try:
            response = await gateway.client.chat.completions.create(
                model=gateway.model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "DATA\n" + json.dumps(payload, ensure_ascii=False)},
                ],
                **JUDGE_PARAMETERS,
            )
            text = response.choices[0].message.content if response.choices else ""
            result = {
                "text": text or "",
                "raw": response.model_dump(mode="json"),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "call_id": identifier,
            }
        except BaseException as exc:
            append(
                root / "calls.jsonl",
                {
                    "kind": "finished",
                    "call_id": identifier,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "created_at": utc_now(),
                },
            )
            raise
        else:
            append(
                root / "calls.jsonl",
                {"kind": "finished", "call_id": identifier, "status": "ok", "response": result},
            )
            return result
        finally:
            CALL_CONTEXT.reset(token)

    return complete

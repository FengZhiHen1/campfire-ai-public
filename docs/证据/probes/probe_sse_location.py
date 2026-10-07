"""真机验证：SSE 路径是否命中 nginx 的**流式 location**（而不是通用的 /api/ location）。

为什么必须验「命中了哪个 location」而不只是「路径能通」：
前缀从 `/consult` 改成 `/api/consult` 时，SSE 那条正则 location 也必须同步改。
若忘了改，请求仍会 200/401（被通用的 `location /api/` 接走），**但缓冲是开的**——
表现为前端「回复一次性蹦出来」，且任何状态码与日志都正常。这正是之前用假上游消融
测出来的那个失败模式。

区分手段：流式 location 里有 `add_header Cache-Control "no-store" always;`，
通用 location 没有。因此看响应头即可知道请求走了哪条。

判据：SSE 路径的响应带头部含 `Cache-Control: no-store`；普通 API 路径不含。
"""

import urllib.error
import urllib.request

BASE = "http://127.0.0.1:18094"


def headers(path: str) -> tuple[int, dict[str, str]]:
    request = urllib.request.Request(BASE + path, headers={"Accept": "text/event-stream"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers)
    except Exception as exc:  # noqa: BLE001 —— 探针
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


print("=== 判断请求走了哪条 location（看 Cache-Control: no-store）===")
sse_status, sse_headers = headers("/api/consult/runs/probe/stream")
sse_cache = sse_headers.get("Cache-Control", "(无)")
print(f"  SSE 路径   /api/consult/runs/probe/stream  HTTP {sse_status}  Cache-Control={sse_cache}")

api_status, api_headers = headers("/api/consult/sessions")
api_cache = api_headers.get("Cache-Control", "(无)")
print(f"  普通 API   /api/consult/sessions           HTTP {api_status}  Cache-Control={api_cache}")

sse_streaming = "no-store" in sse_cache
api_generic = "no-store" not in api_cache
print()
print(f"SSE 路径命中流式 location（缓冲已关）: {sse_streaming}")
print(f"普通 API 走通用 location（未套用 SSE 设置）: {api_generic}")
print()
print("总判定:", "通过——SSE 的正则 location 已随前缀同步" if (sse_streaming and api_generic) else "未通过")

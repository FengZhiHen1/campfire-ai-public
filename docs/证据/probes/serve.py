"""T11 后端启动器：在**进程内**规范化 no_proxy 之后再引导 uvicorn。

为什么不用 `set NO_PROXY=... && uvicorn`（T10 记录的做法）：本机实测该做法不可靠——
在同一个 pwsh 命令里设好变量后，`cmd` 与 `node` 子进程看到的是新值，而 `.venv` 的
python 子进程 `os.environ` 仍读到旧值 `127.0.0.1,localhost,::1,[::1]`（同一进程里
`GetEnvironmentVariableW` 却返回新值），于是 httpx 在客户端构造期抛
`InvalidURL: Invalid port: ':1]'`，注册/登录整体 500 而 `/readyz` 的 auth 项仍报 ok。
用 Python 在**导入任何 httpx 消费者之前**写 `os.environ`，绕开那一层不一致。

这是测试装置，不是产品代码（放在 tmp/ 下）。它只做一件事：规范化 no_proxy。
"""

import os
import sys

os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

import httpx  # noqa: E402 —— 必须在规范化之后导入

proxies = httpx._utils.get_environment_proxies()
print(f"[T11 backend] no_proxy 已规范化为 {os.environ['no_proxy']!r}", flush=True)
print(f"[T11 backend] httpx 代理表 = {proxies}", flush=True)
httpx.AsyncClient()  # 构造成功才继续；这一步就是 T10 那个缺陷的判据
print("[T11 backend] httpx 默认客户端构造成功（无 InvalidURL）", flush=True)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run("campfire.main:app", host="127.0.0.1", port=port, log_level="info")

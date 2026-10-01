"""代理环境变量的规范化：让「合法的 no_proxy」不被 httpx2 的解析缺陷拒绝。

职责：在构造 httpx2 客户端期间，把 `no_proxy` 家族里的 IPv6 字面量从 `[::1]` 规范成 `::1`。
边界：只规范化那一族的取值，不动 `http_proxy`/`https_proxy`/`all_proxy`；只包住构造期。
参考：`gateway.py` 的模块 docstring「已核实的宿主机环境陷阱」。

为什么需要它（2026-10-01 实测，这是一条真实的启动阻塞）：

宿主机 `no_proxy` 含带方括号的 IPv6 字面量时（例如
`127.0.0.1,localhost,::1,[::1]`——这是相当常见的服务端取值），httpx2 解析豁免列表会抛
`InvalidURL: Invalid port: ':1]'`，而那发生在**客户端构造期**。后果不是「模型调用失败」
而是更早：`ModelGateway.__init__` 直接抛 `ModelConfigurationError`，于是依赖它的产品侧
装配失败、运行器注不进去、产品端点稳定回 503。

**这是词法问题，不是语义问题**：实测两种写法经 httpx2 解析出的豁免模式完全相同——

    输入 `...,::1,[::1]` → 豁免模式 [`all://127.0.0.1`, `all://localhost`, `all://[::1]`]
    输入 `...,::1`       → 豁免模式 [`all://127.0.0.1`, `all://localhost`, `all://[::1]`]
    输入 `[::1]`（未规范）→ 构造期抛 InvalidURL
    输入 `::1`（已规范） → 豁免模式 [`all://[::1]`]

即：方括号形式**本来就该**被解析成 `all://[::1]`，只是解析器在规范化之前就崩了。
因此本模块做的正是那个缺失的规范化步骤，不改变任何匹配结果——`http://[::1]:8000/x`
在两种输入下都命中豁免。

为什么是无方括号形式而不是别的写法：不带方括号的 IPv6 字面量正是 httpx 自己的
`URLPattern` 输出形式（见上面的实测输出），所以它才是「解析器想要的输入」。

为什么用上下文管理器而不是直接改 `os.environ` 一处了事：`no_proxy` 的取值不只我们读
——同一进程里可能有别的组件（以及开发者自己的调试）依赖它；长期改写别人的环境变量
是越界。本模块只在「构造客户端」这一小段窗口内生效，并在 `finally` 里逐字还原
（包括「本来不存在」这一情形），因此对进程其余部分不可见。

线程安全说明（如实声明残余风险）：`os.environ` 是进程级的，窗口期内若有别的线程
同时构造客户端，它也会看到规范化后的取值——那对它同样是**修复**而非破坏（规范化
不改变语义，只让解析不崩），因此这个窗口是可接受的。窗口本身只有一次同步构造的时长。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

#: 参与规范化的环境变量名。大小写两种都要：httpx 读小写，而部分平台/工具只设大写。
PROXY_ENV_NAMES: tuple[str, ...] = ("no_proxy", "NO_PROXY")

#: httpx2 解析不了带方括号的 IPv6 字面量，因此把它们去掉方括号。
#:
#: 判据写成「以 `[` 开头、以 `]` 结尾且中间含 `:`」而不是匹配固定几个取值：
#: 任何 IPv6 字面量在 no_proxy 里都可能被这样写（`[2001:db8::1]` 同样会让解析器崩），
#: 而只处理 `[::1]` 会把同类问题留给下一个地址。
_IPV6_BRACKET_PREFIX = "["
_IPV6_BRACKET_SUFFIX = "]"


def normalize_no_proxy(value: str) -> str:
    """把一个 `no_proxy` 取值里的方括号 IPv6 字面量规范化。

    保留分隔符与顺序（逗号分隔，含空项与前后空白原样保留），只改「方括号包 IPv6」
    这一种形态；其余取值（域名、IPv4、通配、CIDR）逐字不动。

    判别性：输入 `127.0.0.1,[::1],example.com` → `127.0.0.1,::1,example.com`；
    输入 `example.com,10.0.0.0/8` → 原样返回。
    """
    parts: list[str] = []
    for raw in value.split(","):
        token = raw.strip()
        if token.startswith(_IPV6_BRACKET_PREFIX) and token.endswith(_IPV6_BRACKET_SUFFIX):
            inner = token[len(_IPV6_BRACKET_PREFIX) : -len(_IPV6_BRACKET_SUFFIX)]
            # 含 `:` 才是 IPv6 字面量；`[host]` 这类别的写法不动它（不猜）。
            if ":" in inner:
                # 保留原取值的前后空白形状，只替换中间那一段。
                leading = raw[: len(raw) - len(raw.lstrip())]
                trailing = raw[len(raw.rstrip()) :]
                parts.append(f"{leading}{inner}{trailing}")
                continue
        parts.append(raw)
    return ",".join(parts)


@contextmanager
def normalized_no_proxy_environment() -> Iterator[None]:
    """在块内把 `no_proxy` 家族规范化，退出时逐字还原。

    还原是精确的：某个变量原本不存在，退出后仍然不存在（不被写成空串）——把
    「未设置」变成「设置为空」会改变 httpx 的行为（空串是「豁免一切」以外的另一种
    取值），因此那一档必须区分。
    """
    saved: dict[str, str | None] = {name: os.environ.get(name) for name in PROXY_ENV_NAMES}
    try:
        for name in PROXY_ENV_NAMES:
            current = saved[name]
            if current is not None:
                os.environ[name] = normalize_no_proxy(current)
        yield
    finally:
        for name, original in saved.items():
            if original is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original


__all__ = ["PROXY_ENV_NAMES", "normalize_no_proxy", "normalized_no_proxy_environment"]

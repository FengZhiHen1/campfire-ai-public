"""SEC-05 输入校验防护 — HTML 内容安全清洗。

提供 sanitize_html() 纯函数，使用 Python 标准库 html.escape() 执行
OWASP 五字符转义，防止 XSS 攻击。
"""

from __future__ import annotations

import html


def sanitize_html(text: str) -> str:
    """对用户提交的文本内容执行 HTML 实体转义，返回安全的纯文本。

    转义字符集（OWASP XSS Prevention Cheat Sheet Rule #1）：
      & → &amp;
      < → &lt;
      > → &gt;
      " → &quot;
      ' → &#x27;

    Args:
        text: 待清洗的原始文本，可能包含 HTML 标签或脚本片段。

    Returns:
        经过 html.escape() 转义后的纯文本，可安全嵌入 HTML 页面展示。

    Raises:
        TypeError: 如果 text 不是字符串类型。

    Side Effects:
        无。本函数为纯函数，不访问外部资源。

    Thread Safety:
        本函数内部不维护可变状态，线程安全。
    """
    if not isinstance(text, str):
        raise TypeError(
            f"sanitize_html expects str, got {type(text).__name__}"
        )
    # 先反转义（unescape）再转义，保证幂等性：
    # sanitize_html(sanitize_html(x)) == sanitize_html(x)
    # 避免 html.escape() 对已转义内容中的 & 进行二次转义。
    return html.escape(html.unescape(text), quote=True)

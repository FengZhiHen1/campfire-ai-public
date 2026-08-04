"""security 扩展——安全能力挂载点（加载清单首位）。

S3 占位：红线关键词门、免责声明注入、PII 脱敏在代码层实现
（emergency 编排与守卫层）；S5 迁移为本扩展的事件挂载
（input 红线门 / before_agent_start 免责声明 / tool_result PII）。

安全不让渡：本扩展 handler 为纯代码，LLM 不可见不可控。
"""

from py_agent_kernel import ExtensionAPI


def extension(pi: ExtensionAPI) -> None:
    """安全扩展入口（S3 占位——启动断言目标）。"""
    return None

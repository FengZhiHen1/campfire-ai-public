"""api-server Agent 装配——agent_bootstrap（DSR-006 启动装配层）。

职责：
- 应急面扩展清单（security 首位）与加载顺序显式声明
- 启动断言：安全扩展已加载且位于首位（缺失即拒绝启动，Agent内核框架 §八.3）
- 面白名单注入（首份方案无工具 / 追问轮 rag_search）
- DeepSeek 模型实例构建（pydantic-ai provider 接入）

S3 范围：security 占位扩展 + emergency 扩展（emergency-consult Skill）；
扩展全量（case/profile/ticket/knowledge）在 S5 注册。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from py_agent_kernel import AgentSession, create_agent_session
from py_config import get_settings

# ---------------------------------------------------------------------------
# 扩展清单（加载顺序即优先级；security 必须首位——安全不变量）
# ---------------------------------------------------------------------------

_EXTENSIONS_ROOT = Path(__file__).resolve().parents[4] / "packages" / "py-agent-extensions" / "py_agent_extensions"

EMERGENCY_EXTENSIONS: list[Path] = [
    _EXTENSIONS_ROOT / "security",
    _EXTENSIONS_ROOT / "emergency",
]

# 面白名单（Agent 基座 §5.1）：
# 首份方案 max_steps=1、零工具调用（TTFT 工程前提）；追问轮放行 rag_search
EMERGENCY_INITIAL_TOOLS: list[str] = []
EMERGENCY_FOLLOWUP_TOOLS: list[str] = ["rag_search"]


def assert_security_first(loaded_extensions: list[Any]) -> None:
    """启动断言：安全扩展已加载且位于加载清单首位。

    缺失/错位即拒绝启动（受控加载三要素之一，Agent内核框架 §八）。
    """
    if not loaded_extensions:
        raise RuntimeError("启动断言失败：扩展清单为空，安全扩展未加载")
    first = loaded_extensions[0]
    if first.meta.name != "security":
        raise RuntimeError(
            f"启动断言失败：安全扩展必须位于加载清单首位（当前首位为 {first.meta.name}）"
        )


def build_emergency_model() -> Any:
    """构建 DeepSeek 模型实例（pydantic-ai OpenAI 兼容 provider 接入）。

    环境缺失自愈：未配置 API Key 时抛 RuntimeError（调用方降级处理，
    测试以 TestModel 注入替代——不伪造外部可用性）。
    """
    settings = get_settings()
    api_key = getattr(settings, "DEEPSEEK_API_KEY", None)
    base_url = getattr(settings, "DEEPSEEK_BASE_URL", None)
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法构建应急面模型")
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    provider_kwargs: dict[str, Any] = {
        "api_key": api_key.get_secret_value() if hasattr(api_key, "get_secret_value") else str(api_key)
    }
    if base_url:
        provider_kwargs["base_url"] = str(base_url)
    model_name = getattr(settings, "DEEPSEEK_MODEL", "deepseek-chat")
    return OpenAIChatModel(model_name, provider=OpenAIProvider(**provider_kwargs))


def create_emergency_session(
    *,
    model: Any | None = None,
    session_id: str | None = None,
    followup: bool = False,
    output_type: Any | None = None,
    system_prompt: str = "",
    audit_sink: Any | None = None,
) -> AgentSession:
    """创建应急面 Agent 会话。

    Args:
        model: 模型实例（None = 生产 DeepSeek；测试注入 TestModel）。
        session_id: 会话 ID（与咨询会话一致，供审计关联）。
        followup: 追问轮（放行 rag_search 白名单）。
        output_type: 结构化输出契约（首份方案传 EmergencyPlan，追问轮 None）。
        system_prompt: 系统提示（首份方案为强制加载的 Skill 正文 + 免责声明）。
        audit_sink: 工具调用审计外送回调。
    """
    from py_agent_kernel.events.bus import EventBus
    from py_agent_kernel.extension_api import load_extensions
    from py_agent_kernel.runtime.session import PreloadedExtensions
    from py_agent_kernel.tools.toolset import KernelToolset

    # 显式清单加载 + 启动断言（受控加载）
    bus = EventBus()
    toolset = KernelToolset(session_id=session_id or "bootstrap")
    loaded = load_extensions(EMERGENCY_EXTENSIONS, bus, toolset)
    assert_security_first(loaded)

    skill_dirs = [d for ext in loaded for d in ext.skill_dirs]
    resolved_model = model if model is not None else build_emergency_model()

    return create_agent_session(
        resolved_model,
        extensions=[],
        system_prompt=system_prompt,
        output_type=output_type,
        skills_dirs=skill_dirs,
        active_tools=EMERGENCY_FOLLOWUP_TOOLS if followup else EMERGENCY_INITIAL_TOOLS,
        session_id=session_id,
        audit_sink=audit_sink,
        preloaded=PreloadedExtensions(bus=bus, toolset=toolset, loaded=loaded),
    )


__all__ = [
    "EMERGENCY_EXTENSIONS",
    "EMERGENCY_INITIAL_TOOLS",
    "EMERGENCY_FOLLOWUP_TOOLS",
    "assert_security_first",
    "build_emergency_model",
    "create_emergency_session",
]

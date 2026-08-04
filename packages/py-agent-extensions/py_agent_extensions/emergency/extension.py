"""emergency 扩展——应急咨询面（Agent 基座 §三）。

emergency 扩展不持有工具（应急面工具分属 profile/case/ticket，
经面白名单消费，扩展间零 import）；本扩展承载 emergency-consult Skill 包。
"""

from py_agent_kernel import ExtensionAPI


def extension(pi: ExtensionAPI) -> None:
    """应急扩展入口（S3 占位：Skill 经 skills/ 目录自动发现）。

    追问轮的 rag_search 自主调用经面白名单注入（agent_bootstrap），
    本扩展不直接注册工具。
    """
    # S3：无事件 handler——红线门与免责声明在代码层（S5 迁移至 security 扩展事件挂载）
    return None

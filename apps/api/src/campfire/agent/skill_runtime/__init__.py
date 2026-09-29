"""开放标准 skill 机制：发现、元数据装载、激活、按需加载、校验。

归属（见 docs/项目结构设计.md 第 3 节）：**机制**归基座；**内容**归
``apps/api/skills/`` 下的产物目录。

已核实的设计前提（见 docs/技术栈设计.md 第 2 节）：OpenAI Agents SDK 的 `skills`
能力只存在于 sandbox capabilities，**不是**「领域方法论 + 工具范围按需激活」的
一般原语，因此 skill 注册表与工具范围控制由本项目实现。

关键约束（见 docs/技术设计/technical-details/通用基座.md 第 3 节）：

- frontmatter **只用标准的六个字段**，不得自创；自有元数据放 ``metadata``。
- 发现时**不合法即拒绝加载并在启动时失败**，不得以空元数据静默加载。
- 目录注入只含 ``name`` 与 ``description``；目录**预算上限 4000 token**。
- 校验使用标准参照实现 ``skills-ref validate``，纳入工程检查。
- 一期不做安装、市场与运行时下发；skills 随应用发布，根目录由配置指定。

模块分工：:mod:`~campfire.agent.skill_runtime.frontmatter` 只做「文本 → 映射」，
:mod:`~campfire.agent.skill_runtime.skill` 只做字段语义，:mod:`registry` 负责发现与
取用，:mod:`catalog` 与 :mod:`activation` 只做渲染（纯函数）。
"""

from .activation import render_activation
from .catalog import CATALOG_BUDGET_TOKENS, estimate_tokens, render_catalog, visible_to
from .errors import (
    SkillCatalogOverflowError,
    SkillDiscoveryError,
    SkillError,
    SkillFrontmatterError,
    SkillNotFoundError,
    SkillResourceError,
)
from .registry import SKILL_FILE_NAME, SkillRegistry, SkillWarning
from .resources import MAX_RESOURCE_BYTES, RESOURCE_DIRECTORIES, SkillResource, list_resources, read_resource
from .script_runner import ScriptRunner
from .skill import NAME_PATTERN, Skill, SkillMetadata

__all__ = [
    "CATALOG_BUDGET_TOKENS",
    "MAX_RESOURCE_BYTES",
    "NAME_PATTERN",
    "RESOURCE_DIRECTORIES",
    "SKILL_FILE_NAME",
    "ScriptRunner",
    "Skill",
    "SkillCatalogOverflowError",
    "SkillDiscoveryError",
    "SkillError",
    "SkillFrontmatterError",
    "SkillMetadata",
    "SkillNotFoundError",
    "SkillRegistry",
    "SkillResource",
    "SkillResourceError",
    "SkillWarning",
    "estimate_tokens",
    "list_resources",
    "read_resource",
    "render_activation",
    "render_catalog",
    "visible_to",
]

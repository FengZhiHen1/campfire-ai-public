"""py-agent-kernel 扩展契约——ExtensionAPI 与扩展加载器（pi extension 语义移植）。

组织轴（pi extension 语义）：
- 扩展物理形态：目录（含 extension.py / __init__.py + 可选 skills/）或单文件
- 入口：默认导出工厂函数 def extension(pi: ExtensionAPI) -> None
- 生命周期：加载（导入并执行工厂）→ 会话绑定（session_start）→ 卸载（session_shutdown）
- 加载顺序即优先级：事件 handler 按加载顺序执行；宿主显式声明清单

声明式元数据（自造契约，Agent内核框架 §十偏差清单）：
- extension.yaml：name / version / kernel（内核版本兼容区间）
- 启动时校验，不符合拒绝加载
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from py_agent_kernel.events.bus import EventBus, EventHandler
from py_agent_kernel.events.types import KernelEvent
from py_agent_kernel.tools.toolset import KernelToolset
from py_agent_kernel.tools.types import AgentTool

# 内核版本（extension.yaml 兼容性校验基准）
KERNEL_VERSION = "0.1.0"


# ===========================================================================
# ExtensionAPI（扩展侧消费面）
# ===========================================================================


class ExtensionAPI:
    """扩展 API——pi ExtensionAPI 形态（事件订阅/工具注册/命令注册/资源发现）。

    扩展工厂函数接收本对象：
        def extension(pi: ExtensionAPI) -> None:
            pi.on("tool_call", on_tool_call)
            pi.register_tool(my_tool)
            pi.register_command("my-cmd", handler)
    """

    def __init__(self, bus: EventBus, toolset: KernelToolset, extension_name: str) -> None:
        self._bus = bus
        self._toolset = toolset
        self._extension_name = extension_name
        self._commands: dict[str, Callable[..., Any]] = {}
        self._skill_paths: list[Path] = []

    # ------------------------------------------------------------------
    # 事件订阅
    # ------------------------------------------------------------------

    def on(self, event: KernelEvent | str, handler: EventHandler) -> None:
        """订阅事件（按扩展加载顺序执行）。"""
        self._bus.subscribe(event, handler)

    # ------------------------------------------------------------------
    # 工具注册
    # ------------------------------------------------------------------

    def register_tool(self, tool: AgentTool) -> None:
        """注册工具（工具名全局唯一，重名拒绝）。"""
        self._toolset.register(tool)

    # ------------------------------------------------------------------
    # 命令注册（宿主侧调用）
    # ------------------------------------------------------------------

    def register_command(self, name: str, handler: Callable[..., Any]) -> None:
        """注册命令（宿主侧调用入口，如管理命令/调试命令）。"""
        self._commands[name] = handler

    @property
    def commands(self) -> dict[str, Callable[..., Any]]:
        return dict(self._commands)

    # ------------------------------------------------------------------
    # 资源发现（pi extension 原生能力：动态贡献 skill 路径）
    # ------------------------------------------------------------------

    def contribute_skill_path(self, path: str | Path) -> None:
        """动态贡献 Skill 目录（等价 pi resources_discover 能力）。"""
        self._skill_paths.append(Path(path))

    @property
    def skill_paths(self) -> list[Path]:
        return list(self._skill_paths)

    @property
    def extension_name(self) -> str:
        return self._extension_name


# ===========================================================================
# 扩展元数据与加载
# ===========================================================================


@dataclass
class ExtensionMeta:
    """extension.yaml 元数据（自造契约，偏差清单项）。"""

    name: str
    version: str
    kernel: str = ""  # 内核版本兼容区间（PEP 440 specifier，如 ">=0.1.0,<0.2.0"）


class ExtensionLoadError(Exception):
    """扩展加载失败（元数据缺失/内核版本不兼容/入口缺失）。"""


@dataclass
class LoadedExtension:
    """已加载扩展的运行时表示。"""

    meta: ExtensionMeta
    path: Path | None  # 目录形态为目录路径；单文件/工厂形态为 None
    api: ExtensionAPI
    skill_dirs: list[Path] = field(default_factory=list)


def _validate_kernel_compat(specifier: str) -> bool:
    """内核版本兼容性校验（PEP 440 SpecifierSet）。"""
    if not specifier:
        return True
    try:
        from packaging.specifiers import SpecifierSet

        return KERNEL_VERSION in SpecifierSet(specifier)
    except Exception as exc:
        raise ExtensionLoadError(f"extension.yaml kernel 版本区间非法: {specifier!r}（{exc}）") from exc


def _load_meta(ext_dir: Path) -> ExtensionMeta:
    """读取并校验 extension.yaml（缺失/不兼容拒绝加载）。"""
    yaml_path = ext_dir / "extension.yaml"
    if not yaml_path.exists():
        raise ExtensionLoadError(f"扩展缺少 extension.yaml: {ext_dir}")
    try:
        data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ExtensionLoadError(f"extension.yaml 解析失败: {yaml_path}（{exc}）") from exc

    name = data.get("name")
    version = data.get("version")
    if not name or not version:
        raise ExtensionLoadError(f"extension.yaml 缺少必填字段 name/version: {yaml_path}")
    kernel_spec = str(data.get("kernel", ""))
    if not _validate_kernel_compat(kernel_spec):
        raise ExtensionLoadError(
            f"扩展 {name}@{version} 与内核 {KERNEL_VERSION} 不兼容（要求 {kernel_spec}）"
        )
    return ExtensionMeta(name=str(name), version=str(version), kernel=kernel_spec)


def _import_factory_from_dir(ext_dir: Path) -> Callable[[ExtensionAPI], None]:
    """从目录形态导入扩展工厂（extension.py 或 __init__.py）。"""
    for candidate in (ext_dir / "extension.py", ext_dir / "__init__.py"):
        if candidate.exists():
            spec = importlib.util.spec_from_file_location(f"py_agent_kernel_ext_{ext_dir.name}", candidate)
            if spec is None or spec.loader is None:
                break
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            factory = getattr(module, "extension", None)
            if callable(factory):
                return factory
            break
    raise ExtensionLoadError(f"扩展入口缺失：{ext_dir} 需含 extension.py/__init__.py 且导出 extension 工厂函数")


def _import_factory_from_file(file_path: Path) -> Callable[[ExtensionAPI], None]:
    """从单文件形态导入扩展工厂。"""
    spec = importlib.util.spec_from_file_location(f"py_agent_kernel_ext_{file_path.stem}", file_path)
    if spec is None or spec.loader is None:
        raise ExtensionLoadError(f"无法加载扩展文件: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "extension", None)
    if not callable(factory):
        raise ExtensionLoadError(f"扩展文件未导出 extension 工厂函数: {file_path}")
    return factory


def load_extension(
    spec: str | Path | Callable[[ExtensionAPI], None],
    bus: EventBus,
    toolset: KernelToolset,
) -> LoadedExtension:
    """加载单个扩展（导入并执行工厂函数）。

    Args:
        spec: 扩展目录路径 / 单文件路径 / 工厂函数（内存形态，测试与宿主直注用）。
        bus: 事件总线（订阅目标）。
        toolset: 内核工具集（注册目标）。

    Returns:
        LoadedExtension（含元数据、API 面、发现的 skill 目录）。

    Raises:
        ExtensionLoadError: 元数据缺失/不兼容/入口缺失。
    """
    if callable(spec):
        # 内存形态：无 extension.yaml（宿主直注/测试用），元数据合成
        api = ExtensionAPI(bus, toolset, extension_name=getattr(spec, "__name__", "inmemory"))
        spec(api)
        return LoadedExtension(
            meta=ExtensionMeta(name=api.extension_name, version="0.0.0"),
            path=None,
            api=api,
            skill_dirs=list(api.skill_paths),
        )

    path = Path(spec)
    if path.is_dir():
        meta = _load_meta(path)
        api = ExtensionAPI(bus, toolset, extension_name=meta.name)
        factory = _import_factory_from_dir(path)
        factory(api)
        # skills/ 常规目录自动发现（吸收 pi package 行为，偏差清单项）
        skill_dirs: list[Path] = []
        skills_dir = path / "skills"
        if skills_dir.is_dir():
            skill_dirs.append(skills_dir)
        skill_dirs.extend(api.skill_paths)
        return LoadedExtension(meta=meta, path=path, api=api, skill_dirs=skill_dirs)

    if path.is_file():
        meta = ExtensionMeta(name=path.stem, version="0.0.0")
        api = ExtensionAPI(bus, toolset, extension_name=meta.name)
        factory = _import_factory_from_file(path)
        factory(api)
        return LoadedExtension(meta=meta, path=path.parent, api=api, skill_dirs=list(api.skill_paths))

    raise ExtensionLoadError(f"扩展路径不存在: {spec}")


def load_extensions(
    specs: list[str | Path | Callable[[ExtensionAPI], None]],
    bus: EventBus,
    toolset: KernelToolset,
) -> list[LoadedExtension]:
    """按清单顺序加载扩展（加载顺序即优先级——宿主显式声明）。"""
    loaded: list[LoadedExtension] = []
    for spec in specs:
        loaded.append(load_extension(spec, bus, toolset))
    return loaded


__all__ = [
    "ExtensionAPI",
    "ExtensionMeta",
    "LoadedExtension",
    "ExtensionLoadError",
    "load_extension",
    "load_extensions",
    "KERNEL_VERSION",
]

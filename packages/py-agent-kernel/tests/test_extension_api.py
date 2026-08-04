"""扩展契约与加载器单元测试——ExtensionAPI / extension.yaml 校验 / 生命周期。"""

from __future__ import annotations

from pathlib import Path

import pytest
from py_agent_kernel.events import EventBus, KernelEvent
from py_agent_kernel.extension_api import (
    ExtensionLoadError,
    load_extension,
    load_extensions,
)
from py_agent_kernel.tools import KernelToolset


@pytest.fixture
def bus_and_toolset():
    return EventBus(), KernelToolset(session_id="test-session")


def _make_extension_dir(
    base: Path,
    name: str,
    *,
    kernel_spec: str = ">=0.1.0,<0.2.0",
    with_yaml: bool = True,
    with_skills: bool = False,
) -> Path:
    """构造扩展目录（extension.yaml + extension.py）。"""
    ext_dir = base / name
    ext_dir.mkdir(parents=True, exist_ok=True)
    if with_yaml:
        (ext_dir / "extension.yaml").write_text(
            f'name: {name}\nversion: "0.1.0"\nkernel: "{kernel_spec}"\n',
            encoding="utf-8",
        )
    (ext_dir / "extension.py").write_text(
        "def extension(pi):\n"
        "    def _handler(ctx):\n"
        "        return None\n"
        "    pi.on('agent_start', _handler)\n",
        encoding="utf-8",
    )
    if with_skills:
        skill_dir = ext_dir / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: 演示\n---\n\n正文\n",
            encoding="utf-8",
        )
    return ext_dir


class TestDirectoryExtension:
    def test_load_success(self, bus_and_toolset, tmp_path):
        bus, toolset = bus_and_toolset
        ext_dir = _make_extension_dir(tmp_path, "demo")
        loaded = load_extension(ext_dir, bus, toolset)
        assert loaded.meta.name == "demo"
        assert loaded.meta.version == "0.1.0"
        assert bus.has_handlers(KernelEvent.AGENT_START)

    def test_missing_yaml_rejected(self, bus_and_toolset, tmp_path):
        bus, toolset = bus_and_toolset
        ext_dir = _make_extension_dir(tmp_path, "noyaml", with_yaml=False)
        with pytest.raises(ExtensionLoadError, match="extension.yaml"):
            load_extension(ext_dir, bus, toolset)

    def test_incompatible_kernel_rejected(self, bus_and_toolset, tmp_path):
        bus, toolset = bus_and_toolset
        ext_dir = _make_extension_dir(tmp_path, "incompat", kernel_spec=">=99.0.0")
        with pytest.raises(ExtensionLoadError, match="不兼容"):
            load_extension(ext_dir, bus, toolset)

    def test_skills_dir_auto_discovered(self, bus_and_toolset, tmp_path):
        """skills/ 常规目录自动发现（pi package 行为吸收，偏差清单项）。"""
        bus, toolset = bus_and_toolset
        ext_dir = _make_extension_dir(tmp_path, "withskills", with_skills=True)
        loaded = load_extension(ext_dir, bus, toolset)
        assert any(d.name == "skills" for d in loaded.skill_dirs)


class TestSingleFileExtension:
    def test_load_from_file(self, bus_and_toolset, tmp_path):
        bus, toolset = bus_and_toolset
        ext_file = tmp_path / "single_ext.py"
        ext_file.write_text(
            "def extension(pi):\n"
            "    pi.register_command('ping', lambda: 'pong')\n",
            encoding="utf-8",
        )
        loaded = load_extension(ext_file, bus, toolset)
        assert "ping" in loaded.api.commands


class TestInMemoryFactory:
    def test_factory_directly(self, bus_and_toolset):
        bus, toolset = bus_and_toolset

        def my_extension(pi):
            pi.on("agent_start", lambda ctx: None)

        loaded = load_extension(my_extension, bus, toolset)
        assert loaded.meta.name == "my_extension"
        assert bus.has_handlers(KernelEvent.AGENT_START)


class TestLoadOrder:
    @pytest.mark.asyncio
    async def test_load_order_is_priority(self, bus_and_toolset, tmp_path):
        """加载顺序即 handler 执行顺序（安全扩展首位断言的基础）。"""
        bus, toolset = bus_and_toolset
        order: list[str] = []

        def make(name):
            def ext(pi):
                def handler(ctx):
                    order.append(name)
                    return None

                pi.on("agent_start", handler)

            return ext

        load_extensions([make("security"), make("case"), make("profile")], bus, toolset)
        from py_agent_kernel.events import EventContext

        await bus.emit(EventContext(KernelEvent.AGENT_START, "s", {}))
        assert order == ["security", "case", "profile"]

    def test_nonexistent_path_rejected(self, bus_and_toolset, tmp_path):
        bus, toolset = bus_and_toolset
        with pytest.raises(ExtensionLoadError, match="不存在"):
            load_extension(tmp_path / "missing", bus, toolset)

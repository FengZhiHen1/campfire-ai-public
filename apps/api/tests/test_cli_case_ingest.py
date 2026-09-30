"""`ingest --library case` 的命令行契约（不连库、不调模型）。

设计（公共案例库第 6 节）把案例入库定成「只接导出物」：入口是本应用包内的 CLI，
`manifest.json` 是必须补的一环。本组用例锁住入口行为：

1. `--library` 缺省仍是资料库（默认值不得漂移成案例库）；
2. 非法库别由 argparse 拒绝（退出码非 0），不静默回退；
3. 案例库路径必须是含 manifest 的**目录**，缺失即明确失败（退出码 1）；
4. 资料库专属参数在 `--library case` 下**显式拒绝**而不静默忽略。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campfire.cli.__main__ import _build_parser, main


def test_library_defaults_to_knowledge() -> None:
    """不给 `--library` 时默认资料库——既有摄取行为不得被这次改动改变。"""
    args = _build_parser().parse_args(["ingest", "some.md"])

    assert args.library == "knowledge"


def test_library_accepts_case() -> None:
    """`--library case` 被接受。"""
    args = _build_parser().parse_args(["ingest", "pkg", "--library", "case"])

    assert args.library == "case"


@pytest.mark.parametrize("bad", ["cases", "Knowledge", "profile", ""])
def test_invalid_library_is_rejected_by_the_parser(bad: str) -> None:
    """非法库别被 argparse 拒绝（choices 约束）——不静默回退到某个库。"""
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["ingest", "pkg", "--library", bad])

    assert excinfo.value.code != 0


def test_case_ingest_rejects_missing_directory(tmp_path: Path) -> None:
    """案例库路径不存在 → 退出码 1（不静默成功）。"""
    code = main(["ingest", str(tmp_path / "nope"), "--library", "case"])

    assert code == 1


def test_case_ingest_rejects_directory_without_manifest(tmp_path: Path) -> None:
    """目录存在但没有 `manifest.json` → 退出码 1，错误信息点明缺什么。"""
    package = tmp_path / "no-manifest"
    package.mkdir()

    assert main(["ingest", str(package), "--library", "case"]) == 1


def test_case_ingest_rejects_knowledge_only_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--library case` 下传 `--source` → 明确拒绝（不静默忽略）。

    为什么必须拒绝而不是忽略：案例的出处来自 manifest，静默忽略会让运维以为
    自己覆盖了出处，而库里存的是 manifest 的值——这类「看着成功、其实没生效」
    的差异事后极难发现。

    判别性：去掉 `_reject_knowledge_only_flags` 的调用后，本用例会因为 manifest
    只有 `{}`（缺必填字段）也返回 1——因此这里**同时断言错误信息里出现 `--source`**，
    让「因别的原因返回 1」不会冒充通过。
    """
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "manifest.json").write_text("{}", encoding="utf-8")

    code = main(["ingest", str(package), "--library", "case", "--source", "某出处"])

    assert code == 1
    assert "--source" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--scope", "--title"])
def test_case_ingest_rejects_each_knowledge_only_flag(
    tmp_path: Path, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--scope` / `--title` 同样在案例库下被拒，且错误信息点明是哪个参数。"""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "manifest.json").write_text("{}", encoding="utf-8")

    assert main(["ingest", str(package), "--library", "case", flag, "某值"]) == 1
    assert flag in capsys.readouterr().err


def test_case_path_message_mentions_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """缺 manifest 的失败信息必须点明 manifest——不让人去猜为什么失败。"""
    package = tmp_path / "no-manifest-msg"
    package.mkdir()

    main(["ingest", str(package), "--library", "case"])

    captured = capsys.readouterr()
    assert "manifest" in captured.err


def test_knowledge_library_still_requires_a_file(tmp_path: Path) -> None:
    """资料库路仍要求单文件路径（把目录传给它 → 失败，不误当成案例包）。"""
    directory = tmp_path / "a-directory"
    directory.mkdir()

    assert main(["ingest", str(directory)]) == 1


def test_usage_mentions_case_library() -> None:
    """用法文本提到 `--library case`——入口的自我说明要与支持的能力一致。

    判别性：从 `_USAGE` 删掉那一行，本用例失败。用法文本是运维唯一能看到的
    「这个入口支持什么」，能力加了而说明没加等于没有。
    """
    from campfire.cli.__main__ import _USAGE

    assert "--library case" in _USAGE

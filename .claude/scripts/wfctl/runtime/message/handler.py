"""消息写入、校验、消费。"""

import json
import uuid
from pathlib import Path

from compat import CURRENT
from compat.instance.registry import load_instance_state
from infrastructure.io import atomic_write_json
from infrastructure.timestamp import iso_timestamp
from infrastructure.errors import ValidationError
from infrastructure.temp_files import is_temp_file
from runtime.worktree.git import git_status_porcelain
from infrastructure.project import find_root
from services.validator import validate_modified_files


def write_message(
    instance_id: str,
    stage_id: str,
    stage_instance_id: str,
    status: str,
    report: str,
    checkpoint_summary: str | None = None,
    confirm_questions: list[str] | None = None,
    parallel_targets: list[dict] | None = None,
    routing_choice: str | None = None,
    worktree: Path | None = None,
    message_target_path: str | None = None,
) -> dict:
    """SubAgent 调用 message write 时执行。

    1. 校验调用者身份（instance_id / stage_id 须与 identity 文件一致）
    2. 通过 git status --porcelain 注入 modified_files
    3. 原子写入消息到 .agent/instances/<id>/messages/
    """
    if message_target_path:
        messages_dir = Path(message_target_path)
    else:
        root = find_root()
        messages_dir = root / ".agent" / "instances" / instance_id / "messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    message_id = f"msg-{uuid.uuid4().hex[:8]}"

    # 注入 modified_files（通过 git status --porcelain）
    modified_files: list[dict] = []
    if worktree and worktree.exists():
        rc, stdout, _ = git_status_porcelain(worktree)
        if rc == 0:
            for line in stdout.strip().splitlines():
                if line and len(line) >= 3:
                    xy = line[:2]
                    rest = line[3:]
                    if " -> " in rest:
                        filename = rest.split(" -> ")[-1]
                    else:
                        filename = rest
                    file_status = _map_git_status_xy(xy)
                    if not is_temp_file(filename):
                        modified_files.append({"path": filename, "status": file_status})

    # 自动清理空文件（SubAgent 经常产出无意义的空占位文件）
    _cleanup_empty_files(worktree, modified_files)

    # 防线前移：拒绝修改 worktree 外文件的写入
    if worktree and worktree.exists() and modified_files:
        escaped = _find_escaped_files(worktree, modified_files)
        if escaped:
            raise ValidationError(
                f"禁止修改 worktree 外的文件，请删除以下文件后重新上报：\n"
                + "\n".join(f"  - {f}" for f in escaped),
                code="ACCESS_VIOLATION",
            )

    # 防线前移：status 必须为合法 StageStatus 枚举值
    from domain.workflow.spec import StageStatus as _StageStatus
    _valid_statuses = {s.value for s in _StageStatus}
    if status not in _valid_statuses:
        raise ValidationError(
            f"非法的 status: '{status}'。合法值：{sorted(_valid_statuses)}",
            code="INVALID_STATUS",
        )

    # 硬性约束：DONE + 有 valid_routing_choices 的 stage 必须传 routing_choice
    if status == "DONE":
        try:
            state = load_instance_state(instance_id)
            st = state.stage_by_instance_id(stage_instance_id)
            if st and st.valid_routing_choices:
                if not routing_choice:
                    raise ValidationError(
                        f"本 stage 支持条件路由，上报 DONE 时必须通过 --choice 指定路由值。"
                        f"合法选项：{st.valid_routing_choices}",
                        code="ROUTING_CHOICE_REQUIRED",
                    )
                matched = _match_routing_choice(routing_choice, st.valid_routing_choices)
                if matched is None:
                    raise ValidationError(
                        f"非法的 routing_choice: '{routing_choice}'。"
                        f"合法选项：{st.valid_routing_choices}\n"
                        f"请使用精确的选项值重新上报（如 --choice \"通过\"）",
                        code="INVALID_ROUTING_CHOICE",
                    )
        except ValidationError:
            raise
        except Exception:
            # 无法加载实例状态时降级放行，消费端仍有兜底校验
            pass

    # 硬性约束：AWAITING_CONFIRM 的 questions 必须非空且符合 "choice_key：描述" 格式
    if status == "AWAITING_CONFIRM":
        questions = confirm_questions or []
        if not questions:
            raise ValidationError(
                "AWAITING_CONFIRM 必须通过 --questions 提供至少 1 个确认选项。"
                "格式：--questions \"choice_key：描述\"，使用中文全角冒号 `：` 分隔",
                code="QUESTIONS_REQUIRED",
            )
        if len(questions) > 4:
            raise ValidationError(
                f"questions 最多 4 项，当前 {len(questions)} 项",
                code="QUESTIONS_TOO_MANY",
            )
        for q in questions:
            if "：" not in q or q.split("：", 1)[0].strip() == "":
                raise ValidationError(
                    f"question 格式错误: '{q}'。"
                    f"每项必须为 \"choice_key：描述\"，使用中文全角冒号 `：` 分隔，choice_key 不能为空",
                    code="QUESTION_FORMAT_INVALID",
                )

    msg = {
        "schema_version": CURRENT.value,
        "message_id": message_id,
        "instance_id": instance_id,
        "stage_id": stage_id,
        "stage_instance_id": stage_instance_id,
        "status": status,
        "report": report,
        "checkpoint_summary": checkpoint_summary or "",
        "confirm_questions": confirm_questions or [],
        "parallel_targets": parallel_targets,
        "routing_choice": routing_choice,
        "modified_files": modified_files,
        "timestamp": iso_timestamp(),
    }

    msg_path = messages_dir / f"{message_id}.json"
    atomic_write_json(msg_path, msg)
    return {"status": "ok", "message_id": message_id}


def scan_messages(instance_id: str, consumed_ids: set[str], messages_dir: str | Path | None = None) -> list[dict]:
    """扫描消息池，返回未消费的消息列表。"""
    if messages_dir:
        messages_dir = Path(messages_dir)
    else:
        root = find_root()
        messages_dir = root / ".agent" / "instances" / instance_id / "messages"
    if not messages_dir.exists():
        return []

    messages: list[dict] = []
    for msg_file in sorted(messages_dir.glob("msg-*.json")):
        try:
            data = json.loads(msg_file.read_text(encoding="utf-8"))
            mid = data.get("message_id")
            if mid and mid not in consumed_ids:
                messages.append(data)
        except Exception:
            import sys
            import traceback
            print(
                f"[wfctl] WARNING: failed to read message {msg_file.name}: {traceback.format_exc()}",
                file=sys.stderr,
            )

    # 按时间戳排序
    messages.sort(key=lambda m: m.get("timestamp", ""))
    return messages


def validate_parallel_targets(instance_id: str, stage_id: str, output_message_id: str | None) -> None:
    """验证 stage 的消息中包含 parallel_targets。"""
    from infrastructure.errors import InputError
    if not output_message_id:
        raise InputError(
            f"Stage {stage_id} 需要产出 parallel_targets 但无 output_message_id。"
            f"请使用中继确认（自循环）让 SubAgent 在确认后继续执行并上报 parallel_targets。",
            code="PARALLEL_TARGETS_REQUIRED",
        )
    root = find_root()
    msg_path = root / ".agent" / "instances" / instance_id / "messages" / f"{output_message_id}.json"
    if not msg_path.exists():
        raise InputError(
            f"Stage {stage_id} 需要产出 parallel_targets 但消息文件 {output_message_id}.json 不存在。",
            code="PARALLEL_TARGETS_REQUIRED",
        )
    try:
        msg = json.loads(msg_path.read_text(encoding="utf-8"))
    except Exception:
        raise InputError(
            f"Stage {stage_id} 的消息文件 {output_message_id}.json 解析失败。",
            code="PARALLEL_TARGETS_REQUIRED",
        )
    if not msg.get("parallel_targets"):
        raise InputError(
            f"Stage {stage_id} 需要产出 parallel_targets 但当前消息中未包含。"
            f"请使用中继确认（自循环）让 SubAgent 补交 parallel_targets。",
            code="PARALLEL_TARGETS_REQUIRED",
        )


def inject_modified_files(msg: dict, worktree: Path) -> dict:
    """通过 git status --porcelain 获取变更列表，注入 modified_files。"""
    rc, stdout, _ = git_status_porcelain(worktree)
    modified_files: list[dict] = []
    if rc == 0:
        for line in stdout.strip().splitlines():
            if line and len(line) >= 3:
                # git status --porcelain 格式: XY filename 或 XY orig -> new
                xy = line[:2]
                rest = line[3:]
                if " -> " in rest:
                    filename = rest.split(" -> ")[-1]
                else:
                    filename = rest
                status = _map_git_status_xy(xy)
                if not is_temp_file(filename):
                    modified_files.append({"path": filename, "status": status})

    _cleanup_empty_files(worktree, modified_files)

    msg["modified_files"] = modified_files
    return msg


def _find_escaped_files(worktree: Path, modified_files: list[dict]) -> list[str]:
    """检测 modified_files 中逃逸到 worktree 外的文件路径，返回违规路径列表。"""
    escaped: list[str] = []
    wt_resolved = worktree.resolve()
    for entry in modified_files:
        fpath = entry["path"]
        try:
            abs_path = (worktree / fpath).resolve()
            abs_path.relative_to(wt_resolved)
        except ValueError:
            escaped.append(fpath)
    return escaped


def _cleanup_empty_files(worktree: Path, modified_files: list[dict]) -> None:
    """删除空文件并从 modified_files 列表中移除对应条目。"""
    if not worktree or not worktree.exists():
        return
    i = 0
    while i < len(modified_files):
        entry = modified_files[i]
        fpath = worktree / entry["path"]
        try:
            if fpath.is_file() and fpath.stat().st_size == 0:
                fpath.unlink()
                modified_files.pop(i)
                continue
        except OSError:
            pass
        i += 1


def _match_routing_choice(raw: str, valid: list[str]) -> str | None:
    """将 SubAgent 上报的 routing_choice 匹配到合法值。

    支持精确匹配和前缀匹配（SubAgent 可能在 choice key 后追加 `：描述`）。
    如 raw='通过：确认设计文档' 且 valid=['通过', ...] → 返回 '通过'。
    """
    if raw in valid:
        return raw
    for v in valid:
        if raw.startswith(v) and len(raw) > len(v) and raw[len(v)] in ("：", ":"):
            return v
    return None


def _map_git_status_xy(xy: str) -> str:
    """将 git status --porcelain 的 XY 位映射为简化状态。"""
    if not xy or len(xy) < 2:
        return "M"
    for char in xy:
        if char in "MADRC":
            return char
    if "?" in xy:
        return "?"
    return "M"

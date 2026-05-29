"""py-rag 索引入库契约 — 黑盒对抗测试。

测试对象：
  - BaseIndexService._validate_case_id()
  - BaseIndexService._validate_enqueue_result()
  - BaseIndexService.enqueue()          [@final, 异步]
  - BaseIndexService.manual_retry()     [@final, 异步]
  - BaseIndexPipeline._validate_task_preconditions()
  - BaseIndexPipeline._validate_task_postconditions()
  - BaseIndexPipeline.process_task()    [@final, 异步]

隔离约束：严禁 import indexing/*.py 或访问任何实现代码。
"""

from __future__ import annotations

import uuid as uuid_lib
from typing import Any

import pytest

from py_rag.indexing_contract import BaseIndexPipeline, BaseIndexService
from py_rag.types import CaseIdStr, TraceIdStr


# ============================================================================
# Mock 子类 — 最小合法实现
# ============================================================================


class MockIndexService(BaseIndexService):
    """测试用 mock：_do_enqueue 返回合法状态，_check_case_status 返回可入队。"""

    def __init__(self, return_status: str = "approved_pending") -> None:
        super().__init__()
        self._mock_return_status = return_status

    async def _do_enqueue(
        self, case_id: CaseIdStr, db_session: Any
    ) -> dict[str, str]:
        return {"status": "enqueued"}

    async def _check_case_status(
        self, case_id: CaseIdStr, db_session: Any
    ) -> str | None:
        return self._mock_return_status

    def set_status(self, status: str | None) -> None:
        """修改 _check_case_status 返回值，用于测试不同分支。"""
        self._mock_return_status = status


class MockBadEnqueueService(BaseIndexService):
    """返回不含 'status' 键的 dict，测试 _validate_enqueue_result。"""

    async def _do_enqueue(
        self, case_id: CaseIdStr, db_session: Any
    ) -> dict[str, str]:
        return {"result": "ok"}  # 缺少 status 键

    async def _check_case_status(
        self, case_id: CaseIdStr, db_session: Any
    ) -> str | None:
        return "approved_pending"


class MockIndexPipeline(BaseIndexPipeline):
    """测试用 mock：实现所有 @abstractmethod 钩子，走完整管线。

    _do_build_chunk / _do_write_index 通过构造时注入的 callable 实现，
    不再作为 abstractmethod 覆写。
    """

    def __init__(self, embedding_encoder: object = None) -> None:
        self._chunk_result: tuple[str, object] = ("测试切片文本", object())
        self._embedding_result: list[float] = [0.0] * 1024

        async def _mock_index_writer(**kwargs: Any) -> None:
            return None

        # 注入 dummy Protocol 实现
        super().__init__(
            embedding_encoder=embedding_encoder or object(),
            chunk_builder=lambda data: self._chunk_result,
            index_writer=_mock_index_writer,
        )
        self._status_processing_updated: bool = False
        self._marked_indexed_calls: list[CaseIdStr] = []
        self._marked_failed_calls: list[dict] = []
        self._case_data: dict[str, Any] | None = {"title": "测试案例"}
        self._status_processing_result: bool = True
        self._fail_on: str | None = None
        self._fail_message: str = "模拟失败"

    def set_chunk_result(self, text: str, metadata: object) -> None:
        """修改 chunk_builder 返回值。"""
        self._chunk_result = (text, metadata)

    def set_index_writer(self, fn) -> None:
        """替换 index_writer callable。"""
        self._index_writer = fn

    def fail_on(self, phase: str, message: str = "模拟失败") -> None:
        """设置在指定阶段抛出异常。

        phase: 'processing'|'read'|'build'|'embed'|'write'|'mark_indexed'
        注意：build/write 通过替换注入的 callable 为抛异常的 lambda 实现。
        """
        self._fail_on = phase
        self._fail_message = message
        if phase == "build":
            self._chunk_builder = lambda data: (_ for _ in ()).throw(RuntimeError(message))
        if phase == "write":
            async def _failing_writer(**kwargs: Any) -> None:
                raise RuntimeError(message)
            self._index_writer = _failing_writer

    async def _do_update_status_to_processing(
        self, case_id: CaseIdStr, db_session: Any
    ) -> bool:
        if self._fail_on == "processing":
            raise RuntimeError(self._fail_message)
        self._status_processing_updated = True
        return self._status_processing_result

    async def _do_read_case_data(
        self, case_id: CaseIdStr, db_session: Any
    ) -> dict[str, Any] | None:
        if self._fail_on == "read":
            raise RuntimeError(self._fail_message)
        return self._case_data

    async def _do_generate_embedding(self, chunk_text: str) -> list[float]:
        if self._fail_on == "embed":
            raise RuntimeError(self._fail_message)
        return self._embedding_result

    async def _do_mark_indexed(self, case_id: CaseIdStr, db_session: Any) -> None:
        if self._fail_on == "mark_indexed":
            raise RuntimeError(self._fail_message)
        self._marked_indexed_calls.append(case_id)

    async def _do_mark_failed(
        self, case_id: CaseIdStr, error: str, phase: str, db_session: Any
    ) -> None:
        self._marked_failed_calls.append(
            {"case_id": case_id, "error": error, "phase": phase}
        )


# ============================================================================
# P0：禁止行为测试 — BaseIndexService 校验
# ============================================================================


VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


class TestValidateCaseId:
    """_validate_case_id() 基线校验测试。"""

    def test_p0_invalid_uuid_format_raises_valueerror(self):
        """非 UUID 格式字符串应抛 ValueError，消息含 '无效的 case_id 格式'。"""
        service = MockIndexService()
        with pytest.raises(ValueError, match="无效的 case_id 格式"):
            service._validate_case_id("not-a-valid-uuid")  # type: ignore[arg-type]

    def test_p0_empty_string_raises_valueerror(self):
        """空字符串应抛 ValueError。"""
        service = MockIndexService()
        with pytest.raises(ValueError, match="无效的 case_id 格式"):
            service._validate_case_id("")  # type: ignore[arg-type]

    def test_p0_random_garbage_raises_valueerror(self):
        """随机乱码字符串应抛 ValueError。"""
        service = MockIndexService()
        with pytest.raises(ValueError, match="无效的 case_id 格式"):
            service._validate_case_id("!@#$%^&*()")  # type: ignore[arg-type]

    def test_p0_none_raises_valueerror(self):
        """None 经过 str() 转换后为 'None'，非有效 UUID → ValueError。"""
        service = MockIndexService()
        with pytest.raises(ValueError, match="无效的 case_id 格式"):
            # 注意：NewType 在运行时是 str，但这里故意传 None 测试防御性
            # 实际调用链：str(None) = 'None' → uuid.UUID('None') → ValueError
            service._validate_case_id(None)  # type: ignore[arg-type]

    def test_p0_too_short_uuid_raises_valueerror(self):
        """少于 32 位十六进制的字符串应抛 ValueError。"""
        service = MockIndexService()
        with pytest.raises(ValueError, match="无效的 case_id 格式"):
            service._validate_case_id("abc123")  # type: ignore[arg-type]


class TestValidateEnqueueResult:
    """_validate_enqueue_result() 基线校验测试。"""

    def test_p0_result_missing_status_key_raises_runtimeerror(self):
        """返回 dict 缺少 'status' 键应抛 RuntimeError。"""
        service = MockIndexService()
        with pytest.raises(RuntimeError, match="status"):
            service._validate_enqueue_result({"result": "ok", "message": "done"})

    def test_p0_result_not_dict_raises_runtimeerror(self):
        """返回非 dict 类型（如 str）应抛 RuntimeError。"""
        service = MockIndexService()
        with pytest.raises(RuntimeError, match="status"):
            service._validate_enqueue_result("not a dict")  # type: ignore[arg-type]

    def test_p0_result_empty_dict_raises_runtimeerror(self):
        """空 dict 缺少 'status' 键应抛 RuntimeError。"""
        service = MockIndexService()
        with pytest.raises(RuntimeError, match="status"):
            service._validate_enqueue_result({})

    def test_p0_result_with_status_key_passes(self):
        """包含 'status' 键的 dict 应通过校验。"""
        service = MockIndexService()
        # 不应抛异常
        service._validate_enqueue_result({"status": "enqueued"})


# ============================================================================
# P0：禁止行为测试 — BaseIndexPipeline 校验
# ============================================================================


class TestValidateTaskPreconditions:
    """_validate_task_preconditions() 基线校验测试。"""

    def setup_method(self) -> None:
        self.pipeline = MockIndexPipeline()
        self.valid_db = object()

    def test_p0_empty_case_id_raises_valueerror(self):
        """case_id 为空字符串应抛 ValueError，消息含 '不能为空'。"""
        with pytest.raises(ValueError, match="case_id 不能为空"):
            self.pipeline._validate_task_preconditions(
                "", "aabbccdd11223344aabbccdd11223344", self.valid_db  # type: ignore[arg-type]
            )

    def test_p0_empty_trace_id_raises_valueerror(self):
        """trace_id 为空字符串应抛 ValueError，消息含 '不能为空'。"""
        with pytest.raises(ValueError, match="trace_id 不能为空"):
            self.pipeline._validate_task_preconditions(
                VALID_UUID, "", self.valid_db  # type: ignore[arg-type]
            )

    def test_p0_none_db_session_raises_valueerror(self):
        """db_session=None 应抛 ValueError，消息含 '不能为 None'。"""
        with pytest.raises(ValueError, match="db_session 不能为 None"):
            self.pipeline._validate_task_preconditions(
                VALID_UUID, "aabbccdd11223344aabbccdd11223344", None  # type: ignore[arg-type]
            )

    def test_p0_both_case_id_and_trace_id_empty(self):
        """两个参数均为空 → 先检查 case_id，抛 case_id 相关错误。"""
        with pytest.raises(ValueError, match="case_id 不能为空"):
            self.pipeline._validate_task_preconditions(
                "", "", self.valid_db  # type: ignore[arg-type]
            )


# ============================================================================
# P1：边界值测试 — UUID 与 trace_id 格式
# ============================================================================


class TestValidInputBoundary:
    """合法输入的边界测试。"""

    def test_p1_valid_uuid_v4_passes_validation(self):
        """合法 UUID v4 字符串通过 _validate_case_id。"""
        service = MockIndexService()
        # 不应抛异常
        service._validate_case_id(VALID_UUID)  # type: ignore[arg-type]

    def test_p1_valid_uuid_without_dashes_passes(self):
        """无连字符的 32 位十六进制 UUID 也通过 uuid.UUID 解析。"""
        service = MockIndexService()
        # uuid.UUID('550e8400e29b41d4a716446655440000') 合法
        service._validate_case_id("550e8400e29b41d4a716446655440000")  # type: ignore[arg-type]

    def test_p1_valid_trace_id_with_length_32_passes(self):
        """32 位十六进制 trace_id 通过前置校验。"""
        pipeline = MockIndexPipeline()
        # 不应抛异常
        pipeline._validate_task_preconditions(
            VALID_UUID, "abcdef0123456789abcdef0123456789", object()  # type: ignore[arg-type]
        )

    def test_p1_trace_id_single_char_passes(self):
        """trace_id 仅检查非空，1 字符也合法。"""
        pipeline = MockIndexPipeline()
        # 不应抛异常——契约仅检查非空
        pipeline._validate_task_preconditions(
            VALID_UUID, "x", object()  # type: ignore[arg-type]
        )

    def test_p1_none_case_id_in_task_preconditions(self):
        """case_id=None（falsy）应通过 not case_id 检查抛 ValueError。"""
        pipeline = MockIndexPipeline()
        with pytest.raises(ValueError, match="case_id 不能为空"):
            pipeline._validate_task_preconditions(
                None, "valid_trace", object()  # type: ignore[arg-type]
            )


# ============================================================================
# P2：类型破坏测试 — NewType 无运行时强制
# ============================================================================


class TestTypeBreaking:
    """验证 NewType 在运行时是透明的，无额外校验。"""

    def test_p2_bare_str_passed_as_case_id_str_works(self):
        """传入裸 str 给期望 CaseIdStr 的参数——运行时透传，不抛异常。"""
        service = MockIndexService()
        # _validate_case_id 接收 CaseIdStr，但运行时 str 完全合法
        service._validate_case_id("550e8400-e29b-41d4-a716-446655440000")  # type: ignore[arg-type]

    def test_p2_bare_str_passed_as_trace_id_str_works(self):
        """传入裸 str 给期望 TraceIdStr 的参数——运行时透传。"""
        pipeline = MockIndexPipeline()
        pipeline._validate_task_preconditions(
            "550e8400-e29b-41d4-a716-446655440000",
            "abbacddc12344321abbacddc12344321",
            object(),
        )  # type: ignore[arg-type]

    def test_p2_list_instead_of_dict_enqueue_result(self):
        """传入 list 而非 dict 给 _validate_enqueue_result → RuntimeError。"""
        service = MockIndexService()
        with pytest.raises(RuntimeError, match="status"):
            service._validate_enqueue_result(["not", "a", "dict"])  # type: ignore[arg-type]


# ============================================================================
# P3：管线状态/时序测试 — enqueue() 与 manual_retry()
# ============================================================================


class TestEnqueueStateMachine:
    """enqueue() 状态机测试。"""

    @pytest.mark.asyncio
    async def test_p3_enqueue_with_approved_pending_status(self):
        """案例状态为 'approved_pending' → 入队成功，返回 status='enqueued'。"""
        service = MockIndexService(return_status="approved_pending")
        result = await service.enqueue(VALID_UUID, object())  # type: ignore[arg-type]
        assert result["status"] == "enqueued"

    @pytest.mark.asyncio
    async def test_p3_enqueue_with_already_indexed_status(self):
        """案例状态为 'already_indexed' → 幂等跳过，返回 status='already_indexed'。"""
        service = MockIndexService(return_status="already_indexed")
        result = await service.enqueue(VALID_UUID, object())  # type: ignore[arg-type]
        assert result["status"] == "already_indexed"

    @pytest.mark.asyncio
    async def test_p3_enqueue_with_already_queued_status(self):
        """案例状态为 'already_queued' → 幂等跳过，返回 status='already_queued'。"""
        service = MockIndexService(return_status="already_queued")
        result = await service.enqueue(VALID_UUID, object())  # type: ignore[arg-type]
        assert result["status"] == "already_queued"

    @pytest.mark.asyncio
    async def test_p3_enqueue_with_none_status_raises_valueerror(self):
        """案例状态为 None（不存在） → 抛 ValueError '不存在'。"""
        service = MockIndexService(return_status=None)
        with pytest.raises(ValueError, match="不存在"):
            await service.enqueue(VALID_UUID, object())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_p3_enqueue_with_unapproved_status_raises_valueerror(self):
        """案例状态非 approved_pending/queued/indexed → 抛 ValueError '未审核通过'。"""
        service = MockIndexService(return_status="draft")
        with pytest.raises(ValueError, match="未审核通过"):
            await service.enqueue(VALID_UUID, object())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_p3_enqueue_bad_result_triggers_validation(self):
        """_do_enqueue 返回不含 status 的 dict → _validate_enqueue_result 抛 RuntimeError。"""
        service = MockBadEnqueueService()
        # enqueue() 是 @final，会先调用 _validate_case_id（通过）→ _check_case_status（返回 approved_pending）
        # → _do_enqueue（返回 {"result": "ok"}）→ _validate_enqueue_result（失败）
        with pytest.raises(RuntimeError, match="status"):
            await service.enqueue(VALID_UUID, object())  # type: ignore[arg-type]


class TestManualRetry:
    """manual_retry() 状态测试。"""

    @pytest.mark.asyncio
    async def test_p3_manual_retry_with_failed_status(self):
        """index_status='failed' → 允许手动重试，返回 status='enqueued'。"""
        service = MockIndexService(return_status="failed")
        result = await service.manual_retry(VALID_UUID, object())  # type: ignore[arg-type]
        assert result["status"] == "enqueued"

    @pytest.mark.asyncio
    async def test_p3_manual_retry_with_non_failed_status_raises(self):
        """index_status 非 'failed' → 抛 ValueError '不允许手动重试'。"""
        service = MockIndexService(return_status="approved_pending")
        with pytest.raises(ValueError, match="不允许"):
            await service.manual_retry(VALID_UUID, object())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_p3_manual_retry_none_case_raises_valueerror(self):
        """案例不存在时 manual_retry 抛 ValueError（先检查状态）。"""
        service = MockIndexService(return_status=None)
        with pytest.raises(ValueError, match="不存在"):
            await service.manual_retry(VALID_UUID, object())  # type: ignore[arg-type]


# ============================================================================
# P3：管线 process_task() 集成测试
# ============================================================================


class TestProcessTaskIntegration:
    """process_task() @final 管线集成测试。"""

    def _valid_params(self):
        return (
            VALID_UUID,
            "aabbccdd11223344aabbccdd11223344",
            object(),
        )

    @pytest.mark.asyncio
    async def test_p3_process_task_success_marks_indexed(self):
        """全管线成功 → 调用 _do_mark_indexed。"""
        pipeline = MockIndexPipeline()
        case_id, trace_id, db = self._valid_params()
        await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        assert len(pipeline._marked_indexed_calls) == 1
        assert len(pipeline._marked_failed_calls) == 0

    @pytest.mark.asyncio
    async def test_p3_process_task_cas_conflict_skips(self):
        """CAS 更新 status→processing 失败 → 直接跳过，不执行后续步骤。"""
        pipeline = MockIndexPipeline()
        pipeline._status_processing_result = False
        case_id, trace_id, db = self._valid_params()
        await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        # 不应标记 indexed，不应读取案例数据
        assert len(pipeline._marked_indexed_calls) == 0
        assert len(pipeline._marked_failed_calls) == 0

    @pytest.mark.asyncio
    async def test_p3_process_task_read_case_none_marks_failed(self):
        """案例数据读取返回 None → mark_failed，不继续后续步骤。"""
        pipeline = MockIndexPipeline()
        pipeline._case_data = None  # 模拟行不存在
        case_id, trace_id, db = self._valid_params()
        await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        assert len(pipeline._marked_failed_calls) == 1
        assert pipeline._marked_failed_calls[0]["phase"] == "read_case"
        assert len(pipeline._marked_indexed_calls) == 0

    @pytest.mark.asyncio
    async def test_p3_process_task_build_chunk_error_marks_failed(self):
        """_do_build_chunk 抛异常 → mark_failed，phase='build_chunk_text'。"""
        pipeline = MockIndexPipeline()
        pipeline.fail_on("build", "四段式字段不完整")
        case_id, trace_id, db = self._valid_params()
        await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        assert len(pipeline._marked_failed_calls) == 1
        assert pipeline._marked_failed_calls[0]["phase"] == "build_chunk_text"
        assert "四段式字段不完整" in pipeline._marked_failed_calls[0]["error"]

    @pytest.mark.asyncio
    async def test_p3_process_task_embed_error_marks_failed(self):
        """嵌入服务调用失败 → mark_failed，phase='generate_embedding'。"""
        pipeline = MockIndexPipeline()
        pipeline.fail_on("embed", "API 限流")
        case_id, trace_id, db = self._valid_params()
        await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        assert len(pipeline._marked_failed_calls) == 1
        assert pipeline._marked_failed_calls[0]["phase"] == "generate_embedding"

    @pytest.mark.asyncio
    async def test_p3_process_task_write_error_marks_failed(self):
        """pgvector 写入失败 → mark_failed，phase='write_index'。"""
        pipeline = MockIndexPipeline()
        pipeline.fail_on("write", "磁盘满")
        case_id, trace_id, db = self._valid_params()
        await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        assert len(pipeline._marked_failed_calls) == 1
        assert pipeline._marked_failed_calls[0]["phase"] == "write_index"

    @pytest.mark.asyncio
    async def test_p3_process_task_mark_indexed_error_propagates(self):
        """_do_mark_indexed 抛异常 → 异常向上传播（契约未在此步骤包裹 try/except）。
        这意味着 mark_indexed 阶段的失败不会被 _do_mark_failed 捕获，
        而是直接传播给调用方。"""
        pipeline = MockIndexPipeline()
        pipeline.fail_on("mark_indexed", "CAS 冲突")
        case_id, trace_id, db = self._valid_params()
        with pytest.raises(RuntimeError, match="CAS 冲突"):
            await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        # 异常直接传播，_do_mark_failed 未被调用
        assert len(pipeline._marked_failed_calls) == 0

    @pytest.mark.asyncio
    async def test_p3_process_task_build_chunk_does_not_swallow(self):
        """管线任一步骤失败，不应静默吞掉异常——应调用 _do_mark_failed。"""
        pipeline = MockIndexPipeline()
        pipeline.fail_on("build", "敏感信息检测到 PII")
        case_id, trace_id, db = self._valid_params()
        await pipeline.process_task(case_id, trace_id, db)  # type: ignore[arg-type]
        # 应记录了失败，而不是静默返回成功
        assert len(pipeline._marked_failed_calls) == 1

    def test_p3_validate_task_postconditions_noop(self):
        """_validate_task_postconditions 基线实现为空，不抛异常。"""
        pipeline = MockIndexPipeline()
        # 不应抛异常
        pipeline._validate_task_postconditions("any_case_id")  # type: ignore[arg-type]

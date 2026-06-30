"""应急咨询链路诊断脚本。

模拟 JsonSectionTracker 对各类 LLM 输出的解析能力，
以及端到端 stream_generate 流程。
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

# ============================================================================
# 步骤 1: 测试 JsonSectionTracker 对各种格式的解析
# ============================================================================


def test_tracker():
    """测试 tracker 对不同 LLM 输出格式的解析能力。"""
    from app.services.emergency_plan_generation.streaming import JsonSectionTracker

    test_cases = {
        "标准 JSON": json.dumps(
            {
                "即时安全干预动作": ["措施1 [1]", "措施2"],
                "情绪安抚话术": ["话术1", "话术2"],
                "后续观察指标": ["指标1", "指标2"],
                "就医判断标准": ["标准1", "标准2"],
            },
            ensure_ascii=False,
        ),
        "Markdown 包裹 (```json)": "好的，以下是方案：\n```json\n"
        + json.dumps(
            {
                "即时安全干预动作": ["措施1 [1]", "措施2"],
                "情绪安抚话术": ["话术1", "话术2"],
                "后续观察指标": ["指标1", "指标2"],
                "就医判断标准": ["标准1", "标准2"],
            },
            ensure_ascii=False,
        )
        + "\n```\n以上建议仅供参考。",
        "前缀说明 + JSON": "以下是您需要的应急方案，请查收：\n"
        + json.dumps(
            {
                "即时安全干预动作": ["措施1", "措施2"],
                "情绪安抚话术": ["话术1", "话术2"],
                "后续观察指标": ["指标1", "指标2"],
                "就医判断标准": ["标准1", "标准2"],
            },
            ensure_ascii=False,
        ),
        "Markdown bold keys": '{"即时安全干预动作":["正常"],"情绪安抚话术":["正常"],"后续观察指标":["正常"],"就医判断标准":["正常"]}',
        "英文 keys": '{"immediate_action":["test"],"calming_words":["test"],"observation":["test"],"medical_criteria":["test"]}',
        "空 JSON": "{}",
        "纯文本 (无 JSON)": "抱歉，我无法生成方案。请提供更多信息。",
    }

    for name, sample in test_cases.items():
        tracker = JsonSectionTracker()
        fragments = tracker.feed(sample)

        section_chars = {}
        for section, text in fragments:
            if section:
                section_chars[section] = section_chars.get(section, 0) + len(text)

        total_yield_chars = sum(section_chars.values())
        status = "OK" if total_yield_chars > 0 else "零产出!"
        print(
            f"[{status}] {name}: {len(fragments)} fragments, {total_yield_chars} content chars, sections={list(section_chars.keys())}"
        )


# ============================================================================
# 步骤 2: 端到端 stream_generate 模拟
# ============================================================================


class MockChunk:
    def __init__(self, content: str):
        self.choices = [MockChoice(content)]


class MockChoice:
    def __init__(self, content: str):
        self.delta = MockDelta(content)


class MockDelta:
    def __init__(self, content: str):
        self.content = content


class MockLLMClient:
    """模拟 LLMClient，返回预定义的 JSON 响应。"""

    def __init__(self, response_text: str):
        self._text = response_text

    async def async_chat_stream(self, **kwargs) -> AsyncGenerator:
        # 模拟流式：将响应分成多个 chunk
        chunk_size = 10
        for i in range(0, len(self._text), chunk_size):
            yield MockChunk(self._text[i : i + chunk_size])


async def test_stream_generate(response_text: str, label: str):
    """用模拟 LLM 客户端测试 stream_generate。"""
    from app.services.crisis_judgment.enums import CrisisLevel
    from app.services.crisis_judgment.models import (
        CrisisJudgmentResult,
        JudgmentLayerResult,
    )
    from app.services.emergency_plan_generation.models import EmergencyPlanInput
    from app.services.emergency_plan_generation.streaming import stream_generate
    from py_schemas.consult import SemanticSearchResult

    mock_crisis = CrisisJudgmentResult.model_construct(
        final_level=CrisisLevel.MILD,
        block_deep_response=False,
        judgment_sources=[JudgmentLayerResult.model_construct(layer_name="mock", level=CrisisLevel.MILD)],
    )
    mock_search = SemanticSearchResult.model_construct(
        results=[],
        degradation_applied=False,
    )

    mock_input = EmergencyPlanInput.model_construct(
        crisis_result=mock_crisis,
        search_result=mock_search,
        profile_summary="测试档案",
        behavior_description="测试行为描述",
        request_id="test-123",
    )

    mock_llm = MockLLMClient(response_text)
    messages = [
        {"role": "system", "content": "测试 system prompt"},
        {"role": "user", "content": "测试 user message"},
    ]

    chunks = []
    try:
        async for chunk in stream_generate(
            input_data=mock_input,
            messages=messages,
            prenumbered_slices=[],
            llm_client=mock_llm,
        ):
            if not chunk.is_final:
                chunks.append(chunk)
    except Exception as exc:
        print(f"  [{label}] 异常: {type(exc).__name__}: {exc}")
        return

    content_total = sum(len(c.text) for c in chunks)
    print(
        f"  [{label}]: {len(chunks)} content chunks, {content_total} total chars, finish={chunk.finish_reason if 'chunk' in dir() else 'N/A'}"
    )


async def main():
    print("=" * 60)
    print("步骤 1: JsonSectionTracker 格式兼容性")
    print("=" * 60)
    test_tracker()

    print()
    print("=" * 60)
    print("步骤 2: stream_generate 端到端模拟")
    print("=" * 60)

    standard_json = json.dumps(
        {
            "即时安全干预动作": ["措施1 [1]", "措施2"],
            "情绪安抚话术": ["话术1", "话术2"],
            "后续观察指标": ["指标1", "指标2"],
            "就医判断标准": ["标准1", "标准2"],
        },
        ensure_ascii=False,
    )

    # 场景 A: 标准 JSON
    await test_stream_generate(standard_json, "标准 JSON")

    # 场景 B: Markdown 包裹
    markdown_text = "好的，以下是应急方案：\n```json\n" + standard_json + "\n```\n以上建议仅供参考。"
    await test_stream_generate(markdown_text, "Markdown 包裹")

    # 场景 C: 前缀 + JSON
    await test_stream_generate("以下是您的应急方案：" + standard_json, "前缀说明 + JSON")

    print()
    print("=" * 60)
    print("结论")
    print("=" * 60)
    print("如果标准 JSON 通过但 markdown 包裹不通过 → 需要加固 Prompt 或增强 tracker 容错")
    print("如果全部不通过 → LLM API 本身有问题（检查 API key / 网络 / 模型名）")


if __name__ == "__main__":
    asyncio.run(main())

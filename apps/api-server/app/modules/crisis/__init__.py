"""app.modules.crisis — 红线安全门 + 此刻安全层（ADR-008/009 目标态）。

组件：
- RedlineGate: 二元红线判定（纯规则零 LLM，桶分流/关键词/否定过滤/档案叠加）
- SafetyLayer: 此刻安全层（卡供给回退链/阶段状态机/分流/走失流程）
- CrisisService: 对外编排（词库加载 + 事件落库）
- slot_filler: 安全卡槽位填充（S4 档案数据源接口先行）
"""

from app.modules.crisis.keywords import DEFAULT_KEYWORDS, load_redline_keywords
from app.modules.crisis.redline_event import record_redline_event
from app.modules.crisis.redline_gate import RedlineGate
from app.modules.crisis.safety_layer import SafetyLayer
from app.modules.crisis.service import CrisisService
from app.modules.crisis.slot_filler import ProfileSnapshot, ProfileSnapshotProvider, fill_slots

__all__ = [
    "RedlineGate",
    "SafetyLayer",
    "CrisisService",
    "ProfileSnapshot",
    "ProfileSnapshotProvider",
    "fill_slots",
    "load_redline_keywords",
    "DEFAULT_KEYWORDS",
    "record_redline_event",
]

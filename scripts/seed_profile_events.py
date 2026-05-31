"""为指定 profile 插入模拟事件记录。

用法:
    python scripts/seed_profile_events.py
    python scripts/seed_profile_events.py --profile-id <uuid>

独立脚本，仅依赖 asyncpg。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone


def _load_database_url() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in (".env", ".env.example"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^\s*DATABASE_URL\s*=\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip()
    return "postgresql+asyncpg://campfire:changeme@localhost:5432/campfire"


# ---------------------------------------------------------------------------
# 模拟事件数据
# ---------------------------------------------------------------------------

TARGET_PROFILE_ID = "aff97691-1aae-403c-b4dd-4344c0864aff"
RECORDED_BY = "00000000-0000-0000-0000-000000000001"  # 虚拟家长用户

NOW = datetime.now(timezone.utc)

MOCK_EVENTS = [
    {
        "days_ago": 1,
        "behavior_type": "情绪崩溃",
        "severity_level": "重",
        "setting": "家庭",
        "trigger_description": "晚饭时 iPad 没电自动关机，孩子正在看的动画片突然中断",
        "manifestation": "大声尖叫持续约15分钟，摔碗筷，反复拍打桌面，拒绝任何语言安抚。期间试图用手机替代但被推开。",
        "intervention_tried": "先移除周围危险物品（碗筷），保持冷静等待情绪高峰过去，约10分钟后尝试用拥抱安抚",
        "intervention_result": "拥抱后逐渐平静，后来自发去拿绘本翻看，情绪完全平复用时约20分钟",
        "is_professional": False,
        "tags": ["电子产品", "情绪爆发"],
    },
    {
        "days_ago": 3,
        "behavior_type": "刻板行为",
        "severity_level": "中",
        "setting": "家庭",
        "trigger_description": "客厅玩具收纳顺序被打乱，奶奶打扫时挪动了积木位置",
        "manifestation": "发现后立即将全部积木倒出，按颜色从浅到深重新排列，重复约40分钟，期间不允许任何人靠近",
        "intervention_tried": "不打断其排列行为，事后用社交故事讲解'整理前先问一问'的规则",
        "intervention_result": "听完故事后点头表示明白，后续两天奶奶打扫前先打招呼，未再触发",
        "is_professional": False,
        "tags": ["秩序敏感", "社交故事"],
    },
    {
        "days_ago": 5,
        "behavior_type": "社交退缩",
        "severity_level": "轻",
        "setting": "公共场合",
        "trigger_description": "小区游乐场来了3个不认识的小朋友，声音嘈杂",
        "manifestation": "躲在滑梯后面约5分钟，拒绝与小朋友互动，小声自言自语重复动画片台词",
        "intervention_tried": "不强迫社交，带他到安静的长椅区坐着，给他喜欢的触觉玩具（橡皮泥）",
        "intervention_result": "10分钟后主动说'想回家了'，回家后情绪稳定，晚上主动聊起游乐场看到的小朋友",
        "is_professional": False,
        "tags": ["社交焦虑"],
    },
    {
        "days_ago": 7,
        "behavior_type": "自伤行为",
        "severity_level": "重",
        "setting": "家庭",
        "trigger_description": "作业本上写错字被指出，要求擦掉重写",
        "manifestation": "突然用力拍打自己额头和前额，约5-6下，伴有'我笨，我做不好'的自语。额头出现轻微红印。",
        "intervention_tried": "立即轻握手腕阻止拍打动作，降低语调说'没关系我们先休息一下'，转移注意去喝果汁",
        "intervention_result": "停止自伤行为，喝果汁后平静。当晚用社交故事讨论'犯错没关系'，第二天写作业遇到错误未再发作",
        "is_professional": True,
        "tags": ["自伤", "学业压力"],
    },
    {
        "days_ago": 10,
        "behavior_type": "攻击行为",
        "severity_level": "中",
        "setting": "学校",
        "trigger_description": "课间同桌未经同意拿了他的橡皮，且未及时归还",
        "manifestation": "推搡同桌肩膀两下，大声说'还给我'，被老师制止后哭闹约5分钟",
        "intervention_tried": "老师介入分开两人，安抚情绪后引导用语言表达'请把我的橡皮还给我'，同桌道歉归还",
        "intervention_result": "情绪平复后向同桌说了'对不起'，老师当天在家校联系本上记录此事件",
        "is_professional": False,
        "tags": ["同伴冲突"],
    },
    {
        "days_ago": 14,
        "behavior_type": "情绪崩溃",
        "severity_level": "重",
        "setting": "公共场合",
        "trigger_description": "超市收银台排队时等待超过5分钟，人多嘈杂",
        "manifestation": "蹲在地上捂着耳朵，随后大声尖叫，拉扯家长衣服要求'现在就走'，引来周围顾客注视",
        "intervention_tried": "一人留下结账，另一人立即带孩子到超市外面安静区域，给降噪耳机戴上",
        "intervention_result": "离开嘈杂环境后约3分钟停止尖叫，戴上耳机后逐步安静，之后全程保持平静",
        "is_professional": False,
        "tags": ["感官过载", "公共场所"],
    },
    {
        "days_ago": 18,
        "behavior_type": "刻板行为",
        "severity_level": "轻",
        "setting": "家庭",
        "trigger_description": "周末早晨，未发现明显外在触发因素",
        "manifestation": "反复摇晃身体约20分钟，一边摇晃一边哼唱同一段旋律，眼神放空",
        "intervention_tried": "未直接干预，在旁安静陪伴，摇晃自行停止后邀请一起准备早餐",
        "intervention_result": "自行停止后参与早餐准备，情绪正常，当天其余时间未再出现长时间摇晃",
        "is_professional": False,
        "tags": ["自我刺激"],
    },
    {
        "days_ago": 21,
        "behavior_type": "多动",
        "severity_level": "中",
        "setting": "机构",
        "trigger_description": "机构感统训练课，课程内容为前庭觉刺激（秋千+旋转）",
        "manifestation": "在秋千上不停扭动无法安静，要求下来后又反复要求上去，无法完成训练师设定的10分钟连续任务",
        "intervention_tried": "训练师调整为短时多次模式（每次3分钟+休息2分钟），配合深压觉输入（负重背心）",
        "intervention_result": "调整后能配合完成训练，后期评估显示前庭觉需求有所降低",
        "is_professional": True,
        "tags": ["感统", "注意力"],
    },
    {
        "days_ago": 25,
        "behavior_type": "社交退缩",
        "severity_level": "轻",
        "setting": "学校",
        "trigger_description": "班级自由活动时间，同学在玩集体游戏（老鹰抓小鸡）",
        "manifestation": "独自坐在教室角落画画，拒绝参与集体游戏，对同学邀请摇头不语",
        "intervention_tried": "老师安排一个性格温和的同桌在旁边陪他画画，不强迫参与游戏",
        "intervention_result": "和同桌一起画画约20分钟，期间有简单交流（颜色选择），未出现焦虑",
        "is_professional": False,
        "tags": ["同伴互动"],
    },
    {
        "days_ago": 28,
        "behavior_type": "自伤行为",
        "severity_level": "中",
        "setting": "家庭",
        "trigger_description": "洗澡时水温比平常稍热（家人忘记调温），孩子不会表达不适",
        "manifestation": "用手抓挠自己手臂，留下浅红色划痕，哭喊但不指认问题所在",
        "intervention_tried": "立即检查水温并调凉，用冷毛巾敷手臂，轻声安抚'没关系，已经调好了'",
        "intervention_result": "水温适宜后停止抓挠，后续洗澡前会先让孩子用手试水温并点头确认",
        "is_professional": False,
        "tags": ["感官不适", "表达障碍"],
    },
]

_INSERT_EVENT = """
    INSERT INTO event_logs (
        event_id, profile_id, recorded_by, recorded_by_role,
        event_time, behavior_type, severity_level, setting,
        trigger_description, manifestation,
        intervention_tried, intervention_result,
        is_professional, tags, created_at, updated_at
    ) VALUES (
        $1, $2, $3, 'parent',
        $4, $5, $6, $7,
        $8, $9,
        $10, $11,
        $12, $13, $14, $14
    )
"""


async def seed_events(profile_id: str) -> None:
    import asyncpg

    raw = _load_database_url()
    pg_url = raw.replace("+asyncpg", "")
    conn = await asyncpg.connect(pg_url)

    try:
        # 验证 profile 存在
        row = await conn.fetchrow(
            "SELECT profile_id, nickname FROM profiles WHERE profile_id = $1",
            profile_id,
        )
        if not row:
            print(f"ERROR: profile {profile_id} 不存在", file=sys.stderr)
            sys.exit(1)
        print(f"目标档案: {row['nickname'] or '未命名'} ({row['profile_id']})")

        now = datetime.now(timezone.utc)
        inserted = 0

        for ev in MOCK_EVENTS:
            event_id = uuid.uuid4()
            event_time = now - timedelta(days=ev["days_ago"], hours=2)
            await conn.execute(
                _INSERT_EVENT,
                event_id,
                profile_id,
                RECORDED_BY,
                event_time,
                ev["behavior_type"],
                ev["severity_level"],
                ev["setting"],
                ev["trigger_description"],
                ev["manifestation"],
                ev["intervention_tried"],
                ev["intervention_result"],
                ev["is_professional"],
                json.dumps(ev["tags"], ensure_ascii=False),
                now,
            )
            print(f"  [OK] {ev['behavior_type']} | {ev['severity_level']} | {ev['days_ago']}天前")
            inserted += 1

        print(f"\n完成: 已插入 {inserted} 条事件记录 -> profile_id={profile_id}")

    finally:
        await conn.close()


def main() -> None:
    profile_id = sys.argv[1] if len(sys.argv) > 1 else TARGET_PROFILE_ID
    asyncio.run(seed_events(profile_id))


if __name__ == "__main__":
    main()

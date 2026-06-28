#!/usr/bin/env python3
# =============================================================================
# Campfire-AI 种子案例导入脚本
#
# 用途：
#   - 为 RAG 检索和应急咨询演示导入一批结构化种子案例
#   - 支持直接生成向量索引（默认）或仅投递到 Redis 队列
#
# 运行方式：
#   # 直接生成向量索引（推荐，最可靠）
#   uv run python scripts/seed_cases.py
#
#   # 仅投递到 Redis 队列，由 Worker 异步处理
#   uv run python scripts/seed_cases.py --enqueue
#
#   # 先清空已有种子数据，再导入
#   uv run python scripts/seed_cases.py --clear
#
# 前置条件：
#   - 数据库已迁移（alembic upgrade head）
#   - .env 中 DATABASE_URL、REDIS_URL（如 --enqueue）、DASHSCOPE_API_KEY 已配置
# =============================================================================

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 将项目根目录加入路径，确保能导入 workspace packages
sys.path.insert(0, str(__file__).replace("\\", "/").rsplit("/scripts/", 1)[0])

from py_config import get_settings
from py_db.models.case_card import CaseCard
from py_db.models.case_narrative import CaseNarrative
from py_db.models.case_chunks import CaseChunk
from py_rag.embedding import _get_encoder
from py_rag.indexing import IndexPipeline
from py_rag.indexing.chunk_builder import build_chunk_text
from py_rag.indexing.index_writer import write_index_to_pgvector
from py_rag.indexing.service import enqueue_index_task
from py_rag.types import CaseIdStr
from py_logger import logger


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SEED_AUTHOR_ID = "seed-script"
SEED_SOURCE_TYPE = "专家撰写"


# ---------------------------------------------------------------------------
# 种子案例数据
# ---------------------------------------------------------------------------

SEED_CASES: list[dict[str, Any]] = [
    {
        "title": "商场突然捂耳朵蹲下尖叫——感觉过载应对",
        "narrative": (
            "7岁男孩乐乐在商场自动扶梯附近突然停下，双手捂住耳朵，蹲下身体开始尖叫。"
            "妈妈注意到商场背景音乐声和广播声同时响起，立即带他走到商场外的安静角落。"
            "妈妈蹲下来用平稳的语气说：\"这里有点吵，我们去安静的地方。\"并用手掌轻轻按压他的肩膀。"
            "约3分钟后尖叫停止，乐乐开始深呼吸。之后妈妈带他到车里休息，给他戴上降噪耳机。"
            "后续一周，家人外出时都会随身携带降噪耳机，并在进入嘈杂场所前提前告知孩子。"
        ),
        "behavior_type": "情绪崩溃",
        "age_range": [4, 10],
        "severity": "中度",
        "scene": "公共场合",
        "ebp_labels": ["前因干预(ABI)", "视觉支持(VS)", "感觉统合(Sensory Integration)"],
        "family_category": "环境调整",
        "immediate_action": (
            "1. 立即将孩子带离嘈杂环境，转移到安静、人少的地方。\n"
            "2. 蹲下与孩子保持同一高度，避免俯视带来的压迫感。\n"
            "3. 使用稳定、缓慢的语速告知当前正在发生什么，如\"我们离开这里，去安静的地方\"。\n"
            "4. 提供可预测的物理按压（如肩膀轻压）或深压拥抱，如果孩子接受。\n"
            "5. 拿出随身准备的降噪耳机或耳塞，帮助孩子降低听觉输入。"
        ),
        "comforting_phrase": (
            "\"这里太吵了，你的耳朵很累。我们走，去一个安静的地方。\""
            "\"妈妈在这里，我们一起慢慢呼吸。\""
        ),
        "observation_metrics": (
            "1. 尖叫持续时长是否缩短（目标：5分钟内停止）。\n"
            "2. 孩子是否能在提示下使用降噪耳机或指认\"太吵了\"。\n"
            "3. 进入嘈杂环境前，是否接受提前提醒并配合准备耳机。"
        ),
        "medical_criteria": (
            "1. 崩溃持续超过30分钟无法安抚。\n"
            "2. 出现自伤、撞头等危险行为且无法制止。\n"
            "3. 崩溃后孩子出现意识模糊、呕吐或异常嗜睡。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "不要在孩子情绪高峰时强行拉拽或大声训斥，避免加剧感觉过载。",
        "contraindications": "如果孩子对触碰高度敏感，避免强行身体接触。",
    },
    {
        "title": "幼儿园排队时被推倒后的攻击行为干预",
        "narrative": (
            "5岁的豆豆在幼儿园排队洗手时被后面的小朋友推倒，他立刻转身用手拍打对方，"
            "并发出愤怒的喊声。老师迅速站在两个孩子中间，用身体隔开距离，同时平静地说："
            "\"我知道你很生气，但不可以打人。\"随后老师带豆豆到旁边的情绪角，给他一张"
            "\"生气卡\"，并教他指认卡片表达情绪。5分钟后豆豆平静下来，老师引导他用语言"
            "表达\"他推我，我不开心\"。下午老师与另一位小朋友沟通，了解到推人是因为着急，"
            "并安排两人第二天一起完成一个小任务。"
        ),
        "behavior_type": "攻击",
        "age_range": [3, 7],
        "severity": "中度",
        "scene": "学校",
        "ebp_labels": ["辅助替代沟通(AAC)", "功能沟通训练(FCT)", "视觉支持(VS)"],
        "family_category": "沟通替代",
        "immediate_action": (
            "1. 立即用身体温和地隔开冲突双方，保护所有孩子安全。\n"
            "2. 用简短语句命名情绪：\"你生气了。\"\n"
            "3. 提供可替代的表达方式，如情绪卡片、手势或简单语句：\"我不开心\"。\n"
            "4. 将孩子转移到安静角落，降低环境刺激。\n"
            "5. 等情绪平复后，示范并练习正确的表达句式。"
        ),
        "comforting_phrase": (
            "\"你被推了，很生气。我们可以这样说：不要推我。\""
            "\"打人会让别人疼，我们可以指这张生气的卡片。\""
        ),
        "observation_metrics": (
            "1. 情绪平复所需时间是否缩短。\n"
            "2. 一周内攻击行为发生频率是否下降。\n"
            "3. 孩子能否在提示下使用替代沟通方式表达不满。"
        ),
        "medical_criteria": (
            "1. 攻击行为导致他人受伤需要医疗处理。\n"
            "2. 孩子持续出现无法安抚的攻击冲动，影响正常入园。\n"
            "3. 伴随自伤或破坏贵重物品行为。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "避免在情绪高峰时讲道理或惩罚，应先处理情绪再处理行为。",
        "contraindications": "如果孩子处于极度激动状态，不要强制要求道歉或互动。",
    },
    {
        "title": "晚餐时反复敲击餐具的刻板行为处理",
        "narrative": (
            "9岁的天天在晚餐时不断用筷子敲击碗沿，发出连续声响，家人无法继续吃饭。"
            "爸爸观察到天天在看电视广告时开始这个动作，判断可能是视觉-听觉刺激需求。"
            "他没有大声制止，而是把电视音量调低，然后在天天手边放了一块有纹理的减压垫，"
            "并说：\"如果你想敲，可以敲这个垫子。\"同时给天天一个明确的用餐计时器，"
            "设定15分钟。几天后，天天在餐桌上敲击餐具的频率明显减少，开始用减压垫替代。"
        ),
        "behavior_type": "刻板",
        "age_range": [6, 12],
        "severity": "轻度",
        "scene": "家庭",
        "ebp_labels": ["感觉统合(Sensory Integration)", "差别强化(DR)", "视觉支持(VS)"],
        "family_category": "自我管理",
        "immediate_action": (
            "1. 降低环境中可能触发刻板行为的刺激源（如调低电视音量）。\n"
            "2. 提供一个功能相同的替代物品，如减压垫、咀嚼棒或可以敲击的软垫。\n"
            "3. 用平静的语言告诉孩子替代行为：\"想敲的话，敲这个。\"\n"
            "4. 设置可视化计时器，明确用餐或活动时间边界。\n"
            "5. 当孩子使用替代物品时，给予具体表扬。"
        ),
        "comforting_phrase": (
            "\"你想敲东西，没问题，我们敲这个垫子。\""
            "\"计时器响了之后我们再一起做你喜欢的事。\""
        ),
        "observation_metrics": (
            "1. 每餐敲击餐具次数是否减少。\n"
            "2. 孩子主动使用替代物品的频率。\n"
            "3. 用餐时间是否能在计时器范围内完成。"
        ),
        "medical_criteria": (
            "1. 刻板行为导致无法进食或睡眠严重不足。\n"
            "2. 刻板行为伴随自伤或伤害他人。\n"
            "3. 刻板行为频率急剧增加，影响日常基本生活。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "不要强行制止刻板行为而不提供替代方案，可能引发情绪爆发。",
        "contraindications": "如果孩子对替代物品完全拒绝，不要强迫使用。",
    },
    {
        "title": "社区花园中试图跑向马路的逃跑行为应对",
        "narrative": (
            "6岁的童童在社区花园玩耍时，突然挣脱奶奶的手向马路方向跑去。"
            "奶奶迅速追上并拉住他的手腕，同时用身体挡住去向。童童开始哭闹并试图挣脱。"
            "奶奶没有责骂，而是蹲下来抱住他说：\"马路上有车，危险。\"等童童稍微平静后，"
            "她带他到花园内的沙坑区，并拿出一辆他喜欢的玩具车作为转移注意。"
            "之后奶奶在社区花园选择靠近内侧的长椅休息，并始终让童童在自己的视线范围内。"
        ),
        "behavior_type": "逃跑",
        "age_range": [3, 8],
        "severity": "重度",
        "scene": "公共场合",
        "ebp_labels": ["反应中断/重定向(RIR)", "前因干预(ABI)", "反应中断/重定向(RIR)"],
        "family_category": "反应中断/重定向(RIR)",
        "immediate_action": (
            "1. 第一时间制止逃跑行为，用身体阻挡危险方向，确保孩子远离车辆、水域等危险区域。\n"
            "2. 保持冷静，用简短语句告知危险：\"有车，危险，停下来。\"\n"
            "3. 将孩子转移到安全区域，降低身体约束，改为稳定陪伴。\n"
            "4. 提供孩子喜欢的物品或活动转移注意力，帮助情绪平复。\n"
            "5. 复盘环境：选择远离道路、人流较少的活动位置。"
        ),
        "comforting_phrase": (
            "\"马路有车，我们不能过去。妈妈/奶奶会保护你。\""
            "\"我们在这里玩沙子，安全。\""
        ),
        "observation_metrics": (
            "1. 外出时孩子是否能在提示下牵住大人的手。\n"
            "2. 逃跑企图发生频率是否下降。\n"
            "3. 孩子是否能识别\"危险\"相关的视觉提示（如停车标志、红灯）。"
        ),
        "medical_criteria": (
            "1. 逃跑行为导致交通事故或严重外伤。\n"
            "2. 孩子持续无视安全边界，反复冲向危险区域。\n"
            "3. 伴随严重情绪崩溃，无法在任何户外环境中保持安全。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "在公共场合务必保持一臂之内的近距离，避免让孩子处于无遮挡的开阔区域。",
        "contraindications": "不要通过恐吓或惩罚来阻止逃跑行为，应通过环境调整和能力训练解决。",
    },
    {
        "title": "睡前咬手腕的自我伤害行为干预",
        "narrative": (
            "10岁的果果每天晚上入睡前会用力咬自己的手腕，留下齿痕。妈妈发现这通常发生"
            "在睡前30分钟，当天活动安排较满或屏幕时间较长时更明显。她与医生沟通后，"
            "在睡前1小时建立固定的放松流程：温水泡脚10分钟、听白噪音、做5次深呼吸。"
            "同时给果果一个咬咬胶替代品，并教他感到紧张时捏压力球。两周后，"
            "咬手腕的频率从每天减少到每周1-2次，齿痕也逐渐消失。"
        ),
        "behavior_type": "自伤",
        "age_range": [6, 14],
        "severity": "重度",
        "scene": "家庭",
        "ebp_labels": ["感觉统合(Sensory Integration)", "自我管理", "差别强化(DR)"],
        "family_category": "反应中断/重定向(RIR)",
        "immediate_action": (
            "1. 立即用柔软的咬合替代物（咬咬胶、咀嚼项链）放在孩子嘴边，引导转移咬合力。\n"
            "2. 温柔但坚定地握住孩子的手腕，说：\"不要咬自己，会疼。咬这个。\"\n"
            "3. 降低环境刺激，调暗灯光，减少屏幕和噪音。\n"
            "4. 建立固定的睡前放松流程，如泡脚、深呼吸、白噪音。\n"
            "5. 记录发生时间和前因，寻找可预测触发因素。"
        ),
        "comforting_phrase": (
            "\"我知道你现在很难受，我们不要伤害自己。\""
            "\"我们一起捏这个球，慢慢呼吸。\""
        ),
        "observation_metrics": (
            "1. 每日自伤行为发生次数是否减少。\n"
            "2. 手腕伤口愈合情况。\n"
            "3. 孩子能否在情绪紧张时主动使用替代物品。"
        ),
        "medical_criteria": (
            "1. 自伤导致破皮、出血、感染或疤痕。\n"
            "2. 自伤行为频率增加或强度加重。\n"
            "3. 伴随拒绝进食、睡眠严重紊乱或情绪低落，需尽快就医。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "自伤行为可能提示感觉需求或情绪调节困难，建议同时咨询作业治疗师或心理医生。",
        "contraindications": "不要严厉惩罚或羞辱自伤行为，也不要忽视可能的身体伤害。",
    },
    {
        "title": "课间独自坐在角落的社交退缩引导",
        "narrative": (
            "8岁的小雨在新学期开始后，每到大课间都独自坐在教室角落，不参与同学游戏。"
            "班主任没有强制他加入，而是先观察他喜欢看的绘本主题，然后安排一名性格温和的"
            "同学坐在他旁边一起看同一本书。几天后，老师邀请小雨和这名同学一起完成一个"
            "两人合作的手工任务，任务简单且有小雨熟悉的步骤。一周后，小雨开始在课间"
            "主动拿起绘本坐在同学附近，偶尔用简短语句回应同学的提问。"
        ),
        "behavior_type": "其他",
        "age_range": [6, 12],
        "severity": "轻度",
        "scene": "学校",
        "ebp_labels": ["自然主义干预(NI)", "同伴教学(PBI)", "社交技能训练(SST)"],
        "family_category": "社交引导",
        "immediate_action": (
            "1. 不要强迫孩子立即加入集体，先尊重他当前的安全行为。\n"
            "2. 识别孩子感兴趣的活动或物品，作为社交切入点。\n"
            "3. 安排一名温和、耐心的同伴进行低压力并行活动。\n"
            "4. 设计简单的合作任务，让孩子在熟悉步骤中自然互动。\n"
            "5. 及时表扬孩子的任何社交尝试，即使只是靠近或眼神接触。"
        ),
        "comforting_phrase": (
            "\"你可以先在这里看书，小明也在这边看。\""
            "\"你刚才看了他的书，做得很好。\""
        ),
        "observation_metrics": (
            "1. 课间是否愿意停留在有同伴的区域。\n"
            "2. 一周内主动与同伴互动（语言/手势/分享）的次数。\n"
            "3. 对合作任务的参与度是否提高。"
        ),
        "medical_criteria": (
            "1. 社交退缩伴随持续情绪低落、哭泣或拒绝上学。\n"
            "2. 完全拒绝与任何成人或同伴互动超过两周。\n"
            "3. 出现退行行为（如丧失已掌握的语言或自理能力）。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "社交技能发展需要时间，避免与其他孩子比较或施压。",
        "contraindications": "不要将孩子推入超出其舒适区的社交场景，可能加重焦虑。",
    },
    {
        "title": "理发时剧烈抗拒的触觉敏感处理",
        "narrative": (
            "4岁的阳阳每次去理发店都会剧烈哭闹，推开采发师的手。妈妈尝试在家用儿童理发器，"
            "先在理发器关闭时让他触摸和玩理发器，再打开电源但不靠近头部，让他适应声音。"
            "几天后，妈妈用理发器轻轻碰一下他的头发，立刻停下并给予零食奖励。"
            "逐步增加触碰时间，从1秒到5秒再到完成一侧头发。两周后，"
            "阳阳能在家中安静完成理发，虽然仍需要零食和动画片作为奖励。"
        ),
        "behavior_type": "情绪崩溃",
        "age_range": [2, 7],
        "severity": "中度",
        "scene": "家庭",
        "ebp_labels": ["感觉统合(Sensory Integration)", "差别强化(DR)", "任务分析(TA)"],
        "family_category": "环境调整",
        "immediate_action": (
            "1. 立即停止引发强烈抗拒的活动，避免强行按压孩子。\n"
            "2. 将任务拆分为极小步骤：看工具→摸工具→听声音→碰头发→剪一小撮。\n"
            "3. 每完成一个步骤立即给予孩子喜欢的奖励（零食、玩具、动画片）。\n"
            "4. 使用可视化社交故事提前告知理发流程。\n"
            "5. 如果孩子当天状态不佳，允许暂停，不要强迫完成。"
        ),
        "comforting_phrase": (
            "\"理发器只是轻轻碰一下，很快就停。\""
            "\"你做得很好，我们去拿你喜欢的零食。\""
        ),
        "observation_metrics": (
            "1. 孩子对理发器声音的耐受时间是否延长。\n"
            "2. 每次理发步骤完成数量是否增加。\n"
            "3. 哭闹强度是否降低，理发时间是否缩短。"
        ),
        "medical_criteria": (
            "1. 抗拒行为导致孩子或家长受伤。\n"
            "2. 头发长期无法清洁或打理，影响健康。\n"
            "3. 触觉敏感泛化到日常生活多个方面，建议就医评估。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "触觉敏感不是任性，强行完成可能造成长期创伤性记忆。",
        "contraindications": "不要在情绪爆发时继续理发，应暂停并安抚。",
    },
    {
        "title": "餐厅等餐时反复站起来走动的前庭调节",
        "narrative": (
            "11岁的天天和家人在餐厅等餐时，不断从座位上站起来，在餐桌周围走动，"
            "家人担心影响其他顾客。爸爸注意到天天在久坐后容易出现这种行为，判断是"
            "前庭感觉寻求。他在等餐前带天天在餐厅外快走5分钟，等餐时允许他坐在"
            "靠过道的位置，并给他一个可以捏的减压玩具。如果等待时间超过15分钟，"
            "爸爸会带他去门口走一圈再回来。调整后，天天在餐厅站起来的次数明显减少。"
        ),
        "behavior_type": "其他",
        "age_range": [8, 14],
        "severity": "轻度",
        "scene": "公共场合",
        "ebp_labels": ["感觉统合(Sensory Integration)", "前因干预(ABI)", "自我管理"],
        "family_category": "环境调整",
        "immediate_action": (
            "1. 不责备孩子的走动行为，判断可能是前庭或本体感觉需求。\n"
            "2. 在进入需要久坐的场所前，安排5-10分钟的大肌肉活动。\n"
            "3. 选择靠近过道或方便短暂离开的位置。\n"
            "4. 提供手边可操作的减压工具或咀嚼物。\n"
            "5. 如果等待时间过长，主动带孩子出去走一圈再回来。"
        ),
        "comforting_phrase": (
            "\"你想动一动，等会儿我们一起去门口走一下。\""
            "\"先捏这个玩具，餐很快就来了。\""
        ),
        "observation_metrics": (
            "1. 坐下后首次站起来所需时间是否延长。\n"
            "2. 一餐中站起来的总次数是否减少。\n"
            "3. 孩子能否在提示下使用减压工具替代走动。"
        ),
        "medical_criteria": (
            "1. 行为严重干扰公共秩序，多次被场所劝离。\n"
            "2. 伴随无法控制的冲动，即使满足活动需求后仍无法停止。\n"
            "3. 影响正常进食或社交活动。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "前庭感觉需求需要通过合理运动满足，单纯禁止往往无效。",
        "contraindications": "不要将孩子长时间限制在狭小空间内，不使用束缚带等工具。",
    },
    {
        "title": "老师换课后情绪爆发——日程变更应对",
        "narrative": (
            "9岁的轩轩平时按照固定课表上课，某天美术课临时改为数学课，老师在课前5分钟才通知。"
            "轩轩听到后立即把桌上的书推到地上，大声说\"不要上数学\"。班主任意识到他对"
            "日程变更是低耐受的，先带他到教室外安静处，用可视化日程板展示\"今天美术课改为数学课，"
            "明天还是美术课\"。然后给轩轩一个选择：\"你想先喝水，还是先去厕所？\""
            "等他平静后再回到教室。之后学校老师在课表变更前会提前告知并用视觉提示更新日程。"
        ),
        "behavior_type": "情绪崩溃",
        "age_range": [6, 12],
        "severity": "中度",
        "scene": "学校",
        "ebp_labels": ["视觉支持(VS)", "前因干预(ABI)", "辅助替代沟通(AAC)"],
        "family_category": "环境调整",
        "immediate_action": (
            "1. 将孩子带离触发场景，避免在公共场合进一步升级。\n"
            "2. 使用可视化工具（日程板、图片卡片）清晰展示变更内容。\n"
            "3. 用简单语言解释变更原因和持续时间：\"今天换课，明天恢复。\"\n"
            "4. 提供有限选择，恢复孩子的控制感。\n"
            "5. 等情绪平复后再返回原场景，不要求立即道歉或解释。"
        ),
        "comforting_phrase": (
            "\"课表变了，我知道你不开心。\""
            "\"今天数学，明天还是美术。你想先喝水还是先去厕所？\""
        ),
        "observation_metrics": (
            "1. 面对临时变更时情绪平复所需时间。\n"
            "2. 一周内因变更引发的情绪爆发次数。\n"
            "3. 孩子能否在视觉提示帮助下接受变更。"
        ),
        "medical_criteria": (
            "1. 情绪爆发导致自伤、攻击他人或严重破坏财物。\n"
            "2. 无法在任何变更场景下恢复平静，持续影响学业。\n"
            "3. 伴随持续焦虑、失眠或拒学。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "日程变更应尽可能提前预告，并配合视觉提示。",
        "contraindications": "不要以惩罚方式应对孩子对变更的抗拒。",
    },
    {
        "title": "被抢走玩具后的情绪崩溃与替代方案",
        "narrative": (
            "5岁的苗苗在游乐场玩沙子时，另一个孩子过来抢走了她的玩具铲子。"
            "苗苗愣了一下，随即大哭并坐在地上。妈妈快速走到她身边，蹲下说："
            "\"铲子被拿走了，你很伤心。\"她没有立刻去要回铲子，而是先抱住苗苗，"
            "等她哭声小一些后，带她一起到旁边说：\"我们可以请小朋友还回来，"
            "或者用这把备用铲子。\"苗苗选了备用铲子，妈妈随后温柔地引导另一个孩子"
            "归还铲子。回家后，妈妈用角色扮演教苗苗练习说\"请还给我\"。"
        ),
        "behavior_type": "情绪崩溃",
        "age_range": [3, 7],
        "severity": "轻度",
        "scene": "公共场合",
        "ebp_labels": ["辅助替代沟通(AAC)", "社交技能训练(SST)", "自然主义干预(NI)"],
        "family_category": "沟通替代",
        "immediate_action": (
            "1. 立即靠近孩子，用身体提供安全感，命名情绪：\"你很难过。\"\n"
            "2. 不要立即要求孩子分享或解决问题，先处理情绪。\n"
            "3. 提供替代方案：备用玩具、其他活动，或示范如何要回物品。\n"
            "4. 在情绪平复后，用简单语言或角色扮演教孩子表达：\"请还给我。\"\n"
            "5. 如果冲突无法当场解决，先带孩子离开，避免持续刺激。"
        ),
        "comforting_phrase": (
            "\"你的玩具被拿走了，你很伤心。妈妈在这里。\""
            "\"我们可以用这把铲子，或者我们一起说：请还给我。\""
        ),
        "observation_metrics": (
            "1. 情绪平复所需时间是否缩短。\n"
            "2. 孩子能否在提示下使用语言表达需求。\n"
            "3. 类似冲突中哭泣强度是否降低。"
        ),
        "medical_criteria": (
            "1. 崩溃持续超过20分钟且无法安抚。\n"
            "2. 出现攻击他人或严重自伤行为。\n"
            "3. 因社交冲突完全拒绝外出或参与活动。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "不要强迫孩子立即分享或道歉，先处理情绪再教技能。",
        "contraindications": "不要当众批评孩子\"小气\"或\"不懂事\"。",
    },
    {
        "title": "看医生排队时的焦虑与视觉倒计时干预",
        "narrative": (
            "7岁的航航每次去医院排队都会变得非常焦虑，反复问\"还有几个人\"，"
            "声音越来越大，甚至想离开候诊室。爸爸制作了一张简单的视觉倒计时卡，"
            "每次前面一个人看完病，就撕掉一格。同时他告诉航航：\"还有3个人，"
            "然后轮到我们。\"航航可以拿着倒计时卡，每减少一格爸爸就表扬他一次。"
            "使用视觉倒计时后，航航在候诊室的焦虑行为明显减少，能够安静等待15分钟左右。"
        ),
        "behavior_type": "其他",
        "age_range": [4, 10],
        "severity": "中度",
        "scene": "公共场合",
        "ebp_labels": ["视觉支持(VS)", "自我管理", "前因干预(ABI)"],
        "family_category": "自我管理",
        "immediate_action": (
            "1. 识别焦虑信号（反复提问、声音变大、试图离开），提前介入。\n"
            "2. 使用可视化倒计时工具，让孩子清楚看到等待进度。\n"
            "3. 用简短、具体的语言告知剩余步骤：\"还有3个人，然后轮到我们。\"\n"
            "4. 每完成一个等待步骤给予即时肯定和奖励。\n"
            "5. 如果孩子焦虑加剧，可带到候诊室门口安静处做几个深呼吸再回来。"
        ),
        "comforting_phrase": (
            "\"我们知道还有几个人，看这张卡，还有3格。\""
            "\"你等得很好，我们再等一格就可以进去了。\""
        ),
        "observation_metrics": (
            "1. 候诊时反复询问的次数是否减少。\n"
            "2. 孩子能安静等待的时长是否延长。\n"
            "3. 试图离开候诊室的频率是否下降。"
        ),
        "medical_criteria": (
            "1. 焦虑导致完全无法进入诊室或接受检查。\n"
            "2. 出现呕吐、过度换气等躯体化症状。\n"
            "3. 长期拒绝就医，影响健康管理。"
        ),
        "evidence_level": "机构经验总结",
        "caution_notes": "医疗环境的陌生感和不可预测性是焦虑的主要来源，可视化可显著降低不确定性。",
        "contraindications": "不要用恐吓方式让孩子配合就医。",
    },
]


# ---------------------------------------------------------------------------
# 导入逻辑
# ---------------------------------------------------------------------------

async def clear_seed_data(session: AsyncSession) -> int:
    """删除由本脚本导入的种子数据（按 author_id 匹配）。"""
    # 查询种子叙事
    result = await session.execute(
        select(CaseNarrative.narrative_id).where(CaseNarrative.author_id == SEED_AUTHOR_ID)
    )
    narrative_ids = [row[0] for row in result.fetchall()]

    deleted_chunks = 0
    if narrative_ids:
        # 查询关联卡片
        result = await session.execute(
            select(CaseCard.card_id).where(CaseCard.narrative_id.in_(narrative_ids))
        )
        card_ids = [row[0] for row in result.fetchall()]

        if card_ids:
            # 删除向量切片
            chunk_result = await session.execute(
                delete(CaseChunk).where(CaseChunk.card_id.in_(card_ids))
            )
            deleted_chunks = chunk_result.rowcount

            # 删除卡片
            await session.execute(delete(CaseCard).where(CaseCard.card_id.in_(card_ids)))

        # 删除叙事
        await session.execute(
            delete(CaseNarrative).where(CaseNarrative.narrative_id.in_(narrative_ids))
        )

    await session.commit()
    return deleted_chunks


async def import_seed_data(
    session: AsyncSession,
    enqueue: bool = False,
) -> tuple[list[CaseCard], list[CaseCard]]:
    """导入种子案例数据。

    Returns:
        (created_cards, indexed_cards) 元组。
    """
    created_cards: list[CaseCard] = []

    for case_data in SEED_CASES:
        narrative = CaseNarrative(
            narrative_id=uuid.uuid4(),
            title=case_data["title"],
            narrative=case_data["narrative"],
            source_type=SEED_SOURCE_TYPE,
            author_id=SEED_AUTHOR_ID,
            status="approved",
            extraction_status="extracted",
        )
        session.add(narrative)
        await session.flush()  # 获取 narrative_id

        card = CaseCard(
            card_id=uuid.uuid4(),
            narrative_id=narrative.narrative_id,
            title=case_data["title"],
            scenario=f"{case_data['scene']}中的{case_data['behavior_type']}行为干预",
            behavior_type=case_data["behavior_type"],
            age_range_min=case_data["age_range"][0],
            age_range_max=case_data["age_range"][1],
            severity=case_data["severity"],
            scene=case_data["scene"],
            ebp_labels=case_data["ebp_labels"],
            family_category=case_data["family_category"],
            immediate_action=case_data["immediate_action"],
            comforting_phrase=case_data["comforting_phrase"],
            observation_metrics=case_data["observation_metrics"],
            medical_criteria=case_data["medical_criteria"],
            evidence_level=case_data["evidence_level"],
            caution_notes=case_data["caution_notes"],
            contraindications=case_data["contraindications"],
            is_template=False,
            review_status="approved",
            index_status="pending",
        )
        session.add(card)
        await session.flush()

        narrative.derived_card_ids = [str(card.card_id)]
        created_cards.append(card)

    await session.commit()

    if enqueue:
        # 投递到 Redis 队列，由 Worker 异步处理
        for card in created_cards:
            await enqueue_index_task(card.card_id, session)
        return created_cards, []

    # 直接生成向量索引
    pipeline = IndexPipeline(
        embedding_encoder=_get_encoder(),
        chunk_builder=build_chunk_text,
        index_writer=write_index_to_pgvector,
    )

    indexed_cards: list[CaseCard] = []
    for card in created_cards:
        card_title = card.title  # 提前读取，避免 session 状态变化后 lazy-load 失败
        card_id = str(card.card_id)
        trace_id = secrets.token_hex(16)
        try:
            await pipeline.process_task(
                case_id=CaseIdStr(card_id),
                trace_id=trace_id,
                db_session=session,
            )
            indexed_cards.append(card)
            logger.info(
                "seed",
                f"卡片索引完成: {card_title}",
                extra={"card_id": card_id},
            )
        except Exception as exc:
            logger.error(
                "seed",
                f"卡片索引失败: {card_title}",
                extra={"card_id": card_id, "error": str(exc)},
            )

    return created_cards, indexed_cards


async def main() -> int:
    parser = argparse.ArgumentParser(description="Campfire-AI 种子案例导入脚本")
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="仅投递到 Redis 队列，由 Worker 异步生成向量索引（默认直接生成）",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="先清空已有种子数据，再导入",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅校验种子数据格式，不写入数据库",
    )
    args = parser.parse_args()

    if args.check:
        print(f"[CHECK] 种子数据共 {len(SEED_CASES)} 条")
        for i, case in enumerate(SEED_CASES, 1):
            print(f"  {i}. {case['title']} | {case['behavior_type']} | {case['severity']} | {case['scene']}")
        print("[OK] 种子数据格式校验通过")
        return 0

    settings = get_settings()
    database_url = str(settings.DATABASE_URL)

    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        if args.clear:
            deleted = await clear_seed_data(session)
            print(f"[INFO] 已清空种子数据，删除 {deleted} 条向量切片")

        print(f"[INFO] 开始导入 {len(SEED_CASES)} 条种子案例...")
        created_cards, indexed_cards = await import_seed_data(
            session, enqueue=args.enqueue
        )
        print(f"[OK] 创建 {len(created_cards)} 张 L2 卡片")

        if args.enqueue:
            print("[OK] 已投递到 Redis 队列，请确保 Worker 正在运行")
        else:
            print(f"[OK] 直接生成向量索引完成：{len(indexed_cards)}/{len(created_cards)}")

            # 验证索引状态
            result = await session.execute(
                select(CaseCard.card_id, CaseCard.index_status).where(
                    CaseCard.card_id.in_([c.card_id for c in created_cards])
                )
            )
            status_map = {str(row[0]): row[1] for row in result.fetchall()}
            failed = [
                c for c in created_cards
                if status_map.get(str(c.card_id)) != "indexed"
            ]
            if failed:
                print(f"[WARN] {len(failed)} 张卡片索引未成功，请检查日志")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

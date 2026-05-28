#!/usr/bin/env python3
"""MVP 种子数据导入脚本。

将 20 条预置案例插入 cases 表，状态设为 approved，并投递 Redis
索引队列。不依赖项目内部包栈，仅使用 asyncpg + redis + python-dotenv。

用法:
    uv run scripts/seed.py
    uv run scripts/seed.py --append          # 不清空现有数据
    uv run scripts/seed.py --count 30        # 导入 30 条
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import asyncpg
import redis
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL: str = os.getenv("DATABASE_URL", "")
REDIS_URL: str = os.getenv("REDIS_URL", "")

# ---------------------------------------------------------------------------
# 种子数据（20 条，覆盖 6 种行为类型）
# ---------------------------------------------------------------------------

_SEED_CASES: list[dict[str, object]] = [
    # 自伤
    {
        "title": "商场捂耳尖叫自伤",
        "behavior_type": "自伤",
        "severity": "重度",
        "scene": "公共场合",
        "immediate_action": "立即用双手轻托孩子手肘，阻止击打头部动作，同时蹲下与孩子平视。",
        "comforting_phrase": "妈妈在这里，你很安全，我们一起深呼吸。",
        "observation_metrics": "观察自伤频率是否下降，记录触发前 30 秒的环境噪音分贝。",
        "medical_criteria": "若头部出现红肿或连续自伤超过 5 分钟无法安抚，立即就医。",
        "evidence_level": "机构经验总结",
        "age_range_min": 3,
        "age_range_max": 8,
    },
    {
        "title": "课堂咬手行为",
        "behavior_type": "自伤",
        "severity": "中度",
        "scene": "学校",
        "immediate_action": "递上咬合玩具替代手指，轻拍背部转移注意力。",
        "comforting_phrase": "你的手会疼，咬这个软软的玩具吧。",
        "observation_metrics": "记录咬手发生时段（课前/课中/课后），是否与特定科目相关。",
        "medical_criteria": "手部破皮出血或出现感染迹象时需就医处理。",
        "evidence_level": "个案观察记录",
        "age_range_min": 5,
        "age_range_max": 12,
    },
    {
        "title": "家庭环境撞头",
        "behavior_type": "自伤",
        "severity": "重度",
        "scene": "家庭",
        "immediate_action": "迅速在头部与墙壁之间垫入软枕，保持安静不增加刺激。",
        "comforting_phrase": "没关系，慢慢停下来，我陪着你。",
        "observation_metrics": "记录撞头前 1 分钟的事件链，排查感官过载因素。",
        "medical_criteria": "撞击后出现意识模糊、呕吐或头部凹陷，立即送急诊。",
        "evidence_level": "机构经验总结",
        "age_range_min": 2,
        "age_range_max": 6,
    },
    # 攻击
    {
        "title": "超市抓挠陌生人",
        "behavior_type": "攻击",
        "severity": "中度",
        "scene": "公共场合",
        "immediate_action": "立即用身体隔开孩子与他人，双手握住孩子手腕向下轻压。",
        "comforting_phrase": "我知道你很着急，我们不能抓别人，抓我的手。",
        "observation_metrics": "观察攻击对象是否为特定人群（性别/年龄/衣着颜色），记录空间拥挤程度。",
        "medical_criteria": "造成他人皮肤破损出血，需陪同就医并评估是否需行为干预师介入。",
        "evidence_level": "NCAEP循证实践",
        "age_range_min": 4,
        "age_range_max": 10,
    },
    {
        "title": "同伴冲突推搡",
        "behavior_type": "攻击",
        "severity": "轻度",
        "scene": "学校",
        "immediate_action": "将双方拉开一臂距离，让孩子背对冲突对象坐下。",
        "comforting_phrase": "推别人会让他们摔倒，我们用手轻轻碰来表示友好。",
        "observation_metrics": "记录推搡前 3 分钟的社会互动事件，是否有玩具争夺。",
        "medical_criteria": "对方摔倒出现擦伤或孩子情绪持续失控超过 10 分钟，联系校医。",
        "evidence_level": "个案观察记录",
        "age_range_min": 6,
        "age_range_max": 12,
    },
    {
        "title": "家庭内对弟妹抓咬",
        "behavior_type": "攻击",
        "severity": "中度",
        "scene": "家庭",
        "immediate_action": "立即将两个孩子物理隔离到不同房间，检查被抓咬处。",
        "comforting_phrase": "你是哥哥/姐姐，弟弟/妹妹会疼，我们轻轻摸摸他。",
        "observation_metrics": "记录攻击发生时父母注意力分配情况，是否与弟妹获得关注有关。",
        "medical_criteria": "伤口深度超过表皮或出现淤青肿胀，需就医处理并评估破伤风疫苗。",
        "evidence_level": "机构经验总结",
        "age_range_min": 5,
        "age_range_max": 14,
    },
    # 刻板
    {
        "title": "课堂反复开关门",
        "behavior_type": "刻板",
        "severity": "轻度",
        "scene": "学校",
        "immediate_action": "用身体轻挡门框，递上替代感官玩具（如减压球），引导回座位。",
        "comforting_phrase": "门已经关好了，我们回座位捏捏这个球。",
        "observation_metrics": "记录刻板行为持续时间，以及替代玩具的接受度。",
        "medical_criteria": "刻板行为导致课堂完全无法参与超过 30 分钟，需与特教老师制定 IEP 调整方案。",
        "evidence_level": "NCAEP循证实践",
        "age_range_min": 6,
        "age_range_max": 14,
    },
    {
        "title": "公共场合排列物品",
        "behavior_type": "刻板",
        "severity": "轻度",
        "scene": "公共场合",
        "immediate_action": "不强行打断，蹲下来观察排列规律，用温和语气引导\"我们排好队再走吧\"。",
        "comforting_phrase": "你排得真整齐！现在我们一起把东西放回去，好不好？",
        "observation_metrics": "记录排列物品的种类偏好，以及被打断时的情绪反应强度。",
        "medical_criteria": "刻板行为严重到完全拒绝移动，影响公共安全（如阻挡紧急通道）时，需撤离现场。",
        "evidence_level": "个案观察记录",
        "age_range_min": 4,
        "age_range_max": 12,
    },
    {
        "title": "家中反复旋转身体",
        "behavior_type": "刻板",
        "severity": "中度",
        "scene": "家庭",
        "immediate_action": "在旋转区域铺设软垫防跌倒，播放节奏音乐引导转化为有规律的舞蹈。",
        "comforting_phrase": "转得好快呀！要不要跟着音乐转？",
        "observation_metrics": "记录旋转时长和频率，是否与无聊/焦虑情绪相关。",
        "medical_criteria": "旋转导致晕眩呕吐或撞伤家具，需限制活动区域并咨询作业治疗师。",
        "evidence_level": "机构经验总结",
        "age_range_min": 3,
        "age_range_max": 10,
    },
    # 逃跑
    {
        "title": "公园突然跑向马路",
        "behavior_type": "逃跑",
        "severity": "重度",
        "scene": "公共场合",
        "immediate_action": "立即冲刺追赶，大声呼喊孩子名字，必要时丢弃手中物品优先拦截。",
        "comforting_phrase": "停！这里危险！拉住我的手，我们一起走。",
        "observation_metrics": "记录逃跑前的环境刺激（噪音/人群/动物），以及逃跑方向偏好。",
        "medical_criteria": "逃跑过程中发生交通险情或身体受伤，立即就医并报警备案。",
        "evidence_level": "机构经验总结",
        "age_range_min": 4,
        "age_range_max": 12,
    },
    {
        "title": "商场脱离监护人",
        "behavior_type": "逃跑",
        "severity": "中度",
        "scene": "公共场合",
        "immediate_action": "立即通知商场广播寻人，分头在电梯/出口/游戏区寻找，保持手机畅通。",
        "comforting_phrase": "（找到后）妈妈急死了，下次一定要拉住我的手，好吗？",
        "observation_metrics": "记录脱离地点和被发现地点，分析吸引物（玩具/食物/亮色招牌）。",
        "medical_criteria": "脱离时间超过 15 分钟或孩子表达被陌生人接触，立即报警。",
        "evidence_level": "机构经验总结",
        "age_range_min": 5,
        "age_range_max": 14,
    },
    {
        "title": "校园内躲藏",
        "behavior_type": "逃跑",
        "severity": "轻度",
        "scene": "学校",
        "immediate_action": "保持冷静不惊动其他学生，联系保安封锁出口，逐一排查厕所/储物柜/花坛。",
        "comforting_phrase": "老师找到你了，不用害怕，我们回教室休息。",
        "observation_metrics": "记录躲藏前的事件（被批评/作业困难/社交冲突），以及躲藏位置偏好。",
        "medical_criteria": "躲藏导致上课时间损失超过 1 课时或出现自伤行为，需心理老师介入评估。",
        "evidence_level": "个案观察记录",
        "age_range_min": 7,
        "age_range_max": 16,
    },
    # 情绪崩溃
    {
        "title": "餐厅 meltdown 大哭倒地",
        "behavior_type": "情绪崩溃",
        "severity": "重度",
        "scene": "公共场合",
        "immediate_action": "立即用身体围成保护圈，防止踢打到他人或桌椅，不强行拉拽。",
        "comforting_phrase": "你很难过，我陪着你，等你好了我们再走。",
        "observation_metrics": "记录崩溃总时长和恢复触发点（特定食物/温度/噪音阈值）。",
        "medical_criteria": "崩溃后出现呼吸过度、嘴唇发紫或意识模糊，立即就医。",
        "evidence_level": "机构经验总结",
        "age_range_min": 3,
        "age_range_max": 10,
    },
    {
        "title": "课堂突然大哭",
        "behavior_type": "情绪崩溃",
        "severity": "中度",
        "scene": "学校",
        "immediate_action": "请助教陪同离开教室，到安静角落（如资源教室）坐下，提供降噪耳机。",
        "comforting_phrase": "教室太吵了对吗？我们在这里静一静。",
        "observation_metrics": "记录崩溃前 5 分钟的课堂活动类型（小组/独立/转换环节），以及恢复时间。",
        "medical_criteria": "哭泣伴随呕吐或持续超过 30 分钟无法安抚，联系校医和家长。",
        "evidence_level": "NCAEP循证实践",
        "age_range_min": 5,
        "age_range_max": 14,
    },
    {
        "title": "家庭环境摔东西",
        "behavior_type": "情绪崩溃",
        "severity": "中度",
        "scene": "家庭",
        "immediate_action": "迅速移开易碎和危险物品，用身体轻挡投掷方向，保持低声调说话。",
        "comforting_phrase": "东西摔坏了没关系，我们先坐下来，告诉我怎么了。",
        "observation_metrics": "记录摔东西前的请求或拒绝事件，以及物品类型偏好（软/硬/有声响）。",
        "medical_criteria": "投掷物造成人员受伤或孩子手部被碎片割伤，立即处理伤口并评估情绪危机。",
        "evidence_level": "个案观察记录",
        "age_range_min": 4,
        "age_range_max": 12,
    },
    {
        "title": "购物时倒地不起",
        "behavior_type": "情绪崩溃",
        "severity": "重度",
        "scene": "公共场合",
        "immediate_action": "就地坐下陪伴孩子，用外套或围巾垫在身下，请店员帮忙维持周围空间。",
        "comforting_phrase": "我们就在这里休息，不买东西了，等你好了我们回家。",
        "observation_metrics": "记录触发前店内环境变化（灯光/音乐/人流），以及最有效的安抚物。",
        "medical_criteria": "倒地后出现抽搐、瞳孔散大或呼吸困难，立即拨打急救电话。",
        "evidence_level": "机构经验总结",
        "age_range_min": 3,
        "age_range_max": 8,
    },
    # 其他
    {
        "title": "拒绝穿鞋出门",
        "behavior_type": "其他",
        "severity": "轻度",
        "scene": "家庭",
        "immediate_action": "提供两双鞋让孩子选择，或使用视觉日程表提示\"出门先穿鞋\"。",
        "comforting_phrase": "选红色这双还是蓝色这双？穿好了我们就可以去公园。",
        "observation_metrics": "记录拒绝鞋的感官特征（材质/紧度/标签位置），以及选择策略的有效性。",
        "medical_criteria": "因拒绝穿鞋导致足部受伤（如踩到尖锐物），处理伤口并评估鞋类适配需求。",
        "evidence_level": "个案观察记录",
        "age_range_min": 2,
        "age_range_max": 8,
    },
    {
        "title": "反复按电梯按钮",
        "behavior_type": "其他",
        "severity": "轻度",
        "scene": "公共场合",
        "immediate_action": "用身体轻挡按钮面板，递上替代按压玩具，引导等待电梯到达。",
        "comforting_phrase": "电梯马上就到了，我们先按一下这个计数器，1、2、3...",
        "observation_metrics": "记录按钮按压频率和等待时长耐受度，以及替代活动的接受度。",
        "medical_criteria": "按压行为导致手指红肿或影响他人正常使用电梯，需限制接触并评估感觉统合需求。",
        "evidence_level": "NCAEP循证实践",
        "age_range_min": 4,
        "age_range_max": 10,
    },
    {
        "title": "拒绝进食",
        "behavior_type": "其他",
        "severity": "中度",
        "scene": "家庭",
        "immediate_action": "不强迫进食，提供同一食物的不同形态（如苹果片/苹果泥），营造安静就餐环境。",
        "comforting_phrase": "不饿也没关系，先放在这里，你想吃的时候告诉我。",
        "observation_metrics": "记录拒绝食物的质地/温度/颜色特征，以及替代食物的接受清单。",
        "medical_criteria": "连续 24 小时拒绝进食或出现脱水症状（尿少/口唇干裂），立即就医。",
        "evidence_level": "机构经验总结",
        "age_range_min": 3,
        "age_range_max": 10,
    },
    {
        "title": "睡眠节律紊乱",
        "behavior_type": "其他",
        "severity": "中度",
        "scene": "家庭",
        "immediate_action": "建立固定睡前程序（洗澡→故事→关灯），使用白噪音机，避免睡前屏幕刺激。",
        "comforting_phrase": "故事讲完了，现在我们闭上眼睛，明天见。",
        "observation_metrics": "记录入睡时间和夜间觉醒次数，以及白天的活动量与光照暴露时长。",
        "medical_criteria": "连续一周每天睡眠少于 6 小时且白天出现严重功能下降，需儿童睡眠专科评估。",
        "evidence_level": "NCAEP循证实践",
        "age_range_min": 2,
        "age_range_max": 12,
    },
    {
        "title": "频繁洗手",
        "behavior_type": "其他",
        "severity": "轻度",
        "scene": "学校",
        "immediate_action": "设置洗手计时器（15 秒），使用可视化倒计时，完成后给予即时表扬。",
        "comforting_phrase": "洗得真干净！计时器响了，我们擦擦手回座位吧。",
        "observation_metrics": "记录洗手触发情境（弄脏/Transitions/焦虑），以及每次洗手时长。",
        "medical_criteria": "手部皮肤出现皲裂出血或洗手行为严重干扰课程参与，需皮肤科和心理健康联合评估。",
        "evidence_level": "个案观察记录",
        "age_range_min": 5,
        "age_range_max": 14,
    },
]


# ---------------------------------------------------------------------------
# 数据库操作
# ---------------------------------------------------------------------------

_INSERT_SQL = """
    INSERT INTO cases (
        case_id, title, narrative, source_type, author_id,
        behavior_type, age_range_min, age_range_max, severity, scene,
        ebp_labels, family_category, immediate_action, comforting_phrase,
        observation_metrics, medical_criteria, evidence_level,
        contraindications, is_template, status, index_status,
        created_at, updated_at
    ) VALUES (
        $1, $2, $3, $4, $5,
        $6, $7, $8, $9, $10,
        $11, $12, $13, $14,
        $15, $16, $17,
        $18, $19, $20, $21,
        $22, $23
    )
"""


_case_counter: int = 0


def _generate_case_id(year: int) -> str:
    """生成 CASE-YYYY-NNNN 格式 ID（内存计数器，不依赖数据库序列）。"""
    global _case_counter
    _case_counter += 1
    return f"CASE-{year}-{_case_counter:04d}"


async def _clear_cases(conn: asyncpg.Connection) -> int:
    """清空现有案例，返回删除行数。"""
    count = await conn.fetchval("SELECT COUNT(*) FROM cases")
    await conn.execute("DELETE FROM cases")
    await conn.execute("DELETE FROM case_reviews")
    await conn.execute("DELETE FROM review_audit_logs")
    return int(count)


async def seed(args: argparse.Namespace) -> None:
    """执行种子导入。"""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL 环境变量未设置", file=sys.stderr)
        sys.exit(1)
    if not REDIS_URL:
        print("ERROR: REDIS_URL 环境变量未设置", file=sys.stderr)
        sys.exit(1)

    # 连接数据库（asyncpg 只接受 postgresql://，去掉 +asyncpg 驱动标记）
    db_url = str(DATABASE_URL).replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)
    redis_client = redis.from_url(str(REDIS_URL), decode_responses=True)

    try:
        # 是否清空
        if not args.append:
            deleted = await _clear_cases(conn)
            print(f"已清空现有数据: {deleted} 条案例")

        # 选择种子数据
        cases_to_insert = _SEED_CASES[: args.count]
        now = datetime.now(timezone.utc)
        year = now.year
        inserted_ids: list[str] = []

        for case_data in cases_to_insert:
            case_id = _generate_case_id(year)
            await conn.execute(
                _INSERT_SQL,
                case_id,
                case_data["title"],
                "",  # narrative (MVP 简化)
                "专家撰写",  # source_type
                "seed-script",  # author_id
                case_data["behavior_type"],
                case_data["age_range_min"],
                case_data["age_range_max"],
                case_data["severity"],
                case_data["scene"],
                "[]",  # ebp_labels (JSON 空数组)
                "危机安全",  # family_category
                case_data["immediate_action"],
                case_data["comforting_phrase"],
                case_data["observation_metrics"],
                case_data["medical_criteria"],
                case_data["evidence_level"],
                "暂无",  # contraindications
                False,  # is_template
                "approved",  # status — 直接 approved，跳过审核流程
                "pending",  # index_status — 等待 Worker 索引
                now,
                now,
            )
            inserted_ids.append(case_id)
            print(f"  插入: {case_id} — {case_data['title']}")

        # 投递 Redis 索引队列
        for case_id in inserted_ids:
            payload = json.dumps({"task": "index_case", "case_id": case_id})
            redis_client.lpush("campfire:case_index", payload)

        print(f"\n完成: 插入 {len(inserted_ids)} 条案例，投递 {len(inserted_ids)} 个索引任务到 Redis")

    finally:
        await conn.close()
        redis_client.close()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP 种子数据导入脚本")
    parser.add_argument(
        "--append",
        action="store_true",
        help="追加模式：不清空现有数据",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="导入条数（默认 20）",
    )
    args = parser.parse_args()
    asyncio.run(seed(args))


if __name__ == "__main__":
    main()

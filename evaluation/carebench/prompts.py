"""提示词文本：全包唯一的提示词字面量处，并给出它们的 SHA-256。

职责：定义 A/B 两组的共同任务边界提示、B 组的证据使用提示、C 组用的产品面提示引用，
以及「拒答嫌疑」的保守判定词表。

边界：**不改产品提示**——C 组必须用产品自己的面提示（:data:`PRODUCT_INSTRUCTIONS_SOURCE`），
本模块只记录它从哪里取、hash 是多少。A/B 的提示是本评测工具的一部分，属被测对照条件，
必须与 C 的产品提示一起记进 manifest，否则「同底模、同任务边界」无法核对。

公平性口径（这是本模块存在的理由）：

- A 与 B **必须**用同一段 :data:`COMMON_TASK_INSTRUCTIONS`，唯一差别是 B 额外拿到检索
  到的材料。任何「只给某一组的关键约束」都会让差异无法归因到检索机制。
- C 用的是产品真实提示（`surfaces.consult.assembly.CONSULT_INSTRUCTIONS`）——它本身就是
  被测系统的一部分，评测不得替换它（替换了就不是「当前生产 Agent」了）。
- 三组收到的**使用者文本逐字节相同**（见 :func:`render_user_turn`），且该文本的
  SHA-256 落进每条输出记录，供事后核对信息对称。
"""

from __future__ import annotations

import hashlib

#: A/B 共用的任务边界：说清身份、语言、可执行性要求、安全边界与正文格式。
#:
#: 为什么写得这么具体：协议 01 第 4 节要求 A 组是「同一底座模型 + 精简的共同任务说明」，
#: 而「精简」不等于「什么都不说」——不说清输出纪律时，A 组会因为格式散乱系统性吃亏，
#: 那类差异与「有没有检索/工作流」无关，会污染 H2/H3 的判读。
COMMON_TASK_INSTRUCTIONS = (
    "你是一个面向孤独症儿童家长的照护咨询助手，用中文回答。"
    "使用者会先给出已经确认的背景信息，然后提出问题。"
    "回答要落到这位家长此刻能做的事情上：结合背景里的具体条件（在场成人数量、场地、"
    "孩子的沟通与感官偏好、手上可用的资源），不要提出他做不到的必做步骤。"
    "信息不足时先问最关键的一两个问题再给建议。"
    "涉及安全风险时，说明哪些变化意味着应当立即寻求专业或紧急帮助。"
    "不要声称做过没有做的检索或检查，不要编造资料、出处、档案或专家意见。"
    "正文一律用纯文本：不要使用 markdown 标记（如 **加粗**、# 标题、竖线表格）。"
)

#: B 组追加的证据使用纪律（「基本引用」的落地口径，协议 05 第 4 节）。
#:
#: 只在 B 组出现是刻意的：这就是 RAG 基线的处理（受控检索 + 引用约定），
#: C 组要自己决定何时检索、怎么标注——那是被测能力的一部分。
RAG_EVIDENCE_INSTRUCTIONS = (
    "下面会附带资料库检索到的材料，每条带标题、出处与适用范围。"
    "尽量依据这些材料回答，用到时在句末用括号注明材料标题或出处。"
    "材料没有覆盖的部分要明确说「资料库未给出依据」，不要用常识或印象冒充依据。"
    "材料之间冲突时说明冲突本身，不要替使用者选边。"
)

#: C 组提示取自何处（只记录来源，不复制产品文本——复制会制造第二真源）。
PRODUCT_INSTRUCTIONS_SOURCE = "campfire.surfaces.consult.assembly.CONSULT_INSTRUCTIONS"

#: 不同知识来源之间的分节标题；`{source}` 由 manifest 里的快照 id 填。
CONTEXT_HEADING = "【已确认的背景信息】"
QUESTION_HEADING = "【我的问题】"
FOLLOWUP_HEADING = "【补充说明】"

#: 检索材料块的起止标记（B 组）。
EVIDENCE_HEADING = "【资料库检索到的材料】"
EVIDENCE_EMPTY = "（本次检索没有返回任何材料：资料库当前没有可引用的依据。）"


def sha256_text(text: str) -> str:
    """提示词文本的 SHA-256（UTF-8）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_user_turn(*, shared_context: str, message: str, is_followup: bool) -> str:
    """把案例的「共享背景 + 本轮输入」渲染成使用者文本。

    **三组共用本函数**（A/B/C 都调它），这是「信息可得性对称」的实现方式而不是注释承诺：
    任何一组拿到不同的包装，都会让 `input_sha256` 在输出记录里对不上，verify 会报出来。
    """
    heading = FOLLOWUP_HEADING if is_followup else QUESTION_HEADING
    return f"{CONTEXT_HEADING}\n{shared_context.strip()}\n\n{heading}\n{message.strip()}\n"


#: 拒答嫌疑的保守词表。
#:
#: 用途严格受限：**只标记 `status_flags.refusal_suspected`，不决定 `completion_status`**。
#: 自动判「拒答」在照护场景里尤其危险——「建议现在就联系医生」既是正确的安全表达，
#: 也可能被粗糙的关键词规则误当成拒答。因此真正的 `completion_status` 由评审者在
#: `ratings.csv` 里判定（见 :mod:`evaluation.carebench.review`），这里只给一个排查线索。
REFUSAL_MARKERS = (
    "我无法回答",
    "我不能回答",
    "我无法提供",
    "我不能提供",
    "无法协助",
    "不能协助",
    "抱歉，我无法",
    "抱歉，我不能",
    "我不能帮你",
    "我无法帮你",
)

#: 拒答嫌疑的文本长度上界（字符）。长文里出现上述片段通常是「我不能提供医疗诊断」这类
#: 正常边界说明，而不是整段拒答，因此只在短文里标记。
REFUSAL_MAX_CHARS = 600


def refusal_suspected(text: str) -> bool:
    """按保守词表标记「拒答嫌疑」。不是判定，只是线索。"""
    stripped = text.strip()
    if not stripped or len(stripped) > REFUSAL_MAX_CHARS:
        return False
    return any(marker in stripped for marker in REFUSAL_MARKERS)


__all__ = [
    "COMMON_TASK_INSTRUCTIONS",
    "CONTEXT_HEADING",
    "EVIDENCE_EMPTY",
    "EVIDENCE_HEADING",
    "FOLLOWUP_HEADING",
    "PRODUCT_INSTRUCTIONS_SOURCE",
    "QUESTION_HEADING",
    "RAG_EVIDENCE_INSTRUCTIONS",
    "REFUSAL_MARKERS",
    "REFUSAL_MAX_CHARS",
    "refusal_suspected",
    "render_user_turn",
    "sha256_text",
]

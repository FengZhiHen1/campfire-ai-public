"""注册（邀请码）：复写身份服务的 sign-up API。

职责：在 sign-up 复写法内先原子占用邀请码，通过后再调用原实现建号。
边界：不自建注册端点、不自己签发会话；占用与释放都落 `repository`。
参考：docs/项目结构设计.md 第 6 节；认证与账号第 4 节（docs/技术设计/technical-details/认证与账号.md）。

账号名不要求邮箱格式（`RQ-ACC-05`）：设计真源要求「复写 email 校验器使账号名通过校验」，
落点是 :func:`sign_up_form_fields` 里为 `email` 字段显式给出 `validate`
（:func:`_validate_account_name`）。身份服务的默认邮箱校验器（要求 `@`）**只在该字段
没有 `validate` 时才生效**（实测 `supertokens_python/recipe/emailpassword/utils.py:111-119`），
因此这一个声明就是「账号名」与「邮箱」的分界点。缺陷 `PROD-01` 的成因正是该声明从未落地。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Union

from supertokens_python.recipe.emailpassword import InputFormField
from supertokens_python.recipe.emailpassword.interfaces import (
    APIInterface,
    APIOptions,
    EmailAlreadyExistsError,
    GeneralErrorResponse,
    SignUpPostNotAllowedResponse,
    SignUpPostOkResult,
)
from supertokens_python.recipe.emailpassword.types import FormField
from supertokens_python.recipe.session import SessionContainer

from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts.errors import AccountsError, InviteCodeError
from campfire.modules.accounts.repository import (
    bind_invite_code_account,
    claim_invite_code,
    release_invite_code,
)

logger = logging.getLogger(__name__)

#: `sign_up_post` 原实现/复写实现的确切返回类型（SDK `APIInterface` 的签名，
#: 见 `recipe/emailpassword/interfaces.py`）。复写必须逐字沿用——包装器与
#: 原实现可互换是「包装而非重写」成立的前提。
SignUpPostResult = Union[
    SignUpPostOkResult, EmailAlreadyExistsError, SignUpPostNotAllowedResponse, GeneralErrorResponse
]

#: 原实现的函数类型：与 `APIInterface.sign_up_post` 同签名（六个位置参数按 SDK
#: 契约，位置形态由 `Callable[..., ...]` 表达）。
#: 返回侧用 `Awaitable` 而不是 `Coroutine`：SDK 侧是 async def（协程），
#: 我们的包装器也是 async def，`Awaitable` 对两者都成立且不虚构协程细节。
OriginalSignUpPost = Callable[..., "Awaitable[SignUpPostResult]"]

#: signup 请求里承载邀请码的自定义表单字段名。
#:
#: 它是前后端契约：前端须以该字段名提交邀请码。写死在常量里并由测试钉住，
#: 避免前后端各写一份字符串而无人发现不一致（那种不一致表现为「注册总是被拒」）。
#:
#: 它还必须被声明进身份服务的 signup 表单（见 :func:`sign_up_form_fields`）：
#: 实测 SDK 在调用复写之前就校验表单字段的数量与形状——未声明的字段会让请求
#: 以 400 `Are you sending too many formFields?` 被拒，复写函数根本不会被调用。
#:
#: 表单字段的契约：邀请码字段名是 :data:`INVITE_CODE_FORM_FIELD`。它同时是前端契约的一部分
#: （前端须把它作为 signup 请求的自定义字段提交），因此写死在常量里并由测试钉住。
INVITE_CODE_FORM_FIELD = "inviteCode"

#: 账号名字段的字段名（身份服务沿用 `email` 字段承载账号名，`TECH-08` 已知偏差）。
#:
#: 刻意不在这里改名：该字段名由身份服务的 SDK 契约决定，我们只读取它。
#:
#: ⚠️ 它同时是**唯一**的账号名字段：身份服务的 sign-up 与 sign-in 都只认这一个
#: 字段名，没有第二处可以挂账号名。
EMAIL_FORM_FIELD = "email"

#: 密码字段名（同样由 SDK 契约决定）。
PASSWORD_FORM_FIELD = "password"

#: 邀请码在表单层不做实质校验（只要求它是字符串）。
#:
#: 这是刻意的，且第一版写错过：第一版在这里校验「非空且长度 ≥8」并在不满足时
#: 返回表单错误，结果实测「长度不对的码」返回的是 `FIELD_ERROR`，而其它三种拒绝
#: 返回 `GENERAL_ERROR`——两种响应形状不同，可被用来区分拒绝原因，
#: 与「四种拒绝不可区分」的纪律冲突（`test_rejection_message_does_not_distinguish_reasons`
#: 抓到了这一点）。
#:
#: 现在的分工：表单层只负责把这个字段送进来，一切判定（形状、存在性、状态）
#: 都交给原子占用那一步，从而四种拒绝共用同一条消息。

#: 一切「注册被拒」共用的唯一消息。
#:
#: 集中成常量而不是在多处写字面量：消息一旦分叉，就构成账号枚举渠道
#: （见 :func:`_reject`）。有测试断言四种拒绝的响应体完全一致。
#:
#: ⚠️ 2026-10-07（C-3/C-4）后，它的覆盖面**已超出邀请码**：除原有的四类邀请码拒绝
#: （缺失 / 不存在或形状不合法 / 已撤销 / 已占用）外，**租户不存在**与**账号名已被占用**
#: 也共用它。这是**刻意的**，不是命名失准：
#:   - 「租户不存在」若给一个可区分的响应，就成了租户存在性预言机（C-3）；
#:   - 「账号名已被占用」原先走 `FIELD_ERROR`，与四类拒绝形状不同，配合 SDK 的测试
#:     邮箱域可以**不建号、不消耗码**地判定一张候选码是否有效（C-4）。
#: 两处都靠「响应体逐字相同」关闭可区分性，而**逐字相同**要求 `status` 与 `message`
#: 都不分叉——因此只能共用同一个常量。代价（尤其是「账号名重复」的可见文案被改成
#: 「邀请码无效」）已在各自的落点写明。
_REJECTION_MESSAGE = "邀请码无效或已不可用"

#: 账号名为空或纯空白时的表单错误文本。
#:
#: 刻意写实：空账号名会建出一个无法登录、也无法被使用者理解的账号，
#: 且 `AC-16` 已经去掉了邮箱字段（界面只有一个「账号名」输入框），
#: 「请填写账号名」是可据以自救的提示。
#:
#: 它**不构成账号枚举**渠道：消息只取决于调用方自己发来的字符串是否为空，
#: 与账号是否存在于身份服务无关（与邀请码拒绝消息的取舍不同，见 `_REJECTION_MESSAGE`）。
#:
#: ⚠️ 实测这条消息**不会真的发给使用者**（保留作直接调校验器的语义说明）：
#: 身份服务在调用 `validate` 之前就把空值判掉了——`api/utils.py:47-52` 对
#: 「缺失或值为 `""`」且 `optional=False` 的字段直接产出 `Field is not optional`
#: 并 `continue`，校验器根本不会被调用；且 email 字段在 `:105-106` 先被 `strip()`，
#: 所以 `"  "` 也先变成 `""`、同样在 `validate` 之前被拒。
#: 即「拒绝空/纯空白」这件事由 SDK 的非可选判定与归一化共同承担，见 :func:`_validate_account_name`。
_EMPTY_ACCOUNT_NAME_MESSAGE = "请填写账号名"


async def _validate_account_name(value: str, _tenant_id: str) -> str | None:
    """账号名校验器：接受任意非空字符串，拒绝空与纯空白（`RQ-ACC-05`）。

    这是「账号名」与「邮箱」的分界点（见模块说明）：SDK 对 `id == "email"` 的字段
    **给了 `validate` 就用它**，只有不给时才回落 `default_email_validator`
    （实测 `recipe/emailpassword/utils.py:111-119`）。因此本函数的存在本身
    就移除了「必须含 `@`」的正则约束，而**不需要**改 SDK 或共享层。

    为什么在这里显式判空（即使 SDK 已经拦住了）：
    `InputFormField.optional` 对 `id == "email"` 的分支被 SDK **硬编码忽略**
    （`utils.py:117-119` 恒传 `False`，见 :func:`sign_up_form_fields` 的说明），
    即「拒绝空值」实际靠 SDK 的非可选判定。把判空写进本函数，
    是为了让 `validate` 自身也是安全的——校验器将来若被别处直接调用
    （或 SDK 某版本改变归一化顺序），空账号名仍被拒绝，而不是静默放行
    `""` 建出一个无法登录的账号。两处判空不冲突：SDK 先拒，本函数是兜底。

    归一化注记：入参可能仍是带空白的字符串（SDK 只对 email 字段 `strip()`，
    见 `api/utils.py:105-106`），因此用 `strip()` 判空而不是只比 `""`。

    Args:
        value: 账号名原值（身份服务的表单字段值）。
        _tenant_id: SDK 契约要求的租户标识；本校验与租户无关，刻意忽略。

    Returns:
        `None` 表示通过；否则返回给使用者看的错误文本。
    """
    if not isinstance(value, str) or not value.strip():
        return _EMPTY_ACCOUNT_NAME_MESSAGE
    return None


def sign_up_form_fields() -> list[InputFormField]:
    """声明 signup 表单额外的自定义字段（邀请码）与账号名字段。

    这一步不能省：实测 SDK 的 `validate_form_or_throw_error` 在
    `len(config_form_fields) < len(inputs)` 时直接抛
    `Are you sending too many formFields?`——即未声明的字段会让请求在校验阶段
    就被拒，我们的复写（:func:`api_overrides`）根本不会被调用。
    第一版实现漏了它，实测表现是「带邀请码注册返回 400，而复写里的日志一条都没有」。

    邀请码字段的 `optional=True` 且校验器恒通过（见上方常量的说明）：
    - `optional=True`：缺失邀请码时走到我们自己的拒绝分支（统一消息），
      而不是让 SDK 报「字段不能为空」——后者泄露字段存在性且响应形状不同；
    - 校验器恒通过：所有判定集中在原子占用那一步，保证四种拒绝响应完全一致。
    **本次改动刻意不动它**（见下方「为什么不改邀请码字段」）。

    账号名字段（`EMAIL_FORM_FIELD`，承载账号名）为什么必须在这里声明：

    - **覆盖默认邮箱校验器**：不声明该字段时，SDK 会自动补一个 `email` 字段并挂上
      `default_email_validator`（要求含 `@`），`小安`/`xiaoshi`/`a@b` 全被拒——
      这就是 `PROD-01`。声明并给出 `validate` 后，默认正则不再生效。
    - **sign-in 会复用同一个校验器（已实测，不是推断）**：sign-in 的字段表由
      sign-up 的字段表派生，对 `email` 取的是同一个 `validate`
      （`utils.py:160-175`，`y.validate if y.id == FORM_FIELD_EMAIL_ID`）。
      探针实测两者是**同一个函数对象**：`signup_email.validate is signin_email.validate`
      为 `True`。因此本声明同时修好注册与登录，**不会**出现「能注册但登录不了」。
    - 同一份校验器还被密码重置的「生成 token」表单复用（`utils.py:206-213`）；
      对「任意非空账号名」而言这是正确行为——重置链接必须能发给非邮箱账号名。

    为什么不设 `optional`：账号名是必填。刻意显式写 `optional=False` 表达意图并
    留下文档锚点，尽管实测它对 `id == "email"` 无实际作用——SDK 在该分支
    **忽略**传入的 `optional`，恒按非可选处理（`utils.py:117-119` 硬编码 `False`）。
    即「必填」的真实承重点在 SDK 的非可选分支，这里写下来是为了让意图可读、
    并让「哪天 SDK 改了这条」这件事有一个明确的检查点。

    为什么不改邀请码字段的校验器去「顺手」处理账号名：两者职责不同。
    邀请码恒通过是**有意**的（判定集中在原子占用，保证四种拒绝同形）；
    账号名是另一件事，改它会把表单层拒绝引入邀请码路径，破坏 `:85` 那条既约。

    Returns:
        自定义字段声明列表（邀请码 + 账号名）。顺序无关：身份服务按 `id` 查字段
        （`api/utils.py:44-46` 用 `find_first_occurrence_in_list`）。
    """

    async def accept_any_string(_value: str, _tenant_id: str) -> str | None:
        """恒通过：判定不在此层（见上方说明）。"""
        return None

    return [
        InputFormField(
            id=INVITE_CODE_FORM_FIELD,
            validate=accept_any_string,
            optional=True,
        ),
        InputFormField(
            id=EMAIL_FORM_FIELD,
            validate=_validate_account_name,
            # 账号名必填：显式写出意图。实测该值对 email 字段不生效
            # （SDK 硬编码非可选），见 docstring 的说明。
            optional=False,
        ),
    ]


def _field_value(form_fields: list[FormField], field_id: str) -> str | None:
    """从表单字段里取某个字段的值；不存在返回 `None`。

    表单字段是外部输入（`CORE-04` 数据边界），因此逐项校验类型，
    而不是假设 SDK 一定给字符串。`FormField.value` 的静态类型是 `str`
    （SDK 声明），但边界处的实际值由请求决定，调用方（如邮箱）须自行
    `isinstance` 复核——见 :func:`_account_exists` 的用法。
    """
    for field in form_fields:
        if field.id == field_id:
            value = field.value
            return value if isinstance(value, str) else None
    return None


class InviteCodeRequired(Exception):
    """注册请求缺少邀请码字段或字段为空。

    单独成型（而不是复用 `InviteCodeError`）：这是请求形状问题，
    与「码无效」是两件不同的事，且它不该触发补偿释放（那时还没有占用任何码）。
    """

    def __init__(self, detail: str) -> None:
        """记录原因（不含邀请码本身——它是准入凭据）。"""
        self.detail = detail
        super().__init__(f"注册请求缺少有效的邀请码：{detail}")


def _reject(message: str) -> GeneralErrorResponse:
    """构造一个面向使用者的明确拒绝响应。

    不区分具体原因（第 5 节与 `errors.InviteCodeRejectedError` 的说明）：
    「码缺失 / 不存在 / 过期 / 已用 / 已撤销」共用同一条消息，否则拒绝本身成为
    账号枚举渠道。

    签名注记：`GeneralErrorResponse` 只接受 `message`，`status` 是它内部
    写死的 `"GENERAL_ERROR"`（实测源码）。第一版误传了 `status=`，实测抛
    `TypeError: unexpected keyword argument 'status'`——那会让拒绝路径本身崩成 500，
    比「拒绝理由可区分」更糟。

    HTTP 状态注记：身份服务用 HTTP 200 + 响应体里的 `status` 字段表达
    业务结果（实测：拒绝是 `200 {"status":"GENERAL_ERROR",...}`）。这不是我们的
    选择，是 SDK 的线格式；调用方与测试都必须按响应体判断成败，不能只看状态码。
    """
    return GeneralErrorResponse(message=message)


async def _claim_invite_code(raw_code: object) -> str:
    """原子占用邀请码并在独立事务里提交，返回归一化后的码。

    为什么独立提交：见模块说明的「一处必须写明的顺序约束」。占用是个独立的
    存储事实，必须早于建号落地，否则崩溃窗口会让同一个码建出两个账号。

    Raises:
        InviteCodeRequired: 未提供邀请码（请求形状问题）。
        InviteCodeError: 码无效/过期/已用/已撤销，或形状不合法。
    """
    if raw_code is None or raw_code == "":
        raise InviteCodeRequired("缺少邀请码字段或字段为空")

    async with session_scope(get_settings()) as session:
        claimed = await claim_invite_code(session, code=raw_code)
    # 归一化形态由仓储层保证；这里取回它以便后续绑定与释放用同一个值。
    return claimed.code


async def _bind_account(code: str, account_id: str) -> bool:
    """把已占用的码绑定到建好的账号（第 4 节步骤 2 成功后的回填）。

    失败不抛给使用者，但必须如实返回：账号已经建好了，此时报错会让人以为注册
    失败而重试，而重试会因「账号已存在」失败——用户陷入死循环。因此这里记录并返回
    `False`，让调用方知道「绑定的前提是账号确实存在」。

    返回值的用途（2026-09-30 审查修正）：绑定失败会留下
    「码已占用且账号已建、但 `used_by_account_id` 为空」的行，其形状与
    「码已占用但账号未建」完全相同。因此调用方不得据此释放码
    ——那会放行一次真实占用（见 :func:`api_overrides` 的说明）。
    这里返回 `False` 只用于日志与让上层明确知道「不该释放」。

    Returns:
        True 表示绑定成功；False 表示绑定失败（已记日志）。
    """
    try:
        async with session_scope(get_settings()) as session:
            await bind_invite_code_account(session, code=code, account_id=account_id)
    except AccountsError:
        logger.warning("邀请码绑定账号失败（账号已建，注册继续）：code=%s", code, exc_info=True)
        return False
    return True


async def _release_quietly(code: str) -> None:
    """补偿释放（第 4 节步骤 3），失败只记日志。

    为什么不让释放失败掩盖原始错误：调用方走到这里是因为建号失败，
    那才是使用者需要知道的原因。若释放本身再抛异常，原始错误会被替换成一个
    更难理解的内部错误（「释放失败」而不是「账号名已被占用」）。
    释放失败本身是需要运维关注的（会出现一张无法自动回收的已占用码），故记日志。

    ⚠️ 调用方必须先确认「账号肯定没被建出来」：见 :func:`_account_exists`
    与 :func:`api_overrides` 的说明——「建了号却没回填」与「没建号」在库里
    长得一样，误放行会破坏「一码只用一次」。
    """
    try:
        async with session_scope(get_settings()) as session:
            await release_invite_code(session, code=code)
    except AccountsError:
        logger.error(
            "补偿释放邀请码失败——该码会停在已占用状态，需运营按 code 查核处理：code=%s",
            code,
            exc_info=True,
        )


async def _account_exists(email: object) -> bool:
    """直接问身份服务：该账号名现在是否存在。

    为什么必须有这个能力（2026-09-30 审查发现的重要缺陷的修复点）：

    第 4 节的补偿释放依赖「建号失败」这一判据，而「原实现返回了非 OK 结果」
    不等于「没有建号」。实测已装 SDK 的源码（`recipe/emailpassword/api/implementation.py`）：

    - `:738` 先调 `recipe_implementation.sign_up(...)` —— 账号在这一步已经建好；
    - `:755` 然后跑 `post_auth_checks`；
    - `:766` 该检查不通过时返回 `SignUpPostNotAllowedResponse`（非 OK）。

    因此存在一条真实路径：账号已建，但结果不是 OK。修复前代码对此无条件
    释放邀请码，于是同一个码可以再建一个账号——「一码只用一次」（`AC-15`）被破坏，
    且第一张码的记录会被第二次绑定覆盖，运营看不出发生过两次注册。

    为什么用 `list_users_by_account_info`：

    实测它在「已存在」时返回含一个用户的列表、不存在时返回空列表
    （探针：`list [['dbg-...@x.test']]` vs `list []`）——这是确定性的、
    由身份服务自己回答的判据，不依赖我们的推断。

    Raises:
        不抛异常：查询失败时返回保守值（见下），因为抛异常会把「无法确认」
        变成「注册失败」，而那时账号可能已经建好了。
    """
    from supertokens_python.asyncio import list_users_by_account_info
    from supertokens_python.types.base import AccountInfoInput

    if not isinstance(email, str) or not email:
        return False
    try:
        users = await list_users_by_account_info("public", AccountInfoInput(email=email))
    except Exception:  # noqa: BLE001 —— 查不动时按「存在」处理，见下方说明
        # 保守方向：返回 True（当作已建号），从而不释放邀请码。
        # 理由是不对称的代价：不释放只是让一张码停在已占用（运营可查、可撤销重发，
        # 第 4 节明确该状态安全）；误释放则会放行一次真实占用、破坏一次性。
        logger.error("无法确认账号是否存在，按「已存在」保守处理（不释放邀请码）", exc_info=True)
        return True
    return len(users) > 0


async def _tenant_exists(tenant_id: object) -> bool | None:
    """问身份服务：该租户是否存在。三态返回，`None` 表示**判定不了**。

    为什么必须有这个能力（C-3，2026-10-07 用户裁决「补 4xx」）：

    身份服务在租户不存在时抛的是**裸 `Exception`**，不是某个可 `isinstance`
    的业务异常——实测源码 `.venv/.../supertokens_python/auth_utils.py:865-869`：

        if valid_res == "TENANT_NOT_FOUND_ERROR":
            if has_session:
                raise UnauthorisedError("Tenant not found")
            else:
                raise Exception("Tenant not found error.")   # ← 注册路径走这一支

    因此「按异常类型识别」不可行，而「按异常消息字符串识别」是脆的（SDK 改字即失效，
    且失败方向是静默的：识别不到就退回裸 500）。本函数改用 SDK 自己的**语义**判据：
    `get_tenant` 对 `TENANT_NOT_FOUND_ERROR` 返回 `None`
    （`recipe/multitenancy/recipe_implementation.py:183-184`），不依赖任何字符串。

    为什么是三态而不是 `bool`：

    「查不动」与「不存在」必须分开。若把查询失败当成「不存在」，调用方会据此把它当
    业务拒绝返回——而真实原因可能是 core 抖动，此时**账号可能已经建出来了**，
    谎报「邀请码无效」会把用户引向重试（重试再因账号已存在失败，死循环）。
    实测（真 core，原证物 `probes/t40/probe_tenant_api.py`）：`public` → `TenantConfig`；
    `t40-unknown-tenant` → `None`。

    Args:
        tenant_id: SDK 交给复写的租户标识（来自 URL 路径的第 1 段，见
            `recipe_module.py:63-77`）。

    Returns:
        `True` 存在；`False` 确定不存在；`None` 无法判定（查询抛异常）。
    """
    from supertokens_python.recipe.multitenancy.asyncio import get_tenant

    if not isinstance(tenant_id, str) or not tenant_id:
        return None
    try:
        config = await get_tenant(tenant_id)
    except Exception:  # noqa: BLE001 —— 判定不了就如实返回 None，绝不猜成「不存在」
        logger.warning(
            "无法确认租户是否存在（按「判定不了」处理，不改变异常路径）：tenant=%s", tenant_id, exc_info=True
        )
        return None
    return config is not None


def make_sign_up_override(
    original: OriginalSignUpPost,
) -> OriginalSignUpPost:
    """包装身份服务原始的 `sign_up_post`，注入邀请码校验。

    归属：`modules/accounts`（见 docs/项目结构设计.md 第 6 节）。
    形状与可用性不变量由认证与账号（docs/技术设计/technical-details/认证与账号.md）
    第 4 节拥有。

    为什么是「复写 sign-up API」而不是自建注册端点：

    第 4 节 2026-09-29 定：把邀请码作为该 API 的自定义表单字段，在复写法内先校验
    邀请码、通过后调用原实现建号。理由——这是「校验在我们自己的后端代码里」与
    「不自己实现建号与会话签发」同时成立的唯一低成本形状。自建注册端点并禁用
    身份服务的 signup 路由，要求我们自己签发 session、自己设置 cookie，与
    技术栈设计（docs/技术栈设计.md）第 2 节「换取不自己实现会话安全」
    的选型理由相悖。

    为什么是「包装原实现」而不是「自己实现建号」：

    原实现负责建号、密码校验、会话签发与 cookie 设置——这些正是我们不想自己写
    的部分（技术栈设计第 2 节的选型理由）。本函数只做一件事：在调用它之前
    先占用邀请码，并在它失败时补偿释放。

    可用性不变量（第 4 节，2026-09-29 修正版）：

    原文写「同一事务」，该写法不成立——建号发生在 SuperTokens core 这个独立进程内，
    我们本库的事务无法跨进程覆盖它。可实现且必须遵守的形状是三步：

    1. 先在本库原子占用邀请码（条件更新，见 `repository.claim_invite_code`）；
    2. 占用成功后才调用建号（本模块调原实现）；
    3. 建号失败则补偿释放（`repository.release_invite_code`）。

    它保证的是「无效码绝不建号」（第 1 步就拒绝，不触碰身份服务）与
    「一码只用一次」，而不是跨进程原子性。第 2 步成功而第 3 步之前崩溃，
    会留下「码已占用但账号未建」——该状态安全（拒绝二次使用），由运营在撤销/重发时
    处理，不在请求路径内自动回收（第 4 节明文）。

    一处必须写明的顺序约束：

    占用必须先于建号，且占用要独立提交。若两者同属一个未提交事务，则在「core 已
    建号」与「事务提交」之间崩溃时，占用从未落库——同一个码可以再次被使用，建出
    第二个账号（`AC-15` 被静默破坏）。因此本模块的复写函数自己提交占用（用
    `session_scope`），而不是把占用挂到调用方的事务上。

    为什么校验失败时「不调用原实现」：

    这是「无效码绝不建号」的落点（第 4 节）：校验不通过在第 1 步就返回，
    因此身份服务完全不参与，不会留下任何用户记录。
    `test_auth_registration_integration.py` 有一个用例专门断言这一点。

    Args:
        original: SDK 的原始 `sign_up_post` 实现（签名见 `APIInterface`）。

    Returns:
        可赋给 `APIInterface.sign_up_post` 的包装函数。
    """

    async def sign_up_post(
        form_fields: list[FormField],
        tenant_id: str,
        session: Union[SessionContainer, None],  # noqa: UP007 —— 与 SDK 签名保持一致
        should_try_linking_with_session_user: Union[bool, None],  # noqa: UP007
        api_options: APIOptions,
        user_context: dict[str, object],
    ) -> SignUpPostResult:
        """先校验并占用邀请码，通过后交给原实现建号。"""
        raw_code = _field_value(form_fields, INVITE_CODE_FORM_FIELD)

        # --- 第 1 步：原子占用（无效即拒绝，且不触碰身份服务）---
        try:
            code = await _claim_invite_code(raw_code)
        except (InviteCodeRequired, InviteCodeError):
            # 所有拒绝共用同一条消息（不可枚举）：见 `_reject` 的说明。
            #
            # 这里刻意把 `InviteCodeRequired`（缺失字段）与 `InviteCodeError`（码无效）
            # 合并到同一个 except——第一版把它们分开了，缺失字段返回的是
            # 「注册请求缺少有效的邀请码：…」，与其它三种拒绝的消息不同。
            # 实测该差异可被外部区分（`test_rejection_message_does_not_distinguish_reasons`
            # 抓到）：调用方据此就能判断「这个字段名是对的、只是没填」，
            # 而下一步就能试探码的存在性。
            #
            # 也刻意不透出原异常的消息：它可能含形状细节（如「含字符集外的字符」），
            # 那同样是可用于推断的信息。
            return _reject(_REJECTION_MESSAGE)

        # --- 第 2 步：调用原实现建号 ---
        try:
            result = await original(
                form_fields,
                tenant_id,
                session,
                should_try_linking_with_session_user,
                api_options,
                user_context,
            )
        except Exception:
            # 建号抛异常时也要走与非 OK 分支同一套判据：先确认账号没建出来，
            # 再决定是否释放。
            #
            # ⚠️ 这里曾是一个阻断级缺陷（2026-09-30 评审抓出，与前面非 OK 分支
            # 同源）：原实现无条件释放。而 SDK 的顺序是
            # `implementation.py:738` 建号 → `:755` `post_auth_checks` → 再
            # `create_new_session`——建号之后仍有会抛异常的步骤。
            # 因此存在真实路径：「账号已建、随后抛异常」→ 码被退回 `issued`
            # → 同一张码再建第二个账号（`AC-15` 破坏）。
            # 评审实测复现：劫持 `create_new_session` 令其抛错，走完整 HTTP 注册，
            # 得到「账号已建但码回到 issued」。
            #
            # 判据与非 OK 分支共用 `_account_exists`（直接问身份服务），
            # 而不是看 `used_by_account_id`——后者在占用时必然是 NULL，无法区分
            # 「还没建号」与「建了号但没回填」。
            #
            # --- C-3（2026-10-07 用户裁决「补 4xx」）---
            # 上面那套判据回答的是「要不要释放」，**不回答「给调用方什么响应」**：
            # 它之后原样 `raise`，于是异常冒泡成**匿名可达的裸 500**——而触发它的
            # 条件（把租户名换成 URL 路径的一段）完全由调用方控制，因此 500 本身
            # 就是「该租户不存在」的信号：
            #     实测（真 uvicorn + 真 core，原证物 `probes/t40/probe-before.json`）
            #     POST /api/auth/t40-unknown-tenant/signup + 有效码 → HTTP 500
            #     `Internal Server Error`；同一张码改打 /api/auth/（public）→ 200 OK。
            # SDK 抛的是**裸 `Exception`**（`auth_utils.py:869`），所以这里只能用
            # `_tenant_exists` 的语义判据识别，不能用异常类型。
            #
            # 刻意的形状选择：**与四类邀请码拒绝逐字同形**（`_reject(_REJECTION_MESSAGE)`），
            # 而不是另造一个 4xx。理由是任务判据本身——若给「租户不存在」一个可区分的
            # 响应，就只是把裸 500 换成一个**更明显的**租户存在性预言机
            # （500 至少不告诉你这是业务拒绝）。同形之后，未知租户在响应上与
            # 「码无效」不可区分，可探测性被收敛回与邀请码同一档。
            #
            # 释放语义为什么在这里是安全的：`get_tenant` 为 None 意味着该租户不存在，
            # 而账号只能建在租户里 ⇒ **本次不可能建出账号**，这张码没有被真实使用，
            # 必须释放（否则每次探测都白白烧掉一张码，变成对运营的 DoS）。
            # ⚠️ 这也正是不能把「判定不了」（`_tenant_exists` 返回 None）并入这一支的
            # 原因：那时账号**可能**已经建出来了，释放会放行一次真实占用。
            if await _tenant_exists(tenant_id) is False:
                logger.warning("signup 打到不存在的租户——按统一拒绝响应返回（不外泄租户存在性）：tenant=%s", tenant_id)
                await _release_quietly(code)
                return _reject(_REJECTION_MESSAGE)

            if not await _account_exists(_field_value(form_fields, EMAIL_FORM_FIELD)):
                await _release_quietly(code)
            else:
                logger.warning(
                    "建号已发生但后续步骤抛异常——**不释放邀请码**（该码已被真实使用）：code=%s",
                    code,
                )
            raise

        # --- 第 3 步：按结果决定「回填」还是「补偿释放」---
        if isinstance(result, SignUpPostOkResult):
            user_id = getattr(result.user, "id", None)
            if isinstance(user_id, str) and user_id:
                await _bind_account(code, user_id)
            else:  # pragma: no cover
                # 建号成功但拿不到 id，属 SDK 契约异常。
                logger.error("建号成功但结果里没有用户标识，邀请码未绑定：code=%s", code)
            return result

        # --- 非 OK 结果：必须先确认账号真的没建出来，再决定是否释放 ---
        #
        # 不是多余的谨慎：实测已装 SDK 的源码
        # （`recipe/emailpassword/api/implementation.py`）顺序是
        #   `:738` 建号 → `:755` post_auth_checks → `:766` 不通过则返回非 OK。
        # 即存在「账号已建、结果却不是 OK」的真实路径。无条件释放会放行一次真实占用，
        # 于是同一个码可以再建一个账号——「一码只用一次」（AC-15）被破坏，
        # 且第一张码的记录会被第二次绑定覆盖，运营看不出发生过两次注册。
        #
        # 判据用 `_account_exists`（直接问身份服务），不是用
        # `used_by_account_id`：那个列在占用时必然是 NULL（第 4 节的顺序决定），
        # 因此它无法区分「还没建号」与「建了号但没回填」。
        #
        # 先排除「账号本来就在」这一情形：`EmailAlreadyExistsError` 意味着该账号名
        # 在本次请求之前就存在，因此本次没有建号，释放是安全的。
        # 少了这一步会把「重名注册」这条正常路径也判成「已用掉」——
        # 实测（`test_duplicate_account_name_releases_the_code`）：被拒的码停在 `used`，
        # 使用者必须重新索码。`_account_exists` 单独用无法区分这两种情形
        # （重名时它同样返回 True），这正是需要先分类结果类型的原因。
        if isinstance(result, EmailAlreadyExistsError):
            await _release_quietly(code)
            # --- C-4（2026-10-07 用户裁决「改实现，让第五条也同形」）---
            # 原先这里 `return result`，于是它继续走 SDK 的渲染，落在
            # `raise_form_field_exception("EMAIL_ALREADY_EXISTS_ERROR", …)`
            # （`recipe/emailpassword/api/signup.py:99-108`）⇒ 线格式是
            # `200 {"status":"FIELD_ERROR","formFields":[…]}`，与四类邀请码拒绝的
            # `200 {"status":"GENERAL_ERROR","message":…}` **形状不同**。
            #
            # 那个差异可被匿名利用（邀请码有效性预言机）：
            # SDK 的 `is_fake_email`（`auth_utils.py:971-974`）对
            # `@stfakeemail.supertokens.com` 为真，而 `implementation.py:734-736`
            # 在该域且为首因子时**直接**返回 `EmailAlreadyExistsError()`——
            # **不查库、不建号、不消耗邀请码**。而第 1 步（占用邀请码）先于它执行，
            # 因此本分支只在**码有效**时可达 ⇒ 它的出现本身证明了「候选码有效」，
            # 而这正是预言机：拿一张候选码打一次即可判定真伪，且不消耗任何资源。
            #
            # 实测（真 uvicorn + 真 core，原证物 `probes/t40/probe-before.json`）：
            #     POST /api/auth/signup  {email: c4-before@stfakeemail.supertokens.com,
            #                             inviteCode: <有效码>}
            #     → 200 {"status":"FIELD_ERROR","formFields":[{"id":"email",…}]}
            #   改动后同一请求（原证物 `probes/t40/probe-after.json`）：
            #     → 200 {"status":"GENERAL_ERROR","message":"邀请码无效或已不可用"}
            #
            # 与四类同形的代价（**如实记下，这是本裁决的用户可见影响**）：
            # 「账号名已被占用」这条**正常路径**的响应从表单错误变成一般错误，
            # 前端 `apps/web/src/infrastructure/auth/authPort.ts:173-187` 按
            # `FIELD_ERROR` + `email` 字段分派，落到 `account-unusable`
            # （文案「该账号名无法使用，请换一个」）。改成 `GENERAL_ERROR` 后，注册
            # 路径上的 GENERAL_ERROR 在**同文件 :91-95** 被统一定为
            # `invite-rejected`（文案「邀请码无效或已被使用」）⇒
            # **使用者重名注册时会看到「邀请码无效或已被使用」，而那是不准确的**：
            # 他的邀请码没问题，问题在账号名。
            #
            # 为什么仍然按裁决做（我认为这个改变**可接受但不理想**）：
            #   1. 重名是**用户可自纠**的（换个账号名即可），且第 2 步占用已成功、
            #      码已在本次失败中被 `_release_quietly` 退回 issued ⇒ 不烧码、
            #      不锁定，用户拿同一张码换名重试即可成功（有既有用例
            #      `test_duplicate_account_name_releases_the_code` 守着这条）；
            #   2. 文案不准确是**可用性**代价，而 C-4 关掉的是**安全**渠道；
            #      两者的方向与不可逆性不同（前者可事后改文案，后者一旦被利用
            #      无法回溯）；
            #   3. 消除差异不引入新的可区分性：改动后五类拒绝的响应体逐字相同。
            # ⚠️ 未决（留给复查者与用户）：更准确的形状是「保留 FIELD_ERROR 的
            # 字段语义、但让它与邀请码拒绝不可区分」——这两件事在 SD K的线格式下
            # 无法同时成立（FIELD_ERROR 必须带 formFields，GENERAL_ERROR 不带），
            # 因此本裁决的实质是**二选一**，我按裁决选了安全侧。前端文案若要跟上，
            # 是另一处改动（`authPort.ts` 的注册分支），不在本包授权范围内。
            return _reject(_REJECTION_MESSAGE)

        account_email = _field_value(form_fields, EMAIL_FORM_FIELD)
        if await _account_exists(account_email):
            logger.warning(
                "建号返回非 OK 但账号已存在——**不释放邀请码**（该码已被真实使用）：code=%s",
                code,
            )
            return result

        # 账号确实不存在：这次占用没有产生账号，补偿释放让该码可再次使用。
        await _release_quietly(code)
        return result

    return sign_up_post


def api_overrides(original: APIInterface) -> APIInterface:
    """把 `sign_up_post` 换成注入邀请码校验的实现，并关闭匿名的账号存在性查询。

    这是交给 `emailpassword.init(override=InputOverrideConfig(apis=...))` 的函数。
    只改这两处：登录与密码重置维持 SDK 原行为——改动它们会引入与本功能无关的差异。

    为什么必须关掉 `disable_email_exists_get`（2026-09-30 评审抓出）：

    SDK 默认挂载 `GET /auth/signup/email/exists`（`disable_email_exists_get`
    默认 `False`），它无需会话即可回答「某个账号名是否已存在」。
    这与认证与账号第 5 节「不区分『账号不存在』与『密码错误』」是同一条纪律的
    反面：该端点把「账号是否存在」直接变成一个匿名可查的布尔值。

    评审实测（真实 uvicorn，非 ASGI 夹具）：已存在 → `200 {"exists":true}`、
    不存在 → `exists:false`——可区分。

    关闭它不影响登录：登录走 `sign_in_post`，不依赖该端点。
    """
    # SDK 的 APIInterface 是抽象类实例；直接改属性即可（官方 override 的既有做法）。
    # method-assign + assignment：给实例属性赋一个与方法同名/同签名的函数，mypy 视为
    # 方法重绑并按精确参数列表校验——而 SDK 官方 override 机制要求的正是这种重绑
    # （包装器的位置形态由 Callable[...] 表达，见 OriginalSignUpPost 的说明），非错误。
    original.sign_up_post = make_sign_up_override(original.sign_up_post)  # type: ignore[method-assign,assignment]  # SDK 官方 override 的既定形态，方法重绑即其机制
    # 关闭匿名的账号枚举端点：见 docstring 的实测依据。
    original.disable_email_exists_get = True
    return original


__all__ = [
    "EMAIL_FORM_FIELD",
    "INVITE_CODE_FORM_FIELD",
    "InviteCodeRequired",
    "api_overrides",
    "make_sign_up_override",
]

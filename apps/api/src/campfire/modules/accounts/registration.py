"""注册（邀请码）：复写身份服务的 sign-up API。

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

表单字段的契约：

邀请码字段名是 :data:`INVITE_CODE_FORM_FIELD`。它同时是前端契约的一部分
（前端须把它作为 signup 请求的自定义字段提交），因此写死在常量里并由测试钉住。
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
INVITE_CODE_FORM_FIELD = "inviteCode"

#: 账号名字段的字段名（身份服务沿用 `email` 字段承载账号名，`TECH-08` 已知偏差）。
#:
#: 刻意不在这里改名：该字段名由身份服务的 SDK 契约决定，我们只读取它。
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

#: 一切邀请码类拒绝共用的唯一消息。
#:
#: 集中成常量而不是在多处写字面量：消息一旦分叉，就构成账号枚举渠道
#: （见 :func:`_reject`）。有测试断言四种拒绝的响应体完全一致。
_REJECTION_MESSAGE = "邀请码无效或已不可用"


def sign_up_form_fields() -> list[InputFormField]:
    """声明 signup 表单额外的自定义字段（邀请码）。

    这一步不能省：实测 SDK 的 `validate_form_or_throw_error` 在
    `len(config_form_fields) < len(inputs)` 时直接抛
    `Are you sending too many formFields?`——即未声明的字段会让请求在校验阶段
    就被拒，我们的复写（:func:`api_overrides`）根本不会被调用。
    第一版实现漏了它，实测表现是「带邀请码注册返回 400，而复写里的日志一条都没有」。

    `optional=True` 且校验器恒通过（见上方常量的说明）：
    - `optional=True`：缺失邀请码时走到我们自己的拒绝分支（统一消息），
      而不是让 SDK 报「字段不能为空」——后者泄露字段存在性且响应形状不同；
    - 校验器恒通过：所有判定集中在原子占用那一步，保证四种拒绝响应完全一致。

    Returns:
        自定义字段声明列表。
    """

    async def accept_any_string(_value: str, _tenant_id: str) -> str | None:
        """恒通过：判定不在此层（见上方说明）。"""
        return None

    return [
        InputFormField(
            id=INVITE_CODE_FORM_FIELD,
            validate=accept_any_string,
            optional=True,
        )
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


def make_sign_up_override(
    original: OriginalSignUpPost,
) -> OriginalSignUpPost:
    """包装身份服务原始的 `sign_up_post`，注入邀请码校验。

    为什么是「包装原实现」而不是「自己实现建号」：

    原实现负责建号、密码校验、会话签发与 cookie 设置——这些正是我们不想自己写
    的部分（技术栈设计第 2 节的选型理由）。本函数只做一件事：在调用它之前
    先占用邀请码，并在它失败时补偿释放。

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
            else:  # pragma: no cover —— 建号成功但拿不到 id，属 SDK 契约异常
                logger.error("建号成功但结果里没有用户标识，邀请码未绑定：code=%s", code)
            return result

        # --- 非 OK 结果：必须先确认账号真的没建出来，再决定是否释放 ---
        #
        # ⚠️ 这不是多余的谨慎（2026-09-30 审查发现的重要缺陷）：
        # 实测已装 SDK 的源码（`recipe/emailpassword/api/implementation.py`）顺序是
        #   `:738` 建号 → `:755` post_auth_checks → `:766` 不通过则返回非 OK。
        # 即存在「账号已建、结果却不是 OK」的真实路径。修复前这里无条件释放，
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
            return result

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
    # method-assign + assignment + arg-type：给实例属性赋一个与方法同名/同签名的
    # 函数，mypy 视为方法重绑并按精确参数列表校验——而 SDK 官方 override 机制
    # 要求的正是这种重绑（包装器的位置形态由 Callable[...] 表达，见
    # OriginalSignUpPost 的说明），非错误。
    original.sign_up_post = make_sign_up_override(original.sign_up_post)  # type: ignore[method-assign,assignment,arg-type]  # SDK 官方 override 的既定形态，方法重绑即其机制
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

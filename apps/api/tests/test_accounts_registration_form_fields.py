"""账号名不强制邮箱格式（`PROD-01` / `RQ-ACC-05`）的表单字段级回归测试。

不需要数据库与身份服务 core：这些用例只读 `sign_up_form_fields()` 的**声明**，
以及身份服务对这些声明的**归一化结果**。它们钉住的是缺陷 `PROD-01` 的根因——
「设计真源要求复写 email 校验器使账号名通过校验，而该复写从未实现」：

身份服务对 `id == "email"` 的字段**给了 `validate` 就用它**，只在不给时才回落
`default_email_validator`（要求含 `@` 的正则）。因此「账号名字段有没有自己的校验器」
就是「账号名是否被强制邮箱格式」的唯一分界点。

判别性（已实测，见 原证物 orchestrator-20261002-001/T16.md 第 5 节）：
把 `sign_up_form_fields()` 里新增的 email 字段删掉 ⇒ 本文件 11 个用例变红
（默认邮箱校验器重新生效，`小安`/`xiaoshi`/`a@b` 全被拒）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Union

import pytest
from supertokens_python.recipe.emailpassword.utils import (
    default_email_validator,
    normalise_sign_in_form_fields,
    normalise_sign_up_form_fields,
)

from campfire.modules.accounts.registration import (
    EMAIL_FORM_FIELD,
    INVITE_CODE_FORM_FIELD,
    sign_up_form_fields,
)

#: 应当被接受为账号名的值（`RQ-ACC-05`：任意非空账号名，含中文、无 `@`）。
ACCEPTED_ACCOUNT_NAMES = [
    "小安",
    "xiaoshi",
    "a@b",
    "tester01@example.test",  # 兼容性：邮箱形态仍须可用（不影响已有账号）
    "  小安  ",  # 非空白内容：首尾空白不构成「空」
    "账号名 with spaces",
    "a",
]

#: 应当被拒绝的值（空或纯空白）——否则会建出「空账号名」这种更坏的状态。
REJECTED_ACCOUNT_NAMES = ["", "  ", "\t\n", " " * 8]

FIELD_VALIDATOR = Callable[[str, str], Awaitable[Union[str, None]]]


def _effective_sign_up_fields():
    """sign-up 在身份服务内的**生效**字段表（归一化之后）。"""
    return normalise_sign_up_form_fields(sign_up_form_fields())


def _effective_sign_in_fields():
    """sign-in 在身份服务内的生效字段表（由 sign-up 字段表派生）。"""
    return normalise_sign_in_form_fields(_effective_sign_up_fields())


def _field(fields, field_id: str):
    """按 id 取字段；缺失即失败（本文件的前提是它必须被声明）。"""
    match = next((field for field in fields if field.id == field_id), None)
    assert match is not None, f"字段 {field_id!r} 未被声明——账号名会回落到默认邮箱校验器（PROD-01）"
    return match


def _account_name_validator() -> FIELD_VALIDATOR:
    """生效的账号名校验器（sign-up 侧）。"""
    field = _field(_effective_sign_up_fields(), EMAIL_FORM_FIELD)
    assert field.validate is not None, "账号名字段没有校验器——默认邮箱校验器会生效（PROD-01）"
    return field.validate


def test_sign_up_form_fields_declares_the_account_name_field() -> None:
    """账号名字段必须被显式声明，且是必填。

    未声明时身份服务会自动补一个 `email` 字段并挂 `default_email_validator`
    （要求含 `@`），于是界面叫「账号名」却只收邮箱——这正是 `PROD-01`。
    """
    account_name_field = _field(sign_up_form_fields(), EMAIL_FORM_FIELD)

    assert account_name_field.validate is not None, (
        "账号名字段没有自己的校验器——身份服务会回落到默认邮箱校验器，小安/xiaoshi/a@b 全被拒"
    )
    assert account_name_field.optional is False, "账号名是必填，optional 必须显式为 False"


def test_default_email_validator_is_not_used_for_sign_up() -> None:
    """★ 承重用例：默认邮箱校验器不得出现在生效的 sign-up 字段表里。

    这条直接对着根因断言，而不是只看「字段存在」：身份服务的分界点是
    「`id == "email"` 的字段有没有 `validate`」。只要默认校验器仍在生效字段表里，
    就说明复写没有生效（`PROD-01` 原样存在）。
    """
    account_name_field = _field(_effective_sign_up_fields(), EMAIL_FORM_FIELD)

    assert account_name_field.validate is not default_email_validator, (
        "生效的账号名校验器仍是身份服务的默认邮箱校验器——账号名被强制邮箱格式（PROD-01）"
    )
    offenders = [field.id for field in _effective_sign_up_fields() if field.validate is default_email_validator]
    assert offenders == [], f"这些字段仍挂着默认邮箱校验器（要求含 @）：{offenders}"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ACCEPTED_ACCOUNT_NAMES)
async def test_account_name_validator_accepts_arbitrary_non_empty_names(value: str) -> None:
    """任意非空账号名通过校验（含中文、无 `@`；邮箱形态兼容）。"""
    error = await _account_name_validator()(value, "public")
    assert error is None, f"账号名 {value!r} 应被接受，实际被拒：{error!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", REJECTED_ACCOUNT_NAMES)
async def test_account_name_validator_rejects_empty_and_whitespace(value: str) -> None:
    """空与纯空白必须被拒——否则会建出无法登录的「空账号名」。"""
    error = await _account_name_validator()(value, "public")
    assert error is not None, f"账号名 {value!r} 是空/纯空白，必须被拒绝，实际通过了"


def test_sign_in_reuses_the_same_account_name_validator() -> None:
    """★ 登录复用注册的校验器：修注册会同时修好登录。

    身份服务对 sign-in 的 `email` 字段取的是 sign-up 配置里的同一个 `validate`
    （`utils.py:160-175`：`y.validate if y.id == FORM_FIELD_EMAIL_ID`）。
    这条断言两者是**同一个函数对象**，从而「能注册但登录不了」不可能发生；
    `test_sign_in_accepts_a_non_email_account_name` 用行为再验一次。

    判别性：撤回 sign-up 的账号名字段 ⇒ 这里拿到的是默认邮箱校验器，用例失败。
    """
    sign_up_field = _field(_effective_sign_up_fields(), EMAIL_FORM_FIELD)
    sign_in_field = _field(_effective_sign_in_fields(), EMAIL_FORM_FIELD)

    assert sign_in_field.validate is sign_up_field.validate, (
        "sign-in 与 sign-up 用的不是同一个账号名校验器——会出现「能注册但登录不了」"
    )
    assert sign_in_field.validate is not default_email_validator


@pytest.mark.asyncio
async def test_sign_in_accepts_a_non_email_account_name() -> None:
    """登录侧行为验证：非邮箱账号名在 sign-in 的表单校验里也通过。"""
    sign_in_field = _field(_effective_sign_in_fields(), EMAIL_FORM_FIELD)
    assert sign_in_field.validate is not None

    assert await sign_in_field.validate("小安", "public") is None
    assert await sign_in_field.validate("", "public") is not None


@pytest.mark.asyncio
async def test_sign_in_rejects_blank_account_name() -> None:
    """登录侧也不接受空账号名（sign-in 复用同一校验器）。"""
    sign_in_field = _field(_effective_sign_in_fields(), EMAIL_FORM_FIELD)
    assert sign_in_field.validate is not None

    for value in REJECTED_ACCOUNT_NAMES:
        assert await sign_in_field.validate(value, "public") is not None, f"{value!r} 必须被拒"


@pytest.mark.asyncio
async def test_invite_code_field_behaviour_is_unchanged() -> None:
    """邀请码字段的行为不得被本次改动改变（`optional=True` + 恒通过）。

    这是刻意的设计（见 `sign_up_form_fields` 的说明）：判定集中在原子占用那一步，
    才保证「四种邀请码拒绝响应完全一致」。若有人「顺手」给它加上非空/长度校验，
    拒绝形状会分叉，本用例失败。
    """
    invite_field = _field(sign_up_form_fields(), INVITE_CODE_FORM_FIELD)

    assert invite_field.optional is True, "邀请码必须 optional=True：缺失时走我们自己的统一拒绝，而不是 SDK 的字段错误"
    assert invite_field.validate is not None

    for value in ["", "  ", "ABC", "ZZZZZZZZ", "任意字符串"]:
        error = await invite_field.validate(value, "public")
        assert error is None, f"邀请码校验器必须恒通过（判定在原子占用那一步），{value!r} 却被拒：{error!r}"

    effective_invite = _field(_effective_sign_up_fields(), INVITE_CODE_FORM_FIELD)
    assert effective_invite.optional is True, "归一化后邀请码仍须是可选字段"


def test_account_name_field_is_not_optional_after_normalisation() -> None:
    """归一化之后账号名仍是必填（空值由 SDK 的非可选分支拒绝）。"""
    field = _field(_effective_sign_up_fields(), EMAIL_FORM_FIELD)
    assert field.optional is False


def test_declared_fields_cover_the_signup_payload() -> None:
    """前端提交的字段都必须被声明——未声明的字段会让请求在复写之前被拒。

    `api/utils.py:40-41`：`len(config_form_fields) < len(inputs)` 时直接
    `Are you sending too many formFields?`。这条钉住「账号名与邀请码都在声明里」。
    """
    declared_ids = {field.id for field in sign_up_form_fields()}
    assert {EMAIL_FORM_FIELD, INVITE_CODE_FORM_FIELD} <= declared_ids, (
        f"声明里缺少前端会提交的字段，注册请求会在复写之前就失败：声明={sorted(declared_ids)}"
    )

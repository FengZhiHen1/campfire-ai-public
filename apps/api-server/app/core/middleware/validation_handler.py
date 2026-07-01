"""SEC-05 输入校验防护 — 自定义 FastAPI 校验异常处理器。

注册为 @app.exception_handler(RequestValidationError)，拦截 FastAPI
在路由匹配阶段产生的 Pydantic 校验错误，将默认 422 响应格式覆盖为
ValidationErrorResponse 的字段级错误明细格式。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from py_logger import logger
from py_schemas.security.validation_schemas import (
    ValidationErrorItem,
    ValidationErrorResponse,
)

# ---------------------------------------------------------------------------
# Pydantic 错误类型 → reason 机器可读标识映射表
# ---------------------------------------------------------------------------

_ERROR_TYPE_REASON_MAP: dict[str, str] = {
    "missing": "field_required",
    "string_type": "expected_string",
    "int_parsing": "expected_integer",
    "less_than_equal": "value_out_of_range",
    "greater_than_equal": "value_out_of_range",
}


def _extract_constraint(err: dict) -> str:
    """从 Pydantic 错误上下文提取人类可读的约束条件描述。

    Args:
        err: Pydantic 错误条目字典。

    Returns:
        约束条件字符串，无法提取时返回 "field is required"。
    """
    ctx: dict = err.get("ctx", {}) or {}
    err_type: str = err.get("type", "")

    if err_type == "missing":
        return "field is required"

    if err_type in ("less_than_equal", "greater_than_equal"):
        limit = ctx.get("le") or ctx.get("ge")
        if limit is not None:
            direction = "<=" if err_type == "less_than_equal" else ">="
            return f"value {direction} {limit}"

    if "ge" in ctx:
        return f"value >= {ctx['ge']}"
    if "le" in ctx:
        return f"value <= {ctx['le']}"
    if "min_length" in ctx:
        return f"min_length = {ctx['min_length']}"
    if "max_length" in ctx:
        return f"max_length = {ctx['max_length']}"
    if "pattern" in ctx:
        return f"pattern = {ctx['pattern']}"

    # 回退：返回通用描述
    error_type_display = err_type.replace("_", " ")
    return f"constraint: {error_type_display}"


async def _validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """自定义 RequestValidationError 异常处理器。

    遍历 ValidationError.errors()，将每个错误映射为 ValidationErrorItem：
      - field → err["loc"][-1]（最末级字段名）
      - reason → 映射 Pydantic 错误类型为机器可读标识
      - constraint → 从 err["ctx"] 提取约束值

    Args:
        request: FastAPI Request 对象。
        exc: Pydantic RequestValidationError 异常。

    Returns:
        JSONResponse: HTTP 422，响应体为 ValidationErrorResponse 格式。
    """
    errors: list[ValidationErrorItem] = []

    for err in exc.errors():
        loc = err.get("loc", ())
        # 提取最末级字段名，若 loc 为空则使用 "_body"
        field = str(loc[-1]) if loc else "_body"

        err_type = err.get("type", "")
        reason = _ERROR_TYPE_REASON_MAP.get(err_type, err_type)

        constraint = _extract_constraint(err)

        errors.append(
            ValidationErrorItem(
                field=field,
                reason=reason,
                constraint=constraint,
            )
        )

    response_body = ValidationErrorResponse(errors=errors)

    logger.warning(
        service="api-server",
        message="request_validation_failed",
        extra={
            "path": str(request.url.path),
            "method": request.method,
            "error_count": len(errors),
            "errors": [{"field": e.field, "reason": e.reason} for e in errors],
        },
    )

    return JSONResponse(
        status_code=422,
        content=response_body.model_dump(),
    )


def register_validation_handler(app: FastAPI) -> None:
    """将自定义校验异常处理器注册到 FastAPI 应用实例上。

    必须在 FastAPI app 实例上注册（非 router 子实例），确保对所有路由生效。

    Args:
        app: FastAPI 应用实例。

    Returns:
        None
    """
    app.add_exception_handler(
        RequestValidationError,
        _validation_exception_handler,  # type: ignore[arg-type]
    )

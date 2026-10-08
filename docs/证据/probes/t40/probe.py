"""T40 真栈探针：C-3（未知租户 + 有效邀请码）与 C-4（账号名冲突）。

**为什么必须有它**：本包的成功判据第 1、6 条要求「真实请求」、真栈上走一次，
而不是代码链推定。编排者先前只做了推定、没发过真实请求。

用法（先在另一个终端起 uvicorn）：
    uv run python tmp/t40/probe.py <label>
其中 `<label>` 是 `before` 或 `after`，只用于给证据文件命名。

探针发的是**真实 HTTP 请求**（httpx 打到 127.0.0.1:8099），不是 ASGI 直连，
因此它覆盖 uvicorn + SuperTokens 中间件 + 异常冒泡的完整链路——
`裸 500` 这个现象只在真实服务器上才可见（ASGI 直连会原样抛异常，
看不到 SDK 中间件把未处理异常转成 500 的那一步）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8099"
API_BASE_PATH = "/api/auth"
SIGNUP = f"{BASE}{API_BASE_PATH}/signup"

#: 本包探针专用的账号名域，避免与开发库/其它包撞名。
DOMAIN = "t40-probe.test"
PASSWORD = "probePass123"


def _uniq(prefix: str, label: str) -> str:
    """每次运行唯一的账号名——避免残留账号把「未知租户」探针变成重名探针。"""
    return f"{prefix}-{label}-{uuid.uuid4().hex[:8]}@{DOMAIN}"

EVIDENCE = Path(__file__).resolve().parent


async def issue_code(operator: str) -> str:
    """直接经仓储层签发一张可用邀请码（不经 HTTP：邀请码没有对外端点）。"""
    from campfire.core.config import get_settings
    from campfire.core.db import session_scope
    from campfire.modules.accounts import issue_invite_code

    async with session_scope(get_settings()) as session:
        record = await issue_invite_code(session, created_by=operator)
        return record.code


def payload(email: str, code: str | None) -> dict[str, object]:
    """身份服务 signup 的线格式（`formFields` 数组，不是扁平对象）。"""
    fields: list[dict[str, str]] = [
        {"id": "email", "value": email},
        {"id": "password", "value": PASSWORD},
    ]
    if code is not None:
        fields.append({"id": "inviteCode", "value": code})
    return {"formFields": fields}


def summarise(response: httpx.Response) -> dict[str, object]:
    """把响应压成可对照的结构（状态码 + 体原文 + 关键头）。"""
    try:
        body: object = response.json()
    except Exception:  # noqa: BLE001 —— 非 JSON（如 500 的纯文本/空体）也要留住原文
        body = response.text
    return {
        "http_status": response.status_code,
        "body": body,
        "body_raw": response.text[:2000],
        "content_type": response.headers.get("content-type"),
    }


async def main(label: str) -> None:
    """跑完两个场景并把真实请求/响应原文落盘。"""
    out: dict[str, object] = {"label": label, "probes": {}}

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        # ---------- 探针 0：健康（确认栈起来了） ----------
        r = await client.get(f"{BASE}/readyz")
        out["probes"]["readyz"] = summarise(r)

        # ---------- C-3：未知租户 + 有效邀请码 ----------
        # 租户由 URL 路径承载（SDK `recipe_module.py:63-77` 的正则
        # `^{base_path}(?:/([a-zA-Z0-9-]+))?(/.*)$`）：`/api/auth/<tenant>/signup`。
        # 库中只存在 `public`（实测 `select tenant_id from tenants;` → 仅 public）。
        c3_code = await issue_code(f"t40_probe_c3_{label}")
        unknown_tenant = "t40-unknown-tenant"
        c3_email = _uniq("c3", label)
        c3_url = f"{BASE}{API_BASE_PATH}/{unknown_tenant}/signup"
        r = await client.post(c3_url, json=payload(c3_email, c3_code))
        out["probes"]["c3_unknown_tenant"] = {
            "url": c3_url,
            "request": payload(c3_email, c3_code),
            "response": summarise(r),
        }

        # ---------- C-3 对照：已知租户 + 有效邀请码（应成功） ----------
        known_code = await issue_code(f"t40_probe_c3known_{label}")
        known_email = _uniq("c3ok", label)
        r = await client.post(SIGNUP, json=payload(known_email, known_code))
        out["probes"]["c3_known_tenant_ok"] = {
            "url": SIGNUP,
            "request": payload(known_email, known_code),
            "response": summarise(r),
        }

        # ---------- C-3 可探测性对照：未知租户 + 无效码 vs 已知租户 + 无效码 ----------
        r_unknown_bad = await client.post(c3_url, json=payload(_uniq("c3bad", label), "ZZZZZZZZ"))
        out["probes"]["c3_unknown_tenant_bad_code"] = {
            "url": c3_url,
            "response": summarise(r_unknown_bad),
        }
        r_known_bad = await client.post(SIGNUP, json=payload(_uniq("c3bad2", label), "ZZZZZZZZ"))
        out["probes"]["c3_known_tenant_bad_code"] = {
            "url": SIGNUP,
            "response": summarise(r_known_bad),
        }

        # ---------- C-4：账号名冲突（SDK 测试邮箱域，无需已存在账号、不消耗邀请码） ----------
        # `is_fake_email`（auth_utils.py:971-974）对 `@stfakeemail.supertokens.com`
        # 返回 True，而 implementation.py:734-736 在该域且为首因子时直接返回
        # `EmailAlreadyExistsError()` —— 不触碰 core 的建号、不消耗码。
        c4_fake_email = f"c4-{label}-{uuid.uuid4().hex[:8]}@stfakeemail.supertokens.com"
        c4_code = await issue_code(f"t40_probe_c4_{label}")
        r = await client.post(SIGNUP, json=payload(c4_fake_email, c4_code))
        out["probes"]["c4_duplicate_name"] = {
            "url": SIGNUP,
            "request": payload(c4_fake_email, c4_code),
            "response": summarise(r),
            "note": "用 SDK 测试邮箱域触发 EmailAlreadyExistsError（不消耗邀请码）",
        }

        # ---------- C-4 对照：四条邀请码拒绝（应同形 GENERAL_ERROR） ----------
        r = await client.post(SIGNUP, json=payload(_uniq("c4base", label), "ZZZZZZZZ"))
        out["probes"]["c4_baseline_rejection"] = {"url": SIGNUP, "response": summarise(r)}

    # ---------- 形状比较（本探针自己的判据） ----------
    def shape(entry: dict[str, object]) -> dict[str, object]:
        resp = entry.get("response")
        if not isinstance(resp, dict):
            # `readyz` 之类不是 signup 响应，形状汇总里跳过（它不带 `response`）。
            return {"skipped": True}
        body = resp.get("body")
        if isinstance(body, dict):
            return {
                "http_status": resp.get("http_status"),
                "status": body.get("status"),
                "keys": sorted(body.keys()),
            }
        return {
            "http_status": resp.get("http_status"),
            "status": None,
            "keys": [],
            "body_prefix": str(resp.get("body_raw"))[:120],
        }

    out["shapes"] = {name: shape(entry) for name, entry in out["probes"].items()}  # type: ignore[union-attr]

    dest = EVIDENCE / f"probe-{label}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["shapes"], ensure_ascii=False, indent=2))
    print(f"\n证据已落盘：{dest}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "unlabelled"))

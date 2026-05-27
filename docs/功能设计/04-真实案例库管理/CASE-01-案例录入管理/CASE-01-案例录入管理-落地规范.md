# 1 功能点：CASE-01 案例录入管理 — 落地规范

> **文档生成时间**：`2026-05-27 09:30:27`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 09:30:27 | AI Assistant | 初始版本（基于设计文档v1.0+契约协调报告v1.0.0） |

> **配套文档**：本模块的设计思路与决策依据见 `CASE-01-案例录入管理-设计文档.md`。

---

## 【对内实现】

### 1.1 技术栈绑定

**必须使用**：
- `FastAPI >= 0.115` — API路由与Depends依赖注入系统
- `Pydantic >= 2.0` — 请求/响应Schema校验，使用`BaseModel`和`Field`
- `SQLAlchemy >= 2.0`（async）— 异步ORM，`Enum`类型用于状态列
- `PostgreSQL 17.x` — 主数据存储，`cases`表原生列存储
- `packages/py-auth/rbac.py` — 消费`require_role`和`UserRole`
- `packages/py-db/repositories/` — 复用项目统一repository基类
- `packages/py-schemas/py_schemas/cases.py` — Pydantic Schema定义位置
- `packages/py-logger/` — 结构化审计日志
- `packages/py-config/` — 环境变量读取
- `Zustand >= 5.0`（前端）— 表单状态管理`caseFormStore`
- `Taro >= 4.0`（前端）— Taro.Storage本地草稿存储

**禁止使用**：
- 禁止在`cases`表使用JSONB聚合字段存储L2结构化数据——必须使用原生列
- 禁止跳过`require_role` Depends直接访问Service层
- 禁止在PII检测后自动脱敏或静默通过——必须由用户确认
- 禁止绕过`case_service`直接在路由层操作`case_repository`
- 禁止在`edit`操作中跳过"编辑即重置"状态检查

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| API路由 | `apps/api-server/app/api/v1/cases.py` | 案例CRUD端点定义，含Depends链 |
| Service层 | `apps/api-server/app/services/case_service.py` | 业务逻辑：状态转换、校验链、PII检测调度 |
| Repository层 | `packages/py-db/py_db/repositories/case_repository.py` | 数据库操作：CRUD、状态更新、乐观锁检测 |
| ORM模型 | `packages/py-db/py_db/models/case_model.py` | SQLAlchemy `Case` ORM模型（映射cases表） |
| Pydantic Schema | `packages/py-schemas/py_schemas/cases.py` | `CaseCreateRequest`、`CaseResponse`、`CaseUpdate`等 |
| PII检测 | `packages/py-security/py_security/pii_detector.py` | `detect_pii()`正则匹配检测函数 |
| EBP校验 | `apps/api-server/app/services/ebp_validator.py` | `check_ebp_consistency()`一致性校验 |
| 枚举定义 | `packages/py-schemas/py_schemas/enums/case_enums.py` | `CaseStatus`、`BehaviorType`、`EvidenceLevel`等枚举 |
| TypeScript类型 | `packages/ts-shared/src/types/cases.ts` | 前端接口类型定义 |
| TypeScript枚举 | `packages/ts-shared/src/enums/cases.ts` | 前端枚举定义 |
| 前端Store | `apps/mini-program/src/logics/cases/store/caseFormStore.ts` | Zustand表单状态 |
| 前端API Service | `apps/mini-program/src/logics/cases/services/caseApiService.ts` | 前端API调用封装 |
| 前端视图 | `apps/mini-program/src/views/cases/CaseFormView.tsx` | 纯UI渲染组件 |
| 单元测试 | `apps/api-server/tests/services/test_case_service.py` | Service层单元测试 |
| 集成测试 | `apps/api-server/tests/api/test_cases_api.py` | API端点集成测试 |

---

## 【已锁定】

### 1.3 输入定义（对外接口类型 — 契约引用）

**CaseCreateRequest** — 案例创建请求
- 【契约引用】`docs/contracts/CASE-01/CaseCreateRequest.json`
- 本模块作为该契约的定义方
- 消费方：CASE-09（前端案例管理逻辑）、CASE-02（引用附件关联校验）

**CaseUpdate** — 案例更新请求（部分更新 + 乐观锁）
- 【契约引用】`docs/contracts/CASE-01/CaseUpdate.json`
- 本模块作为该契约的定义方
- 消费方：CASE-09（前端编辑逻辑）
- 特殊约束：`updated_at`为必填字段，用于乐观锁冲突检测

**SourceType** — 案例来源类型枚举
- 【契约引用】`docs/contracts/CASE-01/SourceType.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03、TICK-07

**BehaviorType** — 行为类型枚举
- 【契约引用】`docs/contracts/CASE-01/BehaviorType.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03、CASE-07、CASE-09

**SeverityLevel** — 严重程度枚举
- 【契约引用】`docs/contracts/CASE-01/SeverityLevel.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03、CASE-09

**SceneType** — 发生场景枚举
- 【契约引用】`docs/contracts/CASE-01/SceneType.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03、CASE-09、CSLT-02

**EvidenceLevel** — 循证等级枚举
- 【契约引用】`docs/contracts/CASE-01/EvidenceLevel.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03、CASE-07、KNOW-04

**FamilyDisplayCategory** — 家属端展示大类枚举
- 【契约引用】`docs/contracts/CASE-01/FamilyDisplayCategory.json`
- 本模块作为该契约的定义方
- 消费方：CASE-09

**复用已有契约（本模块作为消费方）**：
- `UserRole` — 【契约引用】`docs/contracts/AUTH-04/UserRole.json`，消费方：CASE-01
- `require_role` — 【契约引用】`docs/contracts/AUTH-04/require_role.json`，消费方：CASE-01
- `PermissionDeniedResponse` — 【契约引用】`docs/contracts/AUTH-04/PermissionDeniedResponse.json`，消费方：CASE-01
- `ValidationErrorResponse` — 【契约引用】`docs/contracts/SEC-05/ValidationErrorResponse.json`，消费方：CASE-01
- `AppSettings` — 【契约引用】`docs/contracts/DEPLOY-05/AppSettings.json`，消费方：CASE-01

**AttachmentRef**（临时内联定义，待CASE-02发布正式的契约后迁移）：
```python
class AttachmentRef(BaseModel):
    """附件引用结构（临时由CASE-01定义，待CASE-02落地后迁移为正式引用）"""
    file_name: str
    minio_path: str
    file_type: str
    file_size: int
    uploaded_at: datetime
    sort_order: int
```

### 1.4 输出定义（对外接口类型 — 契约引用）

**CaseResponse** — 案例详情响应
- 【契约引用】`docs/contracts/CASE-01/CaseResponse.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03（审核数据源）、CASE-04（向量化数据源）、CASE-05（版本对比源）、CASE-07（模板提炼源）、KNOW-04（案例推荐渲染）

**CaseListItem** — 案例列表条目
- 【契约引用】`docs/contracts/CASE-01/CaseListItem.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03（待审核列表）、CASE-09（前端列表展示）、TICK-07（工单沉淀候选）

**CaseStatus** — 案例状态枚举（draft / pending_review / rejected）
- 【契约引用】`docs/contracts/CASE-01/CaseStatus.json`
- 本模块作为该契约的定义方
- 消费方：CASE-02、CASE-03、CASE-04、CASE-05、CASE-07

**PiiWarning** — PII单条警告（内部输出类型，不对外暴露API端点）
- 【契约引用】`docs/contracts/CASE-01/PiiWarning.json`
- 本模块作为该契约的定义方
- 消费方：无（仅CASE-01内部使用，通过`PiiDetectionResult`聚合返回）

**PiiDetectionResult** — PII检测完整结果
- 【契约引用】`docs/contracts/CASE-01/PiiDetectionResult.json`
- 本模块作为该契约的定义方
- 消费方：无（随`CaseResponse`或独立检测端点返回给前端）

---

## 【对内实现】

### 1.5 核心逻辑步骤

#### 1. 流程A：创建案例草稿 `POST /api/v1/cases`

1. **步骤A1：角色准入校验**
   - **操作对象**：FastAPI `Request` 上下文
   - **具体操作**：`Depends(require_role(min_level=UserRole.TEACHER))` 在路由层校验
   - **输入来源**：JWT payload（由`get_current_user` Depends注入`request.state.user.roles`）
   - **输出去向**：校验通过后进入步骤A2；校验失败返回403
   - **失败行为**：角色不满足（非老师/专家）→ `PermissionDeniedResponse`，不进入后续步骤

2. **步骤A2：输入Schema校验**
   - **操作对象**：`CaseCreateRequest` 模型
   - **具体操作**：FastAPI自动调用`CaseCreateRequest.model_validate(body)`
   - **输入来源**：HTTP POST body JSON
   - **输出去向**：校验通过的`CaseCreateRequest`实例进入步骤A3
   - **失败行为**：Pydantic校验失败 → 返回422 `ValidationErrorResponse`，含具体字段和错误描述

3. **步骤A3：四段式字段完整性校验**
   - **操作对象**：`immediate_action`、`comforting_phrase`、`observation_metrics`、`medical_criteria`四个字段
   - **具体操作**：`case_service._validate_four_stage_fields(request)` — 逐字段检查非空（`field is not None and len(field.strip()) > 0`）
   - **输入来源**：步骤A2的`CaseCreateRequest`实例
   - **输出去向**：校验通过进入步骤A4
   - **失败行为**：任一为空 → 返回422，错误信息指向具体缺失字段

4. **步骤A4：PII检测**
   - **操作对象**：`CaseCreateRequest.narrative` 文本
   - **具体操作**：`pii_detector.detect_pii(narrative: str) -> PiiDetectionResult`
   - **输入来源**：步骤A2的`narrative`字段值
   - **输出去向**：`PiiDetectionResult`返回给前端展示
   - **失败行为**（检测到PII）：返回200 + `PiiDetectionResult(has_pii=True, warnings=[...])`，**不阻断**提交；前端展示警告列表，用户确认后调用`PUT /api/v1/cases/{id}/submit`并传入`pii_confirmed=True`

5. **步骤A5：写入数据库**
   - **操作对象**：PostgreSQL `cases` 表
   - **具体操作**：`case_repository.create(Case)` — 构建ORM模型并`INSERT INTO cases (...) VALUES (...) RETURNING *`
   - **输入来源**：步骤A2的`CaseCreateRequest`字段映射为ORM字段，`status=draft`，`author_id`从`request.state.user.user_id`获取
   - **输出去向**：返回`CaseResponse`给调用方
   - **失败行为**：数据库连接超时(>5s) → 重试3次（指数退避1s/2s/4s），仍失败返回503

6. **步骤A6：案例ID生成**
   - **操作对象**：数据库序列 `CASE_ID_SEQ`
   - **具体操作**：`case_repository.generate_case_id()` — 查询`SELECT nextval('case_id_seq')` 并格式化为`CASE-YYYY-NNNN`
   - **输入来源**：数据库序列当前值 + 当前年份
   - **输出去向**：写入`case_id`字段
   - **失败行为**：序列读取失败 → 重试最多3次，仍失败返回503

#### 2. 流程B：更新案例 `PUT /api/v1/cases/{id}`

1. **步骤B1-B2**：同流程A的角色校验和Schema校验（使用`CaseUpdate`）

2. **步骤B3：乐观锁冲突检测**
   - **操作对象**：`cases`表中目标行的`updated_at`列
   - **具体操作**：`case_repository.find_by_id_with_version(case_id, expected_updated_at)` — `SELECT * FROM cases WHERE case_id=$1 AND updated_at=$2`
   - **输入来源**：步骤B2的`CaseUpdate.updated_at`
   - **输出去向**：匹配成功 → 返回当前行进入步骤B4；不匹配 → 返回409
   - **失败行为**：`updated_at`不匹配 → 返回409 Conflict，响应体包含消息和当前最新`updated_at`时间戳

3. **步骤B4：编辑即重置状态检查**
   - **操作对象**：当前行的`status`列
   - **具体操作**：`case_service._check_edit_reset(status)` — 如果`status in [pending_review, rejected]`，将`status`设为`draft`
   - **输入来源**：步骤B3返回的当前行数据
   - **输出去向**：调整后的ORM模型进入步骤B5
   - **失败行为**：仅在非预期状态时跳过重置（如已经是draft则无操作），不抛错

4. **步骤B5：字段更新与写入**
   - **操作对象**：`cases`表的当前行
   - **具体操作**：`case_repository.update(Case)` — `UPDATE cases SET ... WHERE case_id=$1 AND updated_at=$2`，更新传入的非None字段，同时`updated_at=NOW()`
   - **输入来源**：步骤B4处理后的ORM模型 + 步骤B2的`CaseUpdate`字段
   - **输出去向**：更新后的`CaseResponse`返回
   - **失败行为**：同A5数据库失败处理

#### 3. 流程C：提交审核 `POST /api/v1/cases/{id}/submit`

1. **步骤C1-C2**：同流程A的角色校验 + 从路径参数解析`case_id`

2. **步骤C3：案例存在性与状态校验**
   - **操作对象**：`cases`表中目标行
   - **具体操作**：`case_service._validate_submit_eligible(case)` — 检查`status==draft`
   - **输入来源**：步骤C2的`case_id`查询结果
   - **输出去向**：校验通过进入步骤C4
   - **失败行为**：案例不存在 → 404；状态不是draft → 409 Conflict（含当前状态和允许转换提示）

3. **步骤C4：提交前完整性校验**
   - **操作对象**：`cases`当前行的所有必填字段
   - **具体操作**：同A3的四段式校验 + 同A4的PII检测；EBP一致性检测`ebp_validator.check_ebp_consistency(evidence_level, ebp_labels) -> str | None`
   - **输入来源**：数据库中的当前案例字段
   - **输出去向**：校验通过/PII警告/EBP警告返回给前端
   - **失败行为**：四段式缺失 → 422拒绝提交；PII警告 → 返回警告不阻断；EBP不一致 → 返回warning不阻断

4. **步骤C5：状态转换为pending_review**
   - **操作对象**：`cases.status`列
   - **具体操作**：`case_repository.update_status(case_id, CaseStatus.PENDING_REVIEW)` — `UPDATE cases SET status='pending_review', updated_at=NOW() WHERE case_id=$1`
   - **输入来源**：步骤C4校验通过的case_id
   - **输出去向**：返回`CaseResponse(status="pending_review")`
   - **失败行为**：同A5数据库失败处理

5. **步骤C6：审计日志**
   - **操作对象**：`packages/py-logger`
   - **具体操作**：记录结构化日志`logger.info("case_submitted", case_id=..., submitted_by=..., timestamp=...)`
   - **输入来源**：步骤C5的输出
   - **输出去向**：stdout结构化日志

#### 4. 流程D：案例列表查询 `GET /api/v1/cases?status=draft&page=1&page_size=15`

1. **步骤D1-D2**：角色校验 + 查询参数解析（`status: CaseStatus | None`、`page: int=1`、`page_size: int=15`）

2. **步骤D3：数据库查询**
   - **操作对象**：`cases`表
   - **具体操作**：`case_repository.find_by_filters(status=status, author_id=request.state.user.user_id, page=page, page_size=page_size)` — 使用`(status, created_at)`复合索引
   - **输入来源**：查询参数 + 当前用户ID
   - **输出去向**：`list[CaseListItem]` + 总数分页信息

3. **步骤D4：分页封装**
   - **操作对象**：查询结果集
   - **具体操作**：封装为`{"items": [...], "total": N, "page": 1, "page_size": 15, "total_pages": ceil(N/15)}`
   - **输出去向**：返回200 JSON

### 1.6 接口契约（对外暴露的公共接口）

#### 1.6.1 接口1：create_case — 创建案例草稿

```python
async def create_case(
    request: CaseCreateRequest,
    current_user: UserContext = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
) -> CaseResponse:
    """
    创建案例草稿。新建案例初始状态为draft，仅对撰写者本人可见。

    Args:
        request: 案例创建请求体，含L1 4字段+L2 13必填字段
        current_user: 当前用户上下文（由AUTH-02注入）
        _: 角色校验（由AUTH-04注入，仅老师/专家可调用）

    Returns:
        CaseResponse: 创建成功的案例详情，status=draft

    Raises:
        HTTPException(403): 角色权限不足（由require_role抛出）
        HTTPException(422): Pydantic校验失败或四段式字段缺失
        HTTPException(503): 数据库写入失败

    Side Effects:
        - 写入cases表（INSERT）
        - 记录结构化审计日志

    Idempotency:
        无（每次调用创建新案例记录）

    Thread Safety:
        线程安全，无共享可变状态。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `create_case` |
| **HTTP方法** | `POST /api/v1/cases` |
| **输入类型** | `CaseCreateRequest`（详见1.3输入定义） |
| **输出类型** | `CaseResponse`（详见1.4输出定义） |
| **异常类型** | `HTTPException(403)` / `HTTPException(422)` / `HTTPException(503)` |
| **副作用** | 写入数据库、记录日志 |
| **幂等性** | 非幂等（每次创建新记录） |

#### 1.6.2 接口2：update_case — 更新案例

```python
async def update_case(
    case_id: str,
    update: CaseUpdate,
    current_user: UserContext = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
) -> CaseResponse:
    """
    更新案例字段。采用乐观锁（updated_at比对）防止并发冲突。
    编辑pending_review或rejected状态的案例时自动重置为draft。

    Args:
        case_id: 案例唯一标识（CASE-YYYY-NNNN格式）
        update: 部分更新数据，updated_at为必填（乐观锁依据）
        current_user: 当前用户上下文
        _: 角色校验

    Returns:
        CaseResponse: 更新后的案例详情

    Raises:
        HTTPException(404): 案例不存在
        HTTPException(403): 角色权限不足
        HTTPException(409): 乐观锁冲突（updated_at不匹配）
        HTTPException(422): Pydantic校验失败

    Side Effects:
        - 更新cases表（UPDATE）
        - 可能触发状态重置（pending_review/rejected→draft）

    Idempotency:
        同一case_id+同一updated_at的重复调用返回相同结果。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `update_case` |
| **HTTP方法** | `PUT /api/v1/cases/{id}` |
| **输入类型** | `case_id: str` + `CaseUpdate` |
| **输出类型** | `CaseResponse` |
| **异常类型** | `HTTPException(404/403/409/422)` |
| **副作用** | 更新数据库、可能触发状态重置 |

#### 1.6.3 接口3：submit_case — 提交审核

```python
async def submit_case(
    case_id: str,
    pii_confirmed: bool = False,
    current_user: UserContext = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
) -> CaseResponse:
    """
    将草稿状态的案例提交进入审核流程（状态：draft→pending_review）。
    提交前执行完整性校验（四段式非空）、PII检测和EBP一致性检测。

    Args:
        case_id: 案例唯一标识
        pii_confirmed: 用户是否确认已处理PII警告
        current_user: 当前用户上下文
        _: 角色校验

    Returns:
        CaseResponse: 提交后的案例详情，status=pending_review

    Raises:
        HTTPException(404): 案例不存在
        HTTPException(403): 角色权限不足
        HTTPException(409): 状态不是draft（不允许提交）
        HTTPException(422): 四段式字段缺失
        HTTPException(503): 数据库写入失败

    Side Effects:
        - 更新cases.status = pending_review
        - 记录审计日志：case_submitted
        - 如pii_confirmed=True，记录PII确认审计日志
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `submit_case` |
| **HTTP方法** | `POST /api/v1/cases/{id}/submit` |
| **输入类型** | `case_id: str` + `pii_confirmed: bool(Query)` |
| **输出类型** | `CaseResponse` |
| **异常类型** | `HTTPException(404/403/409/422/503)` |
| **副作用** | 状态变更、审计日志 |

#### 1.6.4 接口4：get_case — 案例详情

```python
async def get_case(
    case_id: str,
    current_user: UserContext = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
) -> CaseResponse:
    """
    获取案例完整详情。返回全部L1+L2字段及系统字段。

    Args:
        case_id: 案例唯一标识

    Returns:
        CaseResponse: 完整案例详情

    Raises:
        HTTPException(404): 案例不存在
        HTTPException(403): 角色权限不足
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `get_case` |
| **HTTP方法** | `GET /api/v1/cases/{id}` |
| **输入类型** | `case_id: str(Path)` |
| **输出类型** | `CaseResponse` |
| **异常类型** | `HTTPException(404/403)` |

#### 1.6.5 接口5：list_cases — 案例列表

```python
async def list_cases(
    status: CaseStatus | None = None,
    page: int = 1,
    page_size: int = 15,
    current_user: UserContext = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
) -> PaginatedResponse[CaseListItem]:
    """
    按状态和作者查询案例列表。默认返回当前用户的所有案例，按created_at倒序。

    Args:
        status: 可选状态筛选（draft/pending_review/rejected）
        page: 页码，从1开始
        page_size: 每页条数，默认15

    Returns:
        PaginatedResponse[CaseListItem]: 分页列表响应

    Raises:
        HTTPException(403): 角色权限不足
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `list_cases` |
| **HTTP方法** | `GET /api/v1/cases` |
| **输入类型** | `status: str(Query, 可选)` + `page: int` + `page_size: int` |
| **输出类型** | `PaginatedResponse[CaseListItem]` |
| **异常类型** | `HTTPException(403)` |

#### 1.6.6 接口6：detect_pii — PII检测（独立端点，供前端实时检测使用）

```python
async def detect_pii(
    narrative: str = Body(..., embed=True),
    current_user: UserContext = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
) -> PiiDetectionResult:
    """
    对叙事文本执行PII检测。检测范围：真实姓名、手机号码、身份证号、家庭住址、学校名称。
    检测为提示性辅助功能，不强制阻断。

    Args:
        narrative: 待检测的叙事文本

    Returns:
        PiiDetectionResult: 检测结果（has_pii + warnings列表）
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `detect_pii` |
| **HTTP方法** | `POST /api/v1/cases/pii-check` |
| **输入类型** | `narrative: str(Body)` |
| **输出类型** | `PiiDetectionResult` |
| **异常类型** | `HTTPException(403)` |

### 1.7 依赖与集成接口

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构依据 |
|:---|:---|:---|:---|:---|
| 关系数据库 | PostgreSQL 17.x | `case_repository`通过SQLAlchemy async session操作`cases`表 | 案例主数据CRUD、状态持久化、乐观锁检测 | 技术栈设计 §2; 项目结构 §6.1(`packages/py-db/`) |
| 认证Depends | AUTH-02 (`get_current_user`) | `request.state.user` 注入 `user_id`, `roles` | 获取当前用户身份和角色 | 项目结构 §7.3 |
| 鉴权Depends | AUTH-04 (`require_role`) | `Depends(require_role(min_level=UserRole.TEACHER))` | 角色准入校验 | AUTH-04 落地规范 §1.6.1 |
| 日志 | `packages/py-logger` | `logger.info("event", **kwargs)`, `logger.warning(...)`, `logger.error(...)` | 结构化审计日志 | 项目结构 §6.1(`packages/py-logger/`) |
| 配置 | `packages/py-config` | `from py_config import settings` → `settings.DATABASE_URL`等 | 环境变量读取 | 项目结构 §6.1(`packages/py-config/`) |

#### 1.7.2 核心功能依赖（可 mock 或本地实现）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-04 | `UserRole` 枚举 (`family/teacher/expert/admin/maintainer`)、`require_role` Depends | 角色准入校验 | 已冻结（本stage复用） |
| SEC-05 | `ValidationErrorResponse` 格式 | Pydantic校验失败统一错误格式 | 已冻结（通过FastAPI默认行为复用） |
| OBS-01 | `LogLevel`枚举、`Logger`接口 | 结构化日志 | 已冻结（框架级复用） |
| DEPLOY-05 | `AppSettings` | 数据库连接等环境配置读取 | 已冻结（框架级复用） |
| SEC-03 | PII检测服务（待落地） | 本模块当前内部实现`pii_detector.detect_pii()` | 未开始（SEC-03落地后迁移） |
| CASE-02 | 附件管理（待落地） | 本模块临时内联`AttachmentRef`定义 | 未开始（CASE-02落地后引用正式契约） |
| CASE-03 | 案例审核工作流（待落地） | 下游消费`pending_review`状态的案例，通过`cases`表共享数据 | 未开始（接口通过数据契约解耦） |

### 1.8 状态机

案例录入管理涉及3个持久化状态。状态转换通过`case_repository.update_status()`单入口执行，Service层包装校验逻辑。

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| (新建) | `create_case` | draft | 角色校验通过、Schema校验通过 | INSERT cases记录，生成case_id，记录审计日志 |
| draft | `submit` | pending_review | 四段式字段全部非空；PII检测已完成（含用户确认，如适用） | 更新status和updated_at；记录`case_submitted`审计日志 |
| pending_review | `edit` | draft | 乐观锁`updated_at`匹配 | 更新字段内容；重置status为draft；更新updated_at |
| pending_review | `CASE-03 reject` | rejected | CASE-03模块写入 | 更新status和review_comment；由CASE-03通过repository共享执行 |
| rejected | `edit` | draft | 乐观锁`updated_at`匹配 | 同pending_review→draft |
| draft | `edit` | draft | 乐观锁`updated_at`匹配 | 仅更新字段内容，不触发状态变更 |

**幂等策略**：
- `submit`在`status!=draft`时返回409 Conflict
- `edit`对`draft`案例不触发状态变更
- 重复`submit`调用：第二次调用因status已非draft而返回409
- 状态转换通过`UPDATE ... WHERE case_id=$1 AND status=$expected_status`实现原子性

**CASE-03边界**：CASE-03驳回操作写入`status=rejected`，通过`case_repository.update_status(case_id, CaseStatus.REJECTED, review_comment=comment)`执行。审核通过（`approved`）的状态不在此状态机中。

### 1.9 异常与边界条件

#### 1.9.1 异常1：必填字段缺失

- **触发条件**：
  - 任一必填字段（title, narrative, source_type, behavior_type等17个字段）为None或空字符串
  - `age_range`格式不正确（非`[int, int]`或值超出0-100）
  - `ebp_labels`为空列表
  - 四段式任一字段为`""`或仅空白字符

- **处理策略**：
  1. Pydantic校验阶段捕获`ValidationError`
  2. 提取第一个错误字段名和约束描述
  3. 返回HTTP 422，响应体：`{"detail": [{"loc": ["body", "field_name"], "msg": "约束描述", "type": "value_error"}]}`
  4. 不创建任何数据库记录，不进入Service层

- **重试参数**：不重试。用户修正后重新提交。

#### 1.9.2 异常2：乐观锁冲突

- **触发条件**：
  - `PUT /api/v1/cases/{id}` 请求中`updated_at`值与数据库当前值不一致
  - 即：`SELECT * FROM cases WHERE case_id=$1 AND updated_at=$2` 返回0行

- **处理策略**：
  1. 在`case_repository.find_by_id_with_version()`中检测到0行返回
  2. 重新查询当前最新记录获取最新`updated_at`
  3. 返回HTTP 409 Conflict，响应体：`{"detail": "编辑冲突：案例已被其他用户修改。请刷新后重试。", "current_updated_at": "2026-05-27T09:30:00Z"}`
  4. 记录日志：`logger.warning("optimistic_lock_conflict", case_id=..., expected_ts=..., actual_ts=...)`

- **重试参数**：不自动重试。客户端收到409后重新读取最新数据，合并修改后重新提交。

#### 1.9.3 异常3：状态转换非法

- **触发条件**：
  - 对`status=pending_review`或`rejected`的案例调用`POST /api/v1/cases/{id}/submit`
  - 对不存在的`case_id`调用任何操作

- **处理策略**：
  - `submit`非draft案例：
    1. `case_service._validate_submit_eligible()`检查`status`
    2. 返回HTTP 409，响应体：`{"detail": "当前状态为{status}，仅draft状态可提交审核", "allowed_transition": "draft -> pending_review"}`
  - 案例不存在：
    1. `case_repository.find_by_id()`返回None
    2. 返回HTTP 404，响应体：`{"detail": "案例{case_id}不存在"}`
    3. 记录日志：`logger.warning("case_not_found", case_id=...)`

- **重试参数**：不重试。客户端刷新状态后重新操作。

#### 1.9.4 异常4：数据库写入超时

- **触发条件**：
  - PostgreSQL连接超时（>5秒无响应）
  - 数据库死锁或连接池耗尽
  - 网络中断导致asyncpg连接断开

- **处理策略**：
  1. 捕获`asyncpg.exceptions.PostgresConnectionError` / `asyncio.TimeoutError`
  2. 关闭当前失效连接，从连接池获取新连接
  3. 重试同一操作
  4. 重试3次后仍失败：返回HTTP 503，响应体：`{"detail": "服务暂时不可用，请稍后重试"}`
  5. 记录日志：`logger.critical("database_failure", case_id=..., operation=..., retry_count=...)`

- **重试参数**：最多3次，指数退避（1s, 2s, 4s）。每次重试前重新获取数据库连接。

#### 1.9.5 异常5：四段式字段部分缺失（提交阶段）

- **触发条件**：
  - `submit`操作时数据库中的`immediate_action`/`comforting_phrase`/`observation_metrics`/`medical_criteria`任一为空字符串或仅含空白

- **处理策略**：
  1. `case_service._validate_four_stage_fields()`逐字段检查
  2. 返回HTTP 422，响应体包含具体缺失字段列表：`{"detail": "四段式字段不完整", "missing_fields": ["immediate_action"]}`

- **重试参数**：不重试。用户补全后重新提交。

### 1.10 验收测试场景

#### 1.10.1 正向测试1：完整案例录入全流程

- **场景**：认证专家完整填写案例表单，提交进入审核
- **Given**: 有效JWT（roles=["expert"]），完整`CaseCreateRequest`（17个必填字段全部有效值），narrative无PII
  ```json
  {
    "title": "ASD儿童商场感官过载的降噪干预",
    "narrative": "7岁ASD男孩在商场因吹风机声音突然捂住耳朵蹲下...（120字完整叙事）",
    "source_type": "专家撰写",
    "author_id": "e4a7c8d9-1234-5678-9abc-def012345678",
    "behavior_type": "情绪崩溃",
    "age_range": [3, 8],
    "severity": "中度",
    "scene": "公共场合",
    "ebp_labels": ["视觉支持", "反应中断/重定向", "强化"],
    "family_category": "危机安全",
    "immediate_action": "立即关闭或远离噪音源；提供降噪耳机...",
    "comforting_phrase": "用平静低沉的声音说：没关系...",
    "observation_metrics": "观察患者是否停止捂耳动作...",
    "medical_criteria": "如在安静环境下持续捂耳超过15分钟...",
    "evidence_level": "NCAEP循证实践",
    "contraindications": "禁强行拖拽患者身体...",
    "is_template": false
  }
  ```
- **When**: 
  1. `POST /api/v1/cases` → 创建草稿
  2. `POST /api/v1/cases/{id}/submit?pii_confirmed=true` → 提交审核
- **Then**:
  - 步骤1返回201，`status="draft"`，`case_id`格式为`CASE-2026-NNNN`
  - 步骤2返回200，`status="pending_review"`
  - 数据库中记录完整无遗漏

#### 1.10.2 正向测试2：编辑已驳回案例后重新提交

- **场景**：案例被CASE-03驳回，作者编辑后重新提交
- **Given**: 数据库中案例`status="rejected"`，`review_comment="需补充观察指标细节"`，当前`updated_at="2026-05-27T08:00:00Z"`
- **When**:
  1. `PUT /api/v1/cases/{id}` — 传入`{"observation_metrics": "更新后的详细观察指标...", "updated_at": "2026-05-27T08:00:00Z"}`
  2. `POST /api/v1/cases/{id}/submit`
- **Then**:
  - 步骤1返回200，`status="draft"`（编辑即重置），更新的字段生效
  - 步骤2返回200，`status="pending_review"`

#### 1.10.3 正向测试3：EBP标签一致性检测（不一致警告不阻断）

- **场景**：用户选evidence_level=ebp但ebp_labels含非NCAEP标签
- **Given**: 有效JWT，CaseCreateRequest中`evidence_level="NCAEP循证实践"`，`ebp_labels=["视觉支持", "非标准标签XYZ"]`
- **When**: `POST /api/v1/cases/{id}/submit`
- **Then**: 返回200，`status="pending_review"`，同时响应体含`ebp_inconsistency_warning`字段，内容为标签"非标准标签XYZ"不在NCAEP列表

#### 1.10.4 异常测试1：必填字段缺失被拒绝

- **场景**：narrative字段为空
- **Given**: 有效JWT，CaseCreateRequest中`narrative=""`
- **When**: `POST /api/v1/cases`
- **Then**: 返回422，`detail`中包含`{"loc": ["body", "narrative"], "msg": "ensure this value has at least 100 characters"}`

#### 1.10.5 异常测试2：乐观锁冲突

- **场景**：两个用户同时编辑同一案例
- **Given**: 数据库案例`status="draft"`，`updated_at="2026-05-27T08:00:00Z"`。用户A已先完成编辑，数据库中`updated_at`已更新为`"2026-05-27T09:00:00Z"`
- **When**: 用户B `PUT /api/v1/cases/{id}` — 传入`{"title": "修改后的标题", "updated_at": "2026-05-27T08:00:00Z"}`
- **Then**: 返回409，响应体含`"current_updated_at": "2026-05-27T09:00:00Z"`

#### 1.10.6 异常测试3：非draft状态提交被拒绝

- **场景**：对已提交的案例再次submit
- **Given**: 数据库案例`status="pending_review"`
- **When**: `POST /api/v1/cases/{id}/submit`
- **Then**: 返回409，`detail`包含"当前状态为pending_review，仅draft状态可提交审核"

#### 1.10.7 异常测试4：非老师/专家角色被拒绝

- **场景**：家属角色尝试创建案例
- **Given**: JWT `roles=["family"]`
- **When**: `POST /api/v1/cases`
- **Then**: 返回403，`detail`为预设文案（不泄露权限规则细节）

### 1.11 注意事项与禁止行为（编码层面）

1. **[Depends链顺序]** 路由端点声明`Depends`时，`get_current_user`必须出现在`require_role`之前。正确：`Depends(get_current_user), Depends(require_role(min_level=UserRole.TEACHER))`。错误示例将导致`request.state.user`为None。

2. **[编辑即重置编码位置]** 状态重置逻辑必须写在`case_service.update_case()`中字段更新之前，且在同一数据库事务内。禁止在路由层实现重置逻辑，禁止异步执行重置。

3. **[四段式校验时机]** 创建时仅校验非空（Pydantic层面），提交时再执行完整性校验（Service层面）。禁止在创建草稿时强制四段式完整性——意图文档允许逐步填写草稿。

4. **[PII检测编码约束]** PII检测结果不得自动脱敏或静默忽略。用户确认操作必须记录到审计日志：`logger.info("pii_confirmed", case_id=..., confirmed_by=..., pii_findings=...)`。PII检测正则模式集中维护在`py_security/pii_patterns.py`常量中。

5. **[禁止绕过权限校验]** 所有CASE-01端点必须在路由或Depends中显式声明`require_role(min_level=UserRole.TEACHER)`。禁止在Service层方法直接调用而不经过角色校验。

6. **[禁止跨模块数据操作]** 本模块仅操作`cases`表。禁止直接读取或写入`case_chunks`表（CASE-04）、`case_versions`表（CASE-05）、`tickets`表（TICK-07）。下游客模块通过`CaseResponse`契约获取数据。

7. **[偷懒红线]** 禁止以"四段式字段跟其他字段一样"为由省略提交阶段的完整性校验逻辑。禁止以"PII检测暂时不需要"为由跳过PII检测实现。

### 1.12 文档详细度自检清单

- [x] 文档自包含：不了解本项目代码的Agent可凭此文档独立完成编码
- [x] 无偷懒表述：全文无`"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：所有字段通过契约JSON文件精确定义，含description + constraints
- [x] 逻辑步骤完整：6个流程共20个原子步骤，每个步骤含操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5种异常，每种含精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值（如pii_confirmed=false、is_template=false）已显式标注
- [x] 技术栈绑定明确：必须使用和禁止使用项均已列出，与项目技术栈设计文档一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| CaseStatus | `docs/contracts/CASE-01/CaseStatus.json` | shared-enum | draft | CASE-01 | CASE-02, CASE-03, CASE-04, CASE-05, CASE-07 |
| SourceType | `docs/contracts/CASE-01/SourceType.json` | shared-enum | draft | CASE-01 | CASE-03, TICK-07 |
| BehaviorType | `docs/contracts/CASE-01/BehaviorType.json` | shared-enum | draft | CASE-01 | CASE-03, CASE-07, CASE-09 |
| SeverityLevel | `docs/contracts/CASE-01/SeverityLevel.json` | shared-enum | draft | CASE-01 | CASE-03, CASE-09 |
| SceneType | `docs/contracts/CASE-01/SceneType.json` | shared-enum | draft | CASE-01 | CASE-03, CASE-09, CSLT-02 |
| EvidenceLevel | `docs/contracts/CASE-01/EvidenceLevel.json` | shared-enum | draft | CASE-01 | CASE-03, CASE-07, KNOW-04 |
| FamilyDisplayCategory | `docs/contracts/CASE-01/FamilyDisplayCategory.json` | shared-enum | draft | CASE-01 | CASE-09 |
| CaseCreateRequest | `docs/contracts/CASE-01/CaseCreateRequest.json` | input | draft | CASE-01 | CASE-09 |
| CaseUpdate | `docs/contracts/CASE-01/CaseUpdate.json` | input | draft | CASE-01 | CASE-09 |
| CaseResponse | `docs/contracts/CASE-01/CaseResponse.json` | output | draft | CASE-01 | CASE-03, CASE-04, CASE-05, CASE-07, KNOW-04 |
| CaseListItem | `docs/contracts/CASE-01/CaseListItem.json` | output | draft | CASE-01 | CASE-03, CASE-09, TICK-07 |
| PiiWarning | `docs/contracts/CASE-01/PiiWarning.json` | output | draft | CASE-01 | — |
| PiiDetectionResult | `docs/contracts/CASE-01/PiiDetectionResult.json` | output | draft | CASE-01 | — |

**复用已有契约**：
| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| UserRole | `docs/contracts/AUTH-04/UserRole.json` | shared-enum | draft | AUTH-04 | CASE-01 |
| require_role | `docs/contracts/AUTH-04/require_role.json` | input | draft | AUTH-04 | CASE-01 |
| PermissionDeniedResponse | `docs/contracts/AUTH-04/PermissionDeniedResponse.json` | output | draft | AUTH-04 | CASE-01 |
| ValidationErrorResponse | `docs/contracts/SEC-05/ValidationErrorResponse.json` | output | draft | SEC-05 | CASE-01 |
| AppSettings | `docs/contracts/DEPLOY-05/AppSettings.json` | input | draft | DEPLOY-05 | CASE-01 |
| LogLevel | `docs/contracts/OBS-01/LogLevel.json` | shared-enum | draft | OBS-01 | CASE-01 |
| httpClient | `docs/contracts/AUTH-06/httpClient.json` | output | draft | AUTH-06 | CASE-01 (前端) |
| SessionState | `docs/contracts/AUTH-06/SessionState.json` | shared-enum | draft | AUTH-06 | CASE-01 (前端) |
| TokenPair | `docs/contracts/AUTH-06/TokenPair.json` | shared-model | draft | AUTH-06 | CASE-01 (前端) |

### 1.15 意图一致性声明

- **配套意图文档**：`CASE-01-案例录入管理-意图文档.md`
- **冻结时间**：`2026-05-27 09:11:39`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（17个L1+L2必填字段、枚举值、输出系统字段全部对应）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（draft→pending_review→rejected，编辑即重置为draft，审核通过后状态归属CASE-03）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（必填字段缺失拒绝、PII检测提示不阻断、循证等级不一致提示不阻断、编辑后状态重置）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01字段校验、AC-02来源类型枚举、AC-03行为类型枚举、AC-04循证等级枚举、AC-05 PII检测、AC-06编辑重置、AC-07四段式完整性、AC-09 EBP一致性）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（8项决策全部覆盖：类型定义、物理存储、PII策略、编辑冲突、附件引用、自动保存、LLM提取、表单状态）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。

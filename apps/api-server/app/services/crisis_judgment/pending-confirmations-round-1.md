# CSLT-01 Round 1 修复确认

> **生成时间**: 2026-05-27
> **任务**: 根据盲测失败摘要修复 4 个 bug／8 个失败用例

---

## Bug 1: uniqueItems 验证缺失 (A05)

- **文件**: `models.py`
- **修改**: 在 `CrisisJudgmentRequest` 中添加 `@field_validator('behavior_type_selection')`
- **逻辑**: `len(v) != len(set(v))` 检查重复元素，重复时抛出 `ValueError`
- **参考**: 契约 `CrisisJudgmentRequest.json` 中 `behavior_type_selection.uniqueItems: true`
- **涉及 Case ID**: A05

## Bug 2: degradation_note 未设置 —— profile_missing (A10, C02)

- **文件**: `pipeline.py`
- **修改**: 在 `JudgmentPipeline.run()` 中，步骤 1（前置选择）之后、步骤 2（规则引擎）之前插入检查
- **逻辑**: `request.patient_profile is None` 时设置 `context.degradation_note = "profile_missing"`
- **优先级共存规则**: `profile_missing` 先于 `rule_engine_degraded` 设置；若规则引擎随后因词库加载失败设置 `rule_engine_degraded`，则后者覆盖前者（安全优先策略）
- **参考**: 落地规范 §1.9.4 异常 4：患者档案缺失
- **涉及 Case ID**: A10, C02

## Bug 3: 否定词过滤未生效 (B09, B10)

- **文件**: `rule_engine_layer.py`
- **修改**:
  1. 从 `.ac_matcher` 导入 `_negation_filter` 模块级函数
  2. 匹配循环中独立提取 `match.get("start_pos", 0)`，显式调用 `_negation_filter(match_start_pos=start_pos, text=text)`
  3. 不再依赖 `ac_matcher.search()` 预置的 `negation_filtered` 标记
  4. 否定匹配计入 `negation_filtered = True` 标记并跳过
- **参考**: 否定词列表定义于 `ac_matcher.NEGATION_WORDS`，前向 7 字符窗口扫描
- **涉及 Case ID**: B09, B10

## Bug 4: manual_review_flag 未传播 (B12, X09, X10)

- **文件**: `rule_engine_layer.py` + `pipeline.py`
- **修改**:
  1. `rule_engine_layer.py` — 档案叠加规则触发时除设置 `details["profile_overlap_triggered"] = True` 外，额外设置 `details["manual_review_recommended"] = True`
  2. `pipeline.py` — `_run_rule_engine()` 中追加 `context.sources.append(result)` 之后，检查 `result.details` 的 `manual_review_recommended` 或 `profile_overlap_triggered`，任一为真则设置 `context.manual_review_flag = True`
- **传播路径**: `RuleEngineLayer.judge()` 标记 → `JudgmentLayerResult.details` → `_run_rule_engine()` 传播至 `context.manual_review_flag` → `_merge()` 消费至 `CrisisJudgmentResult.manual_review_flag`
- **参考**: 落地规范 §1.4 步骤 4.4 档案叠加规则 → `context.manual_review_flag = True`
- **涉及 Case ID**: B12, X09, X10

---

## 提交前契约自检清单

- [x] 修复后的 Pydantic 模型字段名、类型、必填性与契约 JSON 一致
  - `CrisisJudgmentRequest.behavior_type_selection` — `list[BehaviorTypeCategory]`, `minLength=1`, `uniqueItems=true`
  - `CrisisJudgmentResult.degradation_note` — `str | None`, 枚举 `["rule_engine_degraded", "profile_missing"]`
- [x] 未在修复中引入契约文件未声明的新字段
  - `JudgmentLayerResult.details` 的 `additionalProperties: true` 允许 `manual_review_recommended`
- [x] `degradation_note` 的值在契约允许的枚举范围内
  - `"profile_missing"` — 在 `CrisisJudgmentResult.json` 的 `enum` 中声明

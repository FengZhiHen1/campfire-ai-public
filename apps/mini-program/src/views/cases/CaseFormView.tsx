/**
 * CASE-01 案例录入管理 — 案例表单视图。
 *
 * 纯 UI 渲染组件，接收 caseFormStore 作为 Props。
 * 不包含任何业务逻辑和数据请求——所有逻辑在 logics/ 层处理。
 *
 * 设计原则（L1a 约束）：
 * - 禁止直接调用 API Service
 * - 禁止直接读写 Zustand Store
 * - 禁止包含数据转换、校验、格式化逻辑
 * - 所有数据和方法通过 Props 传入
 *
 * 调用路径：
 *   pages/ → CaseFormView(Props) ← useCaseFormStore Hook
 */

import { View, Text, Input, Textarea, Picker, Switch, Button } from '@tarojs/components';
import type { FC } from 'react';

import type { CaseFormFields, FormErrors } from '../../logics/cases/types';

// ============================================================================
// Props 类型定义
// ============================================================================

interface CaseFormViewProps {
  /** 表单字段值 */
  fields: CaseFormFields;
  /** 校验错误 */
  errors: FormErrors;
  /** 是否正在提交 */
  isSubmitting: boolean;
  /** 最后保存时间 */
  lastSavedAt: string | null;
  /** 更新字段值的回调 */
  onFieldChange: (name: keyof CaseFormFields, value: string | number | boolean | string[]) => void;
  /** 提交表单的回调 */
  onSubmit: () => void;
  /** 重置表单的回调 */
  onReset: () => void;
  /** 加载草稿的回调 */
  onLoadDraft: () => void;
  /** 来源类型选项 */
  sourceTypeOptions: string[];
  /** 行为类型选项 */
  behaviorTypeOptions: string[];
  /** 严重程度选项 */
  severityOptions: string[];
  /** 场景选项 */
  sceneOptions: string[];
  /** 循证等级选项 */
  evidenceLevelOptions: string[];
  /** 家属展示大类选项 */
  familyCategoryOptions: string[];
}

// ============================================================================
// 组件
// ============================================================================

/**
 * 案例表单视图组件。
 * 纯渲染组件，不含业务逻辑。
 *
 * @param props - 组件属性
 * @returns 表单 UI
 */
const CaseFormView: FC<CaseFormViewProps> = ({
  fields,
  errors,
  isSubmitting,
  lastSavedAt,
  onFieldChange,
  onSubmit,
  onReset,
  onLoadDraft,
  sourceTypeOptions,
  behaviorTypeOptions,
  severityOptions,
  sceneOptions,
  evidenceLevelOptions,
  familyCategoryOptions,
}) => {
  /**
   * 渲染文本输入字段。
   */
  const renderInput = (
    label: string,
    name: keyof CaseFormFields,
    placeholder: string,
    maxLength?: number,
  ) => (
    <View className="form-group">
      <Text className="form-label">{label}</Text>
      <Input
        className={`form-input ${errors[name] ? 'has-error' : ''}`}
        value={String(fields[name] ?? '')}
        placeholder={placeholder}
        maxlength={maxLength}
        onInput={(e) => onFieldChange(name, e.detail.value)}
      />
      {errors[name] && <Text className="form-error">{errors[name]}</Text>}
    </View>
  );

  /**
   * 渲染多行文本输入字段。
   */
  const renderTextarea = (
    label: string,
    name: keyof CaseFormFields,
    placeholder: string,
  ) => (
    <View className="form-group">
      <Text className="form-label">{label}</Text>
      <Textarea
        className={`form-textarea ${errors[name] ? 'has-error' : ''}`}
        value={String(fields[name] ?? '')}
        placeholder={placeholder}
        onInput={(e) => onFieldChange(name, e.detail.value)}
      />
      {errors[name] && <Text className="form-error">{errors[name]}</Text>}
    </View>
  );

  /**
   * 渲染选择器字段（Picker）。
   */
  const renderPicker = (
    label: string,
    name: keyof CaseFormFields,
    options: string[],
    placeholder: string,
  ) => {
    const selectedIndex: number = options.indexOf(String(fields[name] ?? ''));
    return (
      <View className="form-group">
        <Text className="form-label">{label}</Text>
        <Picker
          mode="selector"
          range={options}
          value={selectedIndex >= 0 ? selectedIndex : 0}
          onChange={(e) => {
            const index: number = parseInt(e.detail.value, 10);
            onFieldChange(name, options[index] || '');
          }}
        >
          <View className={`form-picker ${errors[name] ? 'has-error' : ''}`}>
            <Text>{fields[name] ? String(fields[name]) : placeholder}</Text>
          </View>
        </Picker>
        {errors[name] && <Text className="form-error">{errors[name]}</Text>}
      </View>
    );
  };

  return (
    <View className="case-form-container">
      {/* 顶部操作栏 */}
      <View className="form-toolbar">
        <Button className="btn-draft" onClick={onLoadDraft}>
          恢复草稿
        </Button>
        <Button className="btn-reset" onClick={onReset}>
          重置
        </Button>
        {lastSavedAt && (
          <Text className="save-indicator">
            已保存: {new Date(lastSavedAt).toLocaleTimeString()}
          </Text>
        )}
      </View>

      {/* ---- L1 叙事层 ---- */}
      <View className="form-section">
        <Text className="section-title">基本信息</Text>
        {renderInput('案例标题 *', 'title', '请输入案例标题（100字以内）', 100)}
        {renderTextarea('叙事文本 *', 'narrative', '请以自然语言撰写完整干预故事（至少100字）')}
        {renderPicker('来源类型 *', 'source_type', sourceTypeOptions, '请选择来源类型')}
      </View>

      {/* ---- L2 结构化卡片层 ---- */}
      <View className="form-section">
        <Text className="section-title">行为特征</Text>
        {renderPicker('行为类型 *', 'behavior_type', behaviorTypeOptions, '请选择行为类型')}

        <View className="form-group">
          <Text className="form-label">适用年龄区间 *</Text>
          <View className="age-range-container">
            <Input
              className={`form-input age-input ${errors.age_range_min ? 'has-error' : ''}`}
              type="number"
              value={String(fields.age_range_min)}
              placeholder="起始岁"
              onInput={(e) => onFieldChange('age_range_min', parseInt(e.detail.value, 10) || 0)}
            />
            <Text className="age-separator">-</Text>
            <Input
              className={`form-input age-input ${errors.age_range_max ? 'has-error' : ''}`}
              type="number"
              value={String(fields.age_range_max)}
              placeholder="结束岁"
              onInput={(e) => onFieldChange('age_range_max', parseInt(e.detail.value, 10) || 0)}
            />
          </View>
        </View>

        {renderPicker('严重程度 *', 'severity', severityOptions, '请选择严重程度')}
        {renderPicker('发生场景 *', 'scene', sceneOptions, '请选择发生场景')}
      </View>

      <View className="form-section">
        <Text className="section-title">干预方案</Text>
        {renderTextarea('即时安全干预动作 *', 'immediate_action', '描述具体可执行的干预动作')}
        {renderTextarea('情绪安抚话术 *', 'comforting_phrase', '描述温和简短确定的安抚语句')}
        {renderTextarea('后续观察指标 *', 'observation_metrics', '列出具体可观察的行为或生理指标')}
        {renderTextarea('就医判断标准 *', 'medical_criteria', '给出明确的判断条件和建议行动')}
      </View>

      <View className="form-section">
        <Text className="section-title">分类与标签</Text>
        {renderPicker('循证等级 *', 'evidence_level', evidenceLevelOptions, '请选择循证等级')}
        {renderPicker('家属展示大类 *', 'family_category', familyCategoryOptions, '请选择展示大类')}

        <View className="form-group">
          <Text className="form-label">禁忌与注意事项 *</Text>
          <Textarea
            className={`form-textarea ${errors.contraindications ? 'has-error' : ''}`}
            value={fields.contraindications}
            placeholder="请描述注意事项和禁忌"
            onInput={(e) => onFieldChange('contraindications', e.detail.value)}
          />
        </View>
      </View>

      <View className="form-section">
        <Text className="section-title">其他</Text>
        <View className="form-group">
          <Text className="form-label">不适用人群</Text>
          <Input
            className="form-input"
            value={fields.excluded_population}
            placeholder="选填：不适宜的患者群体"
            onInput={(e) => onFieldChange('excluded_population', e.detail.value)}
          />
        </View>
      </View>

      {/* 提交按钮 */}
      <View className="form-actions">
        <Button
          className="btn-submit"
          loading={isSubmitting}
          disabled={isSubmitting}
          onClick={onSubmit}
        >
          提交审核
        </Button>
      </View>
    </View>
  );
};

export default CaseFormView;

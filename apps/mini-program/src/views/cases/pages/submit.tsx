import { View, Text, Button, Input, Textarea, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useCaseSubmit } from '../../../logics/cases';
import './submit.scss';

// ============================================================================
// 组件：案例提交页（纯渲染层）
//
// 所有业务逻辑在 useCaseSubmit Hook 中。
// 本组件只负责 JSX 渲染和事件绑定。
// ============================================================================

export default function CasesSubmit() {
  const {
    title, setTitle,
    behaviorTypeIdx, setBehaviorTypeIdx,
    severityIdx, setSeverityIdx,
    sceneIdx, setSceneIdx,
    evidenceLevelIdx, setEvidenceLevelIdx,
    quartetValues, quartetSetter, handleSubmit,
    behaviorTypeOptions, severityOptions, sceneOptions, evidenceLevelOptions, quartetConfig,
  } = useCaseSubmit();

  return (
    <View className="submit-page">
      {/* 顶部导航栏 */}
      <View className="submit-navbar">
        <Button className="submit-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
        <Text className="submit-navbar__title">提交案例</Text>
      </View>

      {/* 封面图占位 */}
      <View className="submit-cover">
        <Text className="submit-cover__icon">📷</Text>
        <Text className="submit-cover__text">点击上传封面图</Text>
        <Text className="submit-cover__hint">建议上传现场环境照，帮助读者理解情境</Text>
      </View>

      {/* 基础信息 */}
      <View className="submit-section-title">
        <Text className="submit-section-title__required">*</Text>
        <Text>基本信息</Text>
      </View>
      <View className="submit-section">
        <View className="submit-field">
          <Text className="submit-field__label submit-field__label--required">案例标题</Text>
          <Input className="submit-field__input" value={title} onInput={(e) => setTitle(e.detail.value)} placeholder="请输入案例标题" />
        </View>
        <View className="submit-row">
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">行为类型</Text>
            <Picker mode="selector" range={behaviorTypeOptions as unknown as string[]} value={behaviorTypeIdx} onChange={(e) => setBehaviorTypeIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{behaviorTypeOptions[behaviorTypeIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">严重程度</Text>
            <Picker mode="selector" range={severityOptions as unknown as string[]} value={severityIdx} onChange={(e) => setSeverityIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{severityOptions[severityIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
        </View>
        <View className="submit-row">
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">场景</Text>
            <Picker mode="selector" range={sceneOptions as unknown as string[]} value={sceneIdx} onChange={(e) => setSceneIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{sceneOptions[sceneIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
          <View className="submit-field">
            <Text className="submit-field__label submit-field__label--required">循证等级</Text>
            <Picker mode="selector" range={evidenceLevelOptions as unknown as string[]} value={evidenceLevelIdx} onChange={(e) => setEvidenceLevelIdx(Number(e.detail.value))}>
              <Button className="submit-field__picker">
                <Text className="submit-field__picker-text">{evidenceLevelOptions[evidenceLevelIdx]}</Text>
                <Text className="submit-field__picker-chevron">▼</Text>
              </Button>
            </Picker>
          </View>
        </View>
      </View>

      {/* 四段式内容 */}
      <View className="submit-section-title">
        <Text className="submit-section-title__required">*</Text>
        <Text>案例内容</Text>
        <Text className="submit-section-title__hint">请按四段式结构填写</Text>
      </View>
      <View className="submit-quartet">
        {quartetConfig.map((cfg) => (
          <View key={cfg.key} className="submit-card">
            <View className={`submit-card__accent submit-card__accent--${cfg.accent}`} />
            <View className="submit-card__body">
              <Text className={`submit-card__title submit-card__title--${cfg.color}`}>
                <Text className="submit-card__required">*</Text>
                {cfg.title}
              </Text>
              <Text className="submit-card__hint">{cfg.hint}</Text>
              <Textarea
                className="submit-card__textarea"
                value={quartetValues[cfg.key]}
                onInput={(e) => quartetSetter(cfg.key, e.detail.value)}
                placeholder={cfg.hint}
                maxlength={2000}
              />
            </View>
          </View>
        ))}
      </View>

      {/* 底部操作栏 */}
      <View className="submit-actions">
        <Button className="submit-actions__btn" onClick={handleSubmit}>提交案例</Button>
      </View>
    </View>
  );
}

/**
 * 应急咨询会话页——统一聊天容器（消息分级样式）。
 *
 * 消息分级（智能应急咨询 §二 界面形态）：
 * - 安全卡 / 阶段问题 / 红线指引 → 大字号强视觉（critical）
 * - 完整方案 / 追问回复 → 常规消息样式
 * 交互：阶段单点问题 quick-reply（每次一问）、追问输入、未解决标记。
 */

import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useConsultSession } from '@/logics/consult';
import type { ConsultMessage } from '@/logics/consult';
import Button from '@/views/_shared/components/Button';
import './consult.css';

export default function ConsultSessionPage() {
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>();
  const { sessionId, phase, messages, streamingText, answerQuestion, followup, markUnresolved, attachStream } =
    useConsultSession();
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const attachedRef = useRef(false);

  // 从路由进入（刷新/直链）时重新挂接事件流
  useEffect(() => {
    if (attachedRef.current) return;
    attachedRef.current = true;
    if (routeSessionId && routeSessionId !== sessionId) {
      attachStream(routeSessionId);
    }
  }, [routeSessionId, sessionId, attachStream]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingText]);

  const canFollowup = phase === 'followup';

  async function handleFollowup() {
    const text = input.trim();
    if (!text) return;
    setInput('');
    await followup(text);
  }

  return (
    <div className="consult-session">
      {messages.map((msg) => (
        <MessageView key={msg.id} message={msg} onAnswer={answerQuestion} phase={phase} />
      ))}

      {streamingText && (
        <div className="msg msg--plan">
          <div style={{ whiteSpace: 'pre-wrap' }}>{streamingText}▍</div>
        </div>
      )}
      <div ref={bottomRef} />

      {/* 追问输入区（followup 阶段可用） */}
      <div className="consult-input-bar">
        <div className="consult-input-bar__row">
          <input
            className="consult-input-bar__input"
            placeholder={canFollowup ? '补充情况或继续提问…' : '请先完成上方步骤'}
            value={input}
            disabled={!canFollowup}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleFollowup();
            }}
          />
          <Button onClick={() => void handleFollowup()} disabled={!canFollowup || !input.trim()}>
            发送
          </Button>
        </div>
        <div className="consult-input-bar__actions">
          <span>AI 建议仅供参考，不构成医疗诊断</span>
          {canFollowup && (
            <button type="button" className="consult-input-bar__unresolved" onClick={() => void markUnresolved()}>
              问题未解决
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function MessageView({
  message,
  onAnswer,
  phase,
}: {
  message: ConsultMessage;
  onAnswer: (answer: string) => Promise<void>;
  phase: string;
}) {
  switch (message.kind) {
    case 'safety_card':
      return (
        <section className={`safety-card safety-card--${message.card.variant} msg--critical`}>
          <h2 className="safety-card__title">{message.card.title}</h2>
          <div className="safety-card__content">{message.card.content}</div>
        </section>
      );

    case 'stage_question':
      return (
        <StageQuestionView
          key={message.id}
          question={message.question}
          disabled={phase !== 'stage_qa'}
          onAnswer={onAnswer}
        />
      );

    case 'redline_guide':
      return (
        <section className="redline-guide msg--critical">
          <h2 className="redline-guide__title">紧急指引</h2>
          <div className="redline-guide__body">{message.guide.guidance}</div>
        </section>
      );

    case 'plan_chunk':
      return (
        <div className="msg msg--plan">
          <div style={{ whiteSpace: 'pre-wrap' }}>{message.text}</div>
        </div>
      );

    case 'plan_result':
      return (
        <div className="msg msg--plan">
          <div className="msg__section-title">即时安全干预动作</div>
          <div style={{ whiteSpace: 'pre-wrap' }}>{message.plan.immediate_action}</div>
          <div className="msg__section-title">情绪安抚话术</div>
          <div style={{ whiteSpace: 'pre-wrap' }}>{message.plan.soothing_script}</div>
          <div className="msg__section-title">后续观察指标</div>
          <div style={{ whiteSpace: 'pre-wrap' }}>{message.plan.observation}</div>
          <div className="msg__section-title">就医判断标准</div>
          <div style={{ whiteSpace: 'pre-wrap' }}>{message.plan.medical_judgment}</div>
          {message.plan.sources.length > 0 && (
            <>
              <div className="msg__section-title">参考来源</div>
              {message.plan.sources.map((s, i) => (
                <div key={i} style={{ fontSize: 12, color: 'var(--cf-muted)' }}>
                  [{i + 1}] {s.title}
                </div>
              ))}
            </>
          )}
          <div className="msg__disclaimer">{message.plan.disclaimer}</div>
        </div>
      );

    case 'fallback_notice':
      return (
        <section className="fallback-notice">
          <div className="fallback-notice__message">{message.notice.message}</div>
          <div className="fallback-notice__guidance">{message.notice.guidance}</div>
        </section>
      );

    case 'user_answer':
      return <div className="msg msg--user">{message.text}</div>;

    default:
      return null;
  }
}

function StageQuestionView({
  question,
  disabled,
  onAnswer,
}: {
  question: { question_id: string; question: string; options: string[] };
  disabled: boolean;
  onAnswer: (answer: string) => Promise<void>;
}) {
  const [answered, setAnswered] = useState(false);

  return (
    <section className="stage-question msg--critical">
      <div className="stage-question__text">{question.question}</div>
      <div className="stage-question__options">
        {question.options.map((opt) => (
          <button
            key={opt}
            type="button"
            className="stage-question__option"
            disabled={disabled || answered}
            onClick={() => {
              setAnswered(true);
              void onAnswer(opt);
            }}
          >
            {opt}
          </button>
        ))}
      </div>
    </section>
  );
}

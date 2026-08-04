/**
 * 应急咨询入口页——0 输入通用安全卡 + 行为桶选择（大字按钮，危机中单手可操作）。
 * ADR-009 时刻分层：桶选择兼任输入方式/红线分流/检索过滤维度三职。
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BehaviorBucket,
  BUCKET_UI_LABELS,
  consultApi,
  REDLINE_BUCKETS,
  useConsultSession,
} from '@/logics/consult';
import type { SafetyCardPayload } from '@/logics/consult';
import PageContent from '@/views/_shared/layout/PageContent';
import './consult.css';

const BUCKET_ORDER: BehaviorBucket[] = [
  BehaviorBucket.MELTDOWN,
  BehaviorBucket.STEREOTYPY,
  BehaviorBucket.SELF_INJURY,
  BehaviorBucket.AGGRESSION,
  BehaviorBucket.ELOPEMENT,
  BehaviorBucket.MEDICATION,
  BehaviorBucket.SOCIAL_WITHDRAWAL,
  BehaviorBucket.HYPERACTIVITY,
  BehaviorBucket.OTHER,
];

export default function ConsultIndexPage() {
  const navigate = useNavigate();
  const { startWithBucket } = useConsultSession();
  const [universalCard, setUniversalCard] = useState<SafetyCardPayload | null>(null);
  const [submitting, setSubmitting] = useState<BehaviorBucket | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    consultApi.fetchUniversalCard().then(setUniversalCard).catch(() => setUniversalCard(null));
  }, []);

  async function handleBucket(bucket: BehaviorBucket) {
    if (submitting) return;
    setError('');
    setSubmitting(bucket);
    try {
      const sessionId = await startWithBucket(bucket);
      navigate(`/consult/session/${sessionId}`);
    } catch (err) {
      setError((err as Error).message || '发起咨询失败，请稍后重试');
      setSubmitting(null);
    }
  }

  return (
    <PageContent className="consult-index">
      {/* 0 输入通用安全卡（秒级展示） */}
      {universalCard && (
        <section className="safety-card safety-card--universal">
          <h2 className="safety-card__title">{universalCard.title}</h2>
          <div className="safety-card__content">{universalCard.content}</div>
        </section>
      )}

      <h1 className="consult-index__title">他现在是什么情况？</h1>
      <p className="consult-index__hint">点选最符合的一项，我们一步步来</p>

      <div className="bucket-grid">
        {BUCKET_ORDER.map((bucket) => (
          <button
            key={bucket}
            type="button"
            className={`bucket-btn${REDLINE_BUCKETS.has(bucket) ? ' bucket-btn--redline' : ''}`}
            disabled={submitting !== null}
            onClick={() => void handleBucket(bucket)}
          >
            {submitting === bucket ? '进入中…' : BUCKET_UI_LABELS[bucket]}
          </button>
        ))}
      </div>

      {error && <div className="consult-error" role="alert">{error}</div>}

      <div className="consult-index__footer">
        <a href="/consult/history">查看咨询记录</a>
      </div>
    </PageContent>
  );
}

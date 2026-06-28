export interface ChatBubbleProps {
  variant: 'user' | 'ai';
  text: string;
  timestamp?: string;
}

/**
 * 聊天气泡 — 用户右对齐(accent-container)，AI 左对齐(surface)。
 * 右下/左下直角。
 */
export default function ChatBubble({ variant, text, timestamp }: ChatBubbleProps) {
  return (
    <>
      {timestamp && <span className="cf-bubble__timestamp">{timestamp}</span>}
      <div className={`cf-bubble cf-bubble--${variant}`}>{text}</div>
    </>
  );
}

import { describe, expect, it } from 'vitest';
import { readingSection, readingSnippet } from './reading';

describe('真实摄取内容的阅读呈现', () => {
  it('结构化卡片摘录显示情境，排除标题和下一字段标签', () => {
    expect(readingSnippet('title: 自然结果等待法\nscenario: 孩子在家拒绝约定的任务\nimmediate_action: 原文动作')).toBe('孩子在家拒绝约定的任务');
  });
  it('普通文字与不含情境的摘录保持完整，不猜测或丢弃内容', () => {
    expect(readingSnippet('先离开广播声，再讨论下一步')).toBe('先离开广播声，再讨论下一步');
    expect(readingSnippet('title: 只有标题')).toBe('title: 只有标题');
  });
  it('正式摄取节点使用中文冒号，后续元信息字段不混入情境', () => {
    expect(readingSnippet('\n title：自然结果等待法\nscenario：适用于家庭日常场景\nbehavior_type：其他\nsetting：家庭')).toBe('适用于家庭日常场景');
  });
  it('只去与小节标题完全一致的前导定位标记，正文中的斜线原样保留', () => {
    expect(readingSection('场景背景', '/场景背景/\n一位家长回顾了 8/12 的经历。')).toBe('一位家长回顾了 8/12 的经历。');
    expect(readingSection('场景背景', '/其他标记/ 正文')).toBe('/其他标记/ 正文');
  });
});

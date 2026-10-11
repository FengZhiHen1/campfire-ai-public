import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReadableText } from './ReadableText';

describe('回答与资料的可读排版', () => {
  it('标题、列表、引用与强调使用实际语义结构', () => {
    const { container } = render(<ReadableText text={'## 下一步\n\n- **先观察**\n- 再记录\n\n1. 留出时间\n2. 回看变化\n\n> 这是原文引用\n\n记录 `时间`'} />);
    expect(screen.getByRole('heading', { name: '下一步' })).toBeDefined();
    expect(container.querySelectorAll('li')).toHaveLength(4);
    expect(container.querySelector('strong')?.textContent).toBe('先观察');
    expect(container.querySelector('blockquote')?.textContent).toBe('这是原文引用');
    expect(container.querySelector('code')?.textContent).toBe('时间');
  });
  it('原始 HTML 当成文本呈现，不执行资料或模型中的标签', () => {
    const { container } = render(<ReadableText text={'<script>alert(1)</script>'} />);
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toBe('<script>alert(1)</script>');
  });
  it('未完成的流式标题和列表标记不使渲染停滞', () => {
    const { container } = render(<ReadableText text={'# \n\n- \n\n1. '} />);
    expect(container.querySelectorAll('p')).toHaveLength(3);
  });
});

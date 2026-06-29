// React 移植版：View→div, Text→span
import './MarkdownRenderer.css';

interface InlineToken {
  type: 'text' | 'bold' | 'italic' | 'code';
  content: string;
}

interface MdBlock {
  type: 'heading' | 'paragraph' | 'list-item' | 'code-block';
  level?: number;
  tokens: InlineToken[];
}

// ============================================================================
// 解析器：Markdown 文本 → MdBlock[]
// ============================================================================

function parseInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    const boldMatch = remaining.match(/^\*\*(.+?)\*\*/);
    const italicMatch = remaining.match(/^\*(.+?)\*/);
    const codeMatch = remaining.match(/^`([^`]+)`/);

    let earliestType: InlineToken['type'] | null = null;
    let earliestContent = '';
    let earliestRaw = '';
    let earliestIdx = Infinity;

    if (boldMatch) {
      const idx = remaining.indexOf(boldMatch[0]);
      if (idx < earliestIdx) {
        earliestIdx = idx;
        earliestType = 'bold';
        earliestContent = boldMatch[1];
        earliestRaw = boldMatch[0];
      }
    }
    if (italicMatch) {
      const idx = remaining.indexOf(italicMatch[0]);
      if (idx < earliestIdx) {
        earliestIdx = idx;
        earliestType = 'italic';
        earliestContent = italicMatch[1];
        earliestRaw = italicMatch[0];
      }
    }
    if (codeMatch) {
      const idx = remaining.indexOf(codeMatch[0]);
      if (idx < earliestIdx) {
        earliestIdx = idx;
        earliestType = 'code';
        earliestContent = codeMatch[1];
        earliestRaw = codeMatch[0];
      }
    }

    if (earliestType && earliestIdx < Infinity) {
      if (earliestIdx > 0) {
        tokens.push({ type: 'text', content: remaining.slice(0, earliestIdx) });
      }
      tokens.push({ type: earliestType, content: earliestContent });
      remaining = remaining.slice(earliestIdx + earliestRaw.length);
    } else {
      tokens.push({ type: 'text', content: remaining });
      remaining = '';
    }
  }

  return tokens;
}

function parseBlocks(content: string): MdBlock[] {
  const lines = content.split('\n');
  const blocks: MdBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // blank line → skip
    if (!trimmed) {
      i++;
      continue;
    }

    // code block: ``` ... ```
    if (trimmed.startsWith('```')) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({
        type: 'code-block',
        tokens: [{ type: 'text', content: codeLines.join('\n') }],
      });
      continue;
    }

    // heading
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length,
        tokens: parseInline(headingMatch[2]),
      });
      i++;
      continue;
    }

    // unordered list
    if (/^[-*+]\s+/.test(trimmed)) {
      const content = trimmed.replace(/^[-*+]\s+/, '');
      blocks.push({ type: 'list-item', tokens: parseInline(content) });
      i++;
      continue;
    }

    // ordered list
    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      blocks.push({ type: 'list-item', tokens: parseInline(orderedMatch[1]) });
      i++;
      continue;
    }

    // paragraph: collect until blank line or special line
    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() && !isSpecialLine(lines[i].trim())) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push({
      type: 'paragraph',
      tokens: parseInline(paraLines.join('\n')),
    });
  }

  return blocks;
}

function isSpecialLine(line: string): boolean {
  return (
    line.startsWith('#') ||
    line.startsWith('```') ||
    /^[-*+]\s+/.test(line) ||
    /^\d+\.\s+/.test(line)
  );
}

// ============================================================================
// 渲染组件
// ============================================================================

interface MarkdownRendererProps {
  content: string;
}

function InlineText({ token, blockType }: { token: InlineToken; blockType: string }) {
  if (token.type === 'bold') {
    return <span className={`md-${blockType} md-bold`}>{token.content}</span>;
  }
  if (token.type === 'italic') {
    return <span className={`md-${blockType} md-italic`}>{token.content}</span>;
  }
  if (token.type === 'code') {
    return <span className={`md-${blockType} md-inline-code`}>{token.content}</span>;
  }
  return <span className={`md-${blockType}`}>{token.content}</span>;
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) {
    return null;
  }

  const blocks = parseBlocks(content);

  return (
    <div className="md-root">
      {blocks.map((block, idx) => {
        switch (block.type) {
          case 'heading': {
            const Tag = `md-h${block.level ?? 1}`;
            return (
              <div key={idx} className={Tag}>
                {block.tokens.map((t, ti) => (
                  <InlineText key={ti} token={t} blockType={Tag} />
                ))}
              </div>
            );
          }

          case 'paragraph':
            return (
              <div key={idx} className="md-paragraph">
                {block.tokens.map((t, ti) => (
                  <InlineText key={ti} token={t} blockType="md-paragraph" />
                ))}
              </div>
            );

          case 'list-item':
            return (
              <div key={idx} className="md-list-item">
                <span className="md-list-item__bullet">•</span>
                <div className="md-list-item__body">
                  {block.tokens.map((t, ti) => (
                    <InlineText key={ti} token={t} blockType="md-list-item" />
                  ))}
                </div>
              </div>
            );

          case 'code-block':
            return (
              <div key={idx} className="md-code-block">
                <span className="md-code-block__text">{block.tokens[0]?.content ?? ''}</span>
              </div>
            );

          default:
            return null;
        }
      })}
    </div>
  );
}

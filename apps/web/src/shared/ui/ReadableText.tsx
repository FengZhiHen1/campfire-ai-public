/** 将回答和资料中的常用 Markdown 排成读物；所有内容仍由 React 转义。 */
import type { ReactNode } from 'react';

function inline(text: string): ReactNode[] {
  const occurrences = new Map<string, number>();
  return text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part) => {
    const occurrence = occurrences.get(part) ?? 0;
    occurrences.set(part, occurrence + 1);
    const key = `${part}:${occurrence}`;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={key}>{part.slice(1, -1)}</code>;
    return part;
  });
}

export function ReadableText({ text }: { text: string }) {
  const lines = text.split('\n');
  const blocks: ReactNode[] = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index] ?? '';
    if (line.trim() === '') { index += 1; continue; }
    const heading = /^#{1,6}\s+(.+)$/.exec(line);
    if (heading) { blocks.push(<h3 className="readable-heading" key={index}>{inline(heading[1] ?? '')}</h3>); index += 1; continue; }
    const unordered = /^\s*[-*+]\s+(.+)$/;
    const ordered = /^\s*\d+[.)]\s+(.+)$/;
    const listPattern = unordered.test(line) ? unordered : ordered.test(line) ? ordered : null;
    if (listPattern !== null) {
      const start = index;
      const items: ReactNode[] = [];
      while (index < lines.length && listPattern.test(lines[index] ?? '')) {
        items.push(<li key={index}>{inline(listPattern.exec(lines[index] ?? '')?.[1] ?? '')}</li>);
        index += 1;
      }
      blocks.push(listPattern === ordered ? <ol className="readable-list" key={start}>{items}</ol> : <ul className="readable-list" key={start}>{items}</ul>);
      continue;
    }
    if (/^>\s?/.test(line)) { blocks.push(<blockquote className="readable-quote" key={index}>{inline(line.replace(/^>\s?/, ''))}</blockquote>); index += 1; continue; }
    const start = index;
    const paragraph: string[] = [];
    while (index < lines.length && (lines[index] ?? '').trim() !== '' && !/^#{1,6}\s|^>\s?|^\s*[-*+]\s|^\s*\d+[.)]\s/.test(lines[index] ?? '')) {
      paragraph.push(lines[index] ?? '');
      index += 1;
    }
    // 流式输入可能只到达标题或列表标记；仍显示原文并推进，不能卡住渲染。
    if (paragraph.length === 0) { paragraph.push(line); index += 1; }
    blocks.push(<p className="readable-paragraph" key={start}>{inline(paragraph.join('\n'))}</p>);
  }
  return <>{blocks}</>;
}

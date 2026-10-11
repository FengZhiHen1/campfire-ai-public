/** 摄取摘录的阅读呈现：只去已识别的结构标签，不修改原始记录。 */
export function readingSnippet(snippet: string): string {
  const content = snippet.trimStart();
  if (!/^title[:：]/.test(content)) return snippet;
  const scenario = /\bscenario[:：]\s*([\s\S]*?)(?=\n[a-z_]+[:：]|$)/.exec(content);
  return scenario?.[1]?.trim() || snippet;
}

/** 摄取节点可能带同名小节定位标记；标题已独立呈现时不再重复读它。 */
export function readingSection(heading: string, text: string): string {
  const content = text.trimStart();
  const marker = `/${heading}/`;
  return content.startsWith(marker) ? content.slice(marker.length).trimStart() : text;
}

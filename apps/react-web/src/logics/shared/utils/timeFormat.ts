const MS_PER_DAY = 86400000;

/** Format ISO datetime to relative display: "今天 14:30" / "昨天 09:15" / "6月3日 14:30" */
export function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const dayDiff = Math.floor((now.getTime() - date.getTime()) / MS_PER_DAY);
  const timeStr = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;

  if (dayDiff === 0) return `今天 ${timeStr}`;
  if (dayDiff === 1) return `昨天 ${timeStr}`;
  return `${date.getMonth() + 1}月${date.getDate()}日 ${timeStr}`;
}

/** Format Date to YYYY-MM-DD string */
export function formatDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

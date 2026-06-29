const MS_PER_MINUTE = 60000;
const MS_PER_HOUR = 3600000;
const MS_PER_DAY = 86400000;

/**
 * Format ISO datetime to relative display:
 * "刚刚" / "5 分钟前" / "2 小时前" / "昨天" / "3 天前" / "6月3日 14:30"
 * 对齐 OD home.html 最近咨询时间展示。
 */
export function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / MS_PER_MINUTE);
  const diffHours = Math.floor(diffMs / MS_PER_HOUR);
  const dayDiff = Math.floor(diffMs / MS_PER_DAY);
  const timeStr = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;

  if (diffMins < 1) return '刚刚';
  if (diffHours < 1) return `${diffMins} 分钟前`;
  if (dayDiff < 1) return `${diffHours} 小时前`;
  if (dayDiff === 1) return `昨天 ${timeStr}`;
  if (dayDiff < 7) return `${dayDiff} 天前`;
  return `${date.getMonth() + 1}月${date.getDate()}日 ${timeStr}`;
}

/** Format Date to YYYY-MM-DD string */
export function formatDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

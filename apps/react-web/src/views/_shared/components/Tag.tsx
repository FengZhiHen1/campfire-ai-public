export interface TagProps {
  variant?: 'default' | 'active' | 'success';
  label: string;
}

/**
 * 药丸形标签/徽章。OD 规格：8px 圆角，6×10px 内边距。
 */
export default function Tag({ variant = 'default', label }: TagProps) {
  const cls = `cf-tag${variant !== 'default' ? ` cf-tag--${variant}` : ''}`;
  return <span className={cls}>{label}</span>;
}

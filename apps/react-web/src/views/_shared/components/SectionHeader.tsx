import { Link } from 'react-router-dom';

export interface SectionHeaderProps {
  title: string;
  linkTo?: string;
  linkLabel?: string;
}

/**
 * 区块标题 + 右侧链接。
 */
export default function SectionHeader({ title, linkTo, linkLabel }: SectionHeaderProps) {
  return (
    <div className="cf-section-header">
      <h3 className="cf-section-header__title">{title}</h3>
      {linkTo && (
        <Link className="cf-section-header__link" to={linkTo}>
          {linkLabel ?? '查看全部 →'}
        </Link>
      )}
    </div>
  );
}

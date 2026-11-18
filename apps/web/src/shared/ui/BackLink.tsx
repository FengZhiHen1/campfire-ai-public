/** 返回实际来源页；直接打开深链时回到明确的默认入口。 */
import { Link, useLocation, useNavigate } from 'react-router';

import { safeReturnTo } from './returnTo';

export function BackChevron() {
  return (
    <svg className="sp-back-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <path d="m14.7 5.7-6.3 5.6a1 1 0 0 0 0 1.4l6.3 5.6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function BackLink({ fallback, children }: { fallback: string; children?: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const returnTo = safeReturnTo(location.state);
  return (
    <Link className="sp-back" aria-label={children ?? '返回'} to={returnTo ?? fallback} onClick={(event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const historyState: unknown = window.history.state;
      if (returnTo === null && typeof historyState === 'object' && historyState !== null && 'idx' in historyState
        && typeof historyState.idx === 'number' && historyState.idx > 0) {
        event.preventDefault();
        void navigate(-1);
      }
    }}>
      <BackChevron />
      {children}
    </Link>
  );
}

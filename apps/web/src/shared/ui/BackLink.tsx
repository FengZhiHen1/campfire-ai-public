/** 返回实际来源页；直接打开深链时回到明确的默认入口。 */
import { Link, useLocation, useNavigate } from 'react-router';

import { safeReturnTo } from './returnTo';

export function BackLink({ fallback, children = '← 返回' }: { fallback: string; children?: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const returnTo = safeReturnTo(location.state);
  return (
    <Link className="sp-back" to={returnTo ?? fallback} onClick={(event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const historyState: unknown = window.history.state;
      if (returnTo === null && typeof historyState === 'object' && historyState !== null && 'idx' in historyState
        && typeof historyState.idx === 'number' && historyState.idx > 0) {
        event.preventDefault();
        void navigate(-1);
      }
    }}>{children}</Link>
  );
}

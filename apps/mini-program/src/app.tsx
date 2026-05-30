import './polyfills'

import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { ErrorBoundary } from './views/shared/components/ErrorBoundary';
import { useProfile } from './logics/profiles';

import './app.scss';

function App(props: { children?: ReactNode }) {
  const { fetchProfiles } = useProfile();

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  return <ErrorBoundary>{props.children}</ErrorBoundary>
}

export default App

import './polyfills'

import type { ReactNode } from 'react';
import { ErrorBoundary } from './views/shared/components/ErrorBoundary';

import './app.scss';

function App(props: { children?: ReactNode }) {
  return <ErrorBoundary>{props.children}</ErrorBoundary>
}

export default App

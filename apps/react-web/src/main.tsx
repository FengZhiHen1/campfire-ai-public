import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@/views/_shared/tokens.css';
import '@/views/_shared/animations.css';
import '@/views/_shared/global.css';
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

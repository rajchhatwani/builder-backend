import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@knadh/oat/oat.min.css'
import '@knadh/oat/oat.min.js'
import './index.css'
import { QueryClientProvider } from '@tanstack/react-query'
import App from './App.tsx'
import { ErrorBoundary } from './shell/ErrorBoundary'
import { queryClient } from './queryClient'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </QueryClientProvider>
  </StrictMode>,
)

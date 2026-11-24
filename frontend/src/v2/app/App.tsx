import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { I18nProvider, useT } from '../i18n'
import { EmptyState, ErrorBoundary, ToastProvider, TooltipProvider } from '../ui'
import type { ReactNode } from 'react'
import { createAppRouter } from './router'
import { ThemeProvider } from './theme'
import '../tokens/tokens.css'
import '../ui/ui.css'
import '../patterns/patterns.css'
import './app.css'

function BrowserGate({ children }: { children: ReactNode }) {
  const t = useT()
  const platform = navigator.userAgent
  const appleMobile = platform.match(/(?:iPhone|iPad|iPod).*?OS (\d+)_(\d+)/)
  const androidChrome = platform.match(/Android.*?Chrome\/(\d+)/)
  const outdatedApple = appleMobile && (Number(appleMobile[1]) < 16 || (Number(appleMobile[1]) === 16 && Number(appleMobile[2]) < 4))
  const outdatedAndroid = androidChrome && Number(androidChrome[1]) < 110
  if (outdatedApple || outdatedAndroid || globalThis.CSS?.supports?.('container-type', 'inline-size') === false) {
    return <main className="v2-main"><EmptyState title={t('shell.browserUpdate')} description={t('shell.browserUpdateDescription')} /></main>
  }
  return children
}

export function App({ queryClient = defaultQueryClient, router = defaultRouter }: {
  queryClient?: QueryClient
  router?: ReturnType<typeof createAppRouter>
}) {
  return (
    <I18nProvider>
      <ThemeProvider>
        <BrowserGate>
          <ErrorBoundary>
            <ToastProvider>
              <TooltipProvider>
                <QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>
              </TooltipProvider>
            </ToastProvider>
          </ErrorBoundary>
        </BrowserGate>
      </ThemeProvider>
    </I18nProvider>
  )
}

const defaultQueryClient = new QueryClient()
const defaultRouter = createAppRouter(defaultQueryClient)

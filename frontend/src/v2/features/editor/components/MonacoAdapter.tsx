import { lazy, Suspense } from 'react'
import { useT } from '../../../i18n'
import { Alert, CodeBlock, ErrorBoundary, Skeleton, Stack } from '../../../ui'

export type CodeEditorProps = {
  path: string
  value: string
  readOnly: boolean
  language: string
  line?: number
  onChange: (value: string) => void
  onCursor: (line: number, column: number) => void
  onProblems: (problems: { line: number; message: string }[]) => void
}

const Monaco = lazy(() => import('./MonacoSurface'))

export function MonacoAdapter(props: CodeEditorProps) {
  const t = useT()
  return <ErrorBoundary fallback={() => <Stack className="v2-editor-inset">
    <Alert tone="warning">{t('editor.editorFallback')}</Alert>
    <CodeBlock code={props.value} label={t('editor.codeLabel', { path: props.path })} />
  </Stack>}>
    <Suspense fallback={<Skeleton lines={12} label={t('editor.loadingCode')} />}>
      <Monaco {...props} />
    </Suspense>
  </ErrorBoundary>
}

import Editor from '@monaco-editor/react'
import type { OnMount } from '@monaco-editor/react'
import { useEffect, useRef, useState } from 'react'
import '../../../../shell/ai/monacoSetup'
import { useT } from '../../../i18n'
import { Skeleton } from '../../../ui'
import type { CodeEditorProps } from './MonacoAdapter'

const palette = () => document.documentElement.dataset.theme === 'dark' ? 'vs-dark' : 'vs'

export default function MonacoSurface({ path, value, readOnly, language, line, onChange, onCursor, onProblems }: CodeEditorProps) {
  const t = useT()
  const [theme, setTheme] = useState(palette)
  const editorRef = useRef<Parameters<OnMount>[0]>(null)
  const lineRef = useRef(line)
  lineRef.current = line
  const label = t('editor.codeLabel', { path })

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(palette()))
    observer.observe(document.documentElement, { attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const instance = editorRef.current
    if (instance && line) {
      instance.setPosition({ lineNumber: line, column: 1 })
      instance.revealLineInCenterIfOutsideViewport(line)
    }
  }, [line])

  return <Editor
    height="100%"
    language={language}
    value={value}
    theme={theme}
    loading={<Skeleton lines={12} label={t('editor.loadingCode')} />}
    onChange={content => { if (!readOnly) onChange(content ?? '') }}
    onValidate={markers => onProblems(markers.filter(marker => marker.severity >= 4).map(marker => ({
      line: marker.startLineNumber, message: marker.message,
    })))}
    onMount={instance => {
      editorRef.current = instance
      const subscription = instance.onDidChangeCursorPosition(event => onCursor(event.position.lineNumber, event.position.column))
      instance.onDidDispose(() => subscription.dispose())
      if (lineRef.current) {
        instance.setPosition({ lineNumber: lineRef.current, column: 1 })
        instance.revealLineInCenterIfOutsideViewport(lineRef.current)
      }
    }}
    // gate-exempt: Monaco's option identifiers and font sizing use its numeric API.
    options={{ readOnly, ariaLabel: label, automaticLayout: true, fontSize: 13, fontFamily: 'IBM Plex Mono, monospace',
      minimap: { enabled: true, showSlider: 'always' }, scrollBeyondLastLine: false, wordWrap: 'on', renderLineHighlight: 'line',
      codeLens: false, tabSize: 4, accessibilitySupport: 'auto' }}
  />
}

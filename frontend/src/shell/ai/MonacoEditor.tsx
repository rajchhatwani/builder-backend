import Editor from '@monaco-editor/react'
import './monacoSetup'

export interface MonacoEditorProps { path: string; language: string; value: string; readOnly: boolean; onChange: (v: string) => void; onSave: () => void; label: string }

/** The only module that imports Monaco. Always loaded through React.lazy (see CodeView). */
export default function MonacoEditor({ path, language, value, readOnly, onChange, onSave, label }: MonacoEditorProps) {
  return (
    <div className="stage-editor" role="group" aria-label={label} data-testid="code-editor">
      <Editor
        height="100%"
        path={path}
        language={language}
        value={value}
        theme={window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'vs-dark' : 'vs'}
        loading={<p className="muted small-text">Loading editor…</p>}
        onChange={(v) => onChange(v ?? '')}
        onMount={(ed, monaco) => { ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSave()) }}
        options={{ readOnly, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, wordWrap: 'on', automaticLayout: true, ariaLabel: label, tabSize: 4 }}
      />
    </div>
  )
}

import { useMemo } from 'react'
import { buildTree, type TreeNode, type WsFile } from '../../../../shell/ai/stageLogic'
import { useT } from '../../../i18n'
import { Button, Field, Input, Row, Stack } from '../../../ui'

export function ExplorerTree({ files, active, onPick }: { files: WsFile[]; active?: string; onPick: (path: string) => void }) {
  const t = useT()
  const tree = useMemo(() => buildTree(files), [files])
  return <nav aria-label={t('editor.files')}><Stack gap={0}>
    {tree.map(node => <Branch key={node.path} node={node} active={active} onPick={onPick} />)}
  </Stack></nav>
}

function Branch({ node, active, onPick }: { node: TreeNode; active?: string; onPick: (path: string) => void }) {
  const t = useT()
  if (node.file) return <Button variant="ghost" className="v2-editor-entry" title={t('editor.filePath', { path: node.path })}
    aria-current={active === node.path ? 'true' : undefined} onClick={() => onPick(node.path)}>
    <span>{node.name}</span>{node.file.zone && <span className="v2-muted v2-small">{t(node.file.zone === 'custom' ? 'editor.custom' : 'editor.generated')}</span>}
  </Button>

  return <details open>
    <summary className="v2-editor-folder">{node.name}</summary>
    <Stack gap={0} className="v2-editor-branch">
      {node.children.map(child => <Branch key={child.path} node={child} active={active} onPick={onPick} />)}
    </Stack>
  </details>
}

const maxHits = 100

export function FileSearch({ files, contents, value, onChange, onPick }: {
  files: WsFile[]
  contents: ReadonlyMap<string, string>
  value: string
  onChange: (value: string) => void
  onPick: (path: string, line?: number) => void
}) {
  const t = useT()
  const results = useMemo(() => {
    const term = value.trim().toLowerCase()
    const hits: { path: string; line?: number; text?: string }[] = []
    if (!term) return hits
    for (const { path } of files) {
      if (path.toLowerCase().includes(term)) hits.push({ path })
      const content = contents.get(path)
      if (content !== undefined) {
        const lines = content.split(/\r?\n/)
        for (const [index, text] of lines.entries()) {
          if (hits.length > maxHits) break
          if (text.toLowerCase().includes(term)) hits.push({ path, line: index + 1, text: text.trim() })
        }
      }
      if (hits.length > maxHits) break
    }
    return hits
  }, [files, contents, value])
  return <Stack gap={2}>
    <Field label={t('editor.search')} hint={t('editor.searchScope', { count: contents.size })}>{attrs =>
      <Input {...attrs} type="search" value={value} onChange={event => onChange(event.target.value)} />
    }</Field>
    {value.trim() && results.length === 0 && <p role="status">{t('editor.noMatches')}</p>}
    {results.length > maxHits && <p role="status">{t('editor.searchLimit', { count: maxHits })}</p>}
    <Stack gap={0}>
      {results.slice(0, maxHits).map(({ path, line, text }) => <Button key={JSON.stringify([path, line])} variant="ghost"
        className="v2-editor-result" onClick={() => onPick(path, line)}>
        <Stack gap={0}><Row gap={1}>{t(line ? 'editor.location' : 'editor.filePath', { path, line: line ?? 0 })}</Row>
          {text && <code className="v2-muted v2-small">{text}</code>}
        </Stack>
      </Button>)}
    </Stack>
  </Stack>
}

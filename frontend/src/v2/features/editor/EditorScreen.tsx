import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useBlocker, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useMemo, useReducer, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '../../../api/client'
import { languageFor, type WsFile } from '../../../shell/ai/stageLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, PageHeader } from '../../patterns'
import type { SectionSearch } from '../../projectNavigation'
import { editorSectionRoute as route } from '../../patterns/editorLink'
import { Alert, Badge, Breadcrumb, Button, DesktopOnlyCard, EmptyState, Field, IconButton, Row, Select, Skeleton, Stack } from '../../ui'
import { validateWorkspaceContent } from '../../validators'
import { accountOptions, contentOptions, editorKeys, filesOptions, kitOptions, manifestOptions, membersOptions, useFileSave, useZipDownload, workspacesOptions } from './api/editor'
import { EditorPanels } from './components/EditorPanels'
import { ExplorerTree, FileSearch } from './components/Explorer'
import { MonacoAdapter } from './components/MonacoAdapter'
import { draftReducer } from './state/drafts'
import './editor.css'

const supportedLanguages = ['python', 'json', 'yaml', 'markdown', 'ini', 'sql', 'shell', 'plaintext']
const emptyFiles: WsFile[] = []
const filename = (path: string) => path.split('/').at(-1) ?? path

export default function EditorScreen() {
  const t = useT()
  const { projectId } = useParams({ from: route })
  const { workspace, source } = useSearch({ from: route })
  const [mountEditor, setMountEditor] = useState(() => !document.body.clientWidth || document.body.clientWidth >= 700)
  return <div ref={element => {
    if (!element || mountEditor || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width >= 700) setMountEditor(true)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }} className="v2-editor-viewport">
    <div className="v2-phone-only v2-editor-mobile"><Stack>
      <PageHeader title={t('nav.code')} />
      <DesktopOnlyCard />
    </Stack></div>
    {mountEditor && <div className="v2-phone-hidden v2-editor-desktop"><EditorWorkspace key={JSON.stringify([projectId, workspace, source])} /></div>}
  </div>
}

function EditorWorkspace() {
  const t = useT()
  const { projectId } = useParams({ from: route })
  const search = useSearch({ from: route })
  const client = useQueryClient()
  const navigate = useNavigate({ from: route })
  const workspace = search.workspace ?? ''
  const source = workspace ? 'workspace' : search.source ?? 'kit'
  const [drafts, dispatch] = useReducer(draftReducer, {})
  const activity = search.view === 'search' ? 'search' : 'files'
  const setActivity = (view?: 'search') => void navigate({ search: previous => ({ ...previous, view }), replace: true })
  const [editorFeedback, setEditorFeedback] = useState<{
    key: string; cursor?: { line: number; column: number }; problems?: { line: number; message: string }[]
  }>()
  const workspaces = useQuery(workspacesOptions(projectId))
  const workspaceQuery = useQuery({ ...filesOptions(projectId, workspace), enabled: Boolean(workspace) })
  const kit = useQuery({ ...kitOptions(projectId), enabled: source === 'kit' })
  const manifest = useQuery({ ...manifestOptions(projectId), enabled: source === 'manifest' })
  const account = useQuery({ ...accountOptions, enabled: Boolean(workspace) })
  const members = useQuery({ ...membersOptions(projectId), enabled: Boolean(workspace) })
  const zip = useZipDownload(projectId)
  const save = useFileSave(projectId, workspace)
  const role = members.data?.find(member => member.user_id === account.data?.id)?.role
  const canWrite = role === 'owner' || role === 'editor'
  const query = workspace ? workspaceQuery : source === 'kit' ? kit : manifest
  const files = useMemo(() => {
    if (workspace) return workspaceQuery.data ?? emptyFiles
    if (source === 'manifest') return manifest.data?.files.map(file => ({ ...file, zone: '', editable: false })) ?? emptyFiles
    return kit.data ? [...kit.data.keys()].map(path => ({ path, zone: 'generated', editable: false, size: 0 })) : emptyFiles
  }, [workspace, workspaceQuery.data, kit.data, manifest.data, source])

  const active = search.file ?? files[0]?.path
  const entry = files.find(item => item.path === active)
  const paths = new Set(files.map(file => file.path))
  const openFiles = [...new Set([...(search.openFiles ?? []).filter(path => paths.has(path)), ...(entry ? [entry.path] : [])])]
  const file = useQuery({ ...contentOptions(projectId, workspace, active ?? ''), enabled: Boolean(workspace && entry) })
  const key = JSON.stringify([projectId, workspace, source, active])
  const draft = drafts[key]
  const current = file.data
  const contents = new Map<string, string>()
  if (workspace && activity === 'search') {
    for (const [queryKey, result] of client.getQueriesData<typeof current>({ queryKey: [...editorKeys.workspace(projectId, workspace), 'content'] })) {
      const path = String(queryKey.at(-1))
      const local = drafts[JSON.stringify([projectId, workspace, source, path])]
      if (result) contents.set(path, local?.content ?? result.content)
    }
  }
  const writable = Boolean(workspace && current?.editable && canWrite)
  const value = draft?.content ?? (workspace ? current?.content : source === 'kit' && active ? kit.data?.get(active) : undefined)
  const saving = save.isPending && save.variables?.path === active
  const saved = save.isSuccess && save.variables?.path === active && !draft
  const saveError = save.variables?.path === active ? save.error : null
  const validation = draft ? validateWorkspaceContent(draft.content) : undefined
  const busy = save.isPending
  const dirty = Object.keys(drafts).length > 0
  const blocker = useBlocker({
    enableBeforeUnload: dirty || busy,
    withResolver: true,
    shouldBlockFn: ({ current, next }) => {
      if (!dirty && !busy) return false
      if (next.pathname !== current.pathname) return true
      const selection = next.search as SectionSearch
      return (selection.workspace ?? '') !== workspace || selection.source !== search.source
    },
  })
  const language = active ? languageFor(active) : 'plaintext'
  const feedback = editorFeedback?.key === key ? editorFeedback : undefined
  const problems = feedback?.problems ?? []
  const cursor = feedback?.cursor
  const retry = () => void query.refetch()
  const openBuild = <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'build' }}>{t('nav.build')}</Link></Button>

  function pick(path: string, line?: number) {
    void navigate({ search: previous => ({ ...previous, file: path, line, openFiles: [...new Set([...openFiles, path])] }) })
  }

  function close(path: string) {
    const remaining = openFiles.filter(open => open !== path)
    void navigate({ search: previous => ({ ...previous, openFiles: remaining, line: active === path ? undefined : previous.line,
      file: active === path ? remaining.at(-1) ?? (files.length > 1 ? files.find(file => file.path !== path)?.path : undefined) : active }) })
  }

  function changeSource(value: string) {
    const next = value === 'kit' || value === 'manifest' ? value : undefined
    void navigate({ search: { source: next, workspace: next ? undefined : value } })
  }

  async function saveDraft() {
    if (!draft || !active || !writable || validation || busy) return
    try {
      await save.mutateAsync({ path: active, content: draft.content, sha: draft.sha })
      dispatch({ type: 'clear', key })
    } catch { /* The mutation keeps the failure available for recovery. */ }
  }

  function discard() {
    dispatch({ type: 'clear', key })
    save.reset()
  }

  async function reload() {
    if (!(await file.refetch()).isSuccess) throw new Error('file_reload')
    discard()
  }

  const fileIssue = file.error
  const writeConflict = saveError instanceof ApiError && saveError.status === 409
  const stale = writeConflict && saveError.code === 'file_changed'
  const showError = saveError instanceof ApiError ? saveError.code : ''
  const stateContent = query.isPending ? <Skeleton lines={12} label={t('editor.loadingFiles')} />
    : query.isError ? <LoadError error={query.error} retry={retry} />
    : files.length === 0 ? <EmptyState title={t('editor.empty')} action={openBuild} />
    : !entry ? <EmptyState title={t('editor.fileMissing')} action={<Button onClick={() => pick(files[0].path)}>{t('editor.openFirst')}</Button>} />
    : source === 'manifest' ? <Stack>
      <p>{t('editor.fileSize', { size: entry.size })}</p>
      <p>{t('editor.manifestOnly')}</p>
      <Row><Button onClick={() => void navigate({ search: { source: 'kit', file: entry.path } })}>{t('editor.openKit')}</Button></Row>
    </Stack>
    : fileIssue && !draft ? <LoadError error={fileIssue} file retry={() => void file.refetch()} />
    : value === undefined ? <Skeleton lines={12} label={t('editor.loadingCode')} />
    : null

  return <section className="v2-editor" data-testid="v2-editor" aria-label={t('nav.code')} onKeyDownCapture={event => {
    if (writable && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault()
      if (!stale) void saveDraft()
    }
  }}>
    <Stack gap={1} className="v2-editor-activity" role="group" aria-label={t('editor.activity')}>
      <IconButton variant="ghost" label={t('editor.files')} aria-pressed={activity === 'files'} onClick={() => setActivity()}>
        <EditorIcon name="files" />
      </IconButton>
      <IconButton variant="ghost" label={t('editor.search')} aria-pressed={activity === 'search'} onClick={() => setActivity('search')}>
        <EditorIcon name="search" />
      </IconButton>
      <IconButton variant="ghost" asChild label={t('editor.dashboard')}>
        <Link to="/projects/$projectId/overview" params={{ projectId }}><EditorIcon name="dashboard" /></Link>
      </IconButton>
      <IconButton variant="ghost" asChild label={t('nav.history')}>
        <Link to="/projects/$projectId/$section" params={{ projectId, section: 'history' }}><EditorIcon name="history" /></Link>
      </IconButton>
      <div className="v2-editor-spacer" />
      <IconButton variant="ghost" label={t('editor.download')} disabled={zip.isPending} onClick={() => zip.mutate()}>
        <EditorIcon name="download" />
      </IconButton>
    </Stack>
    <Stack gap={2} className="v2-editor-explorer">
      <Stack gap={2} className="v2-editor-inset">
        <h1>{t('editor.explorer')}</h1>
        <Field label={t('editor.source')}>{attrs => <Select triggerProps={attrs}
          value={workspace || source} onValueChange={changeSource}
          options={[
            { value: 'kit', label: t('editor.kit') }, { value: 'manifest', label: t('editor.manifest') },
            ...(workspaces.data ?? []).filter(item => ['active', 'rolled_back'].includes(item.state) || item.id === workspace)
              .map(item => ({ value: item.id, label: item.name })),
            ...(workspace && !workspaces.data?.some(item => item.id === workspace) ? [{ value: workspace, label: t('editor.draft') }] : []),
          ]} />}</Field>
        {source === 'manifest' && manifest.data && <Stack gap={1} className="v2-small v2-muted">
          <span>{t('editor.manifestSummary', { count: manifest.data.total_files, size: manifest.data.total_size })}</span>
          <span>{t('editor.manifestHash', { hash: manifest.data.spec_hash.slice(0, 12) })}</span>
        </Stack>}
        {workspaces.isError && <Alert tone="warning" action={<Button onClick={() => void workspaces.refetch()}>{t('common.retry')}</Button>}>{t('editor.loadWorkspacesFailed')}</Alert>}
      </Stack>
      <div className={activity === 'search' ? 'v2-editor-explorer-content v2-editor-inset' : 'v2-editor-explorer-content'}>
        {activity === 'search' ? <FileSearch files={files}
          contents={source === 'kit' ? kit.data ?? contents : contents} value={search.q ?? ''}
          onChange={q => void navigate({ search: previous => ({ ...previous, q: q || undefined }), replace: true })} onPick={pick} />
          : <ExplorerTree files={files} active={active} onPick={pick} />}
      </div>
    </Stack>
    <div className="v2-editor-main">
      <Row gap={0} className="v2-editor-tabs" role="group" aria-label={t('editor.openFiles')}>
        {openFiles.map(path => <Row gap={0} key={path} className="v2-editor-file-tab" data-selected={active === path}>
          <Button variant="ghost" aria-current={active === path ? 'true' : undefined} title={t('editor.filePath', { path })} onClick={() => pick(path)}>
            {filename(path)}
            {active === path && entry?.zone && <Badge>{t(entry.zone === 'custom' ? 'editor.custom' : 'editor.generated')}</Badge>}
          </Button>
          {openFiles.length > 1 && <IconButton variant="ghost" label={t('editor.closeFile', { path })} onClick={() => close(path)}><EditorIcon name="close" /></IconButton>}
        </Row>)}
      </Row>
      <Stack gap={2} className="v2-editor-inset v2-editor-toolbar">
        {active && <Breadcrumb label={t('editor.fileBreadcrumb')} items={active.split('/').map((part, index) => ({ id: String(index), content: part }))} />}
        {(zip.isError || zip.isPending) && (zip.isPending ? <Skeleton lines={1} label={t('editor.downloading')} />
          : <LoadError error={zip.error} retry={() => zip.mutate()} download />)}
        {workspace && entry?.editable && (account.isError || members.isError) && <Alert tone="warning" action={<Button onClick={() => {
          void account.refetch()
          void members.refetch()
        }}>{t('common.retry')}</Button>}>{t('editor.loadRoleFailed')}</Alert>}
        {writeConflict && (stale
          ? <ConflictBanner action={<ConfirmDestructive trigger={<Button disabled={busy}>{t('editor.reloadLatest')}</Button>}
            title={t('editor.discardTitle')} description={t('editor.discardBody')} action={t('common.discard')} onConfirm={reload} />}>
            {t('editor.stale')}
          </ConflictBanner>
          : <ConflictBanner onReload={() => { save.reset(); void file.refetch() }}>{t(showError === 'workspace_inactive' ? 'editor.inactive' : 'editor.busy')}</ConflictBanner>)}
        {saveError && !writeConflict && <Alert tone="danger">{t(showError === 'dependency_manifest_denied' ? 'editor.dependencies'
          : saveError instanceof ApiError && saveError.status === 403 ? 'editor.saveForbidden' : 'editor.saveFailed')}</Alert>}
        {validation && <p className="v2-field-error" role="alert">{t(validation)}</p>}
        {writable && <Row gap={2}>
          <Button variant="primary" disabled={!draft || busy || Boolean(validation) || stale} onClick={() => void saveDraft()}>
            {t(saving ? 'common.saving' : 'common.save')}
          </Button>
          {draft && !stale && <ConfirmDestructive trigger={<Button disabled={busy}>{t('common.discard')}</Button>}
            title={t('editor.discardTitle')} description={t('editor.discardBody')} action={t('common.discard')} onConfirm={discard} />}
          <span role="status">{saved ? t('common.saved') : draft ? t('common.unsaved') : undefined}</span>
        </Row>}
      </Stack>
      <div className="v2-editor-surface">
        {stateContent ? <div className="v2-editor-inset">{stateContent}</div>
          : active && value !== undefined && <MonacoAdapter key={key} path={active} value={value} readOnly={!writable || saving}
            language={supportedLanguages.includes(language) ? language : 'plaintext'} line={search.line}
            onChange={content => {
              if (current && writable && !saving) dispatch({ type: 'edit', key, content, original: current.content, sha: current.sha256 })
            }}
            onCursor={(line, column) => setEditorFeedback(previous => ({ ...(previous?.key === key ? previous : {}), key, cursor: { line, column } }))}
            onProblems={problems => setEditorFeedback(previous => ({ ...(previous?.key === key ? previous : {}), key, problems }))} />}
      </div>
    </div>
    <EditorPanels projectId={projectId} run={search.run} workspace={search.workspace} panel={search.tab} problems={problems}
      onPanel={tab => void navigate({ search: previous => ({ ...previous, tab }) })}
      onLine={line => { if (active) pick(active, line) }} />
    <Row gap={4} className="v2-editor-status">
      <span>{t(writable ? 'editor.editable' : 'editor.readOnly')}</span>
      {entry && <span>{t(source === 'manifest' ? 'editor.manifest' : source === 'kit' ? 'editor.kit'
        : entry.zone === 'custom' ? 'editor.custom' : 'editor.generatedHint')}</span>}
      {value !== undefined && <>
        <span className="v2-editor-spacer" />
        <span>{t('editor.language.' + language)}</span>
        <span>{t('editor.utf8')}</span>
        <span>{t('editor.cursor', { line: cursor?.line ?? search.line ?? 1, column: cursor?.column ?? 1 })}</span>
      </>}
    </Row>
    <ConfirmDestructive title={t('editor.discardTitle')} description={t(busy ? 'editor.saveInProgress' : 'editor.discardBody')}
      open={blocker.status === 'blocked'} pending={busy} action={t('common.discard')}
      onOpenChange={open => { if (!open && blocker.status === 'blocked') blocker.reset() }}
      onConfirm={() => blocker.proceed?.()} />
  </section>
}

function LoadError({ error, retry, file, download }: { error: unknown; retry: () => void; file?: boolean; download?: boolean }) {
  const t = useT()
  if (error instanceof ApiError && error.status === 409) return <ConflictBanner onReload={retry}>{t(
    error.code === 'workspace_inactive' ? 'editor.inactive' : download ? 'editor.downloadConflict' : 'common.conflict',
  )}</ConflictBanner>
  const key = error instanceof ApiError && error.code === 'email_not_verified' ? 'editor.verify'
    : error instanceof ApiError && error.status === 403 ? 'editor.forbidden'
    : error instanceof ApiError && error.code === 'spec_invalid' ? 'editor.specInvalid'
    : file && error instanceof ApiError && [413, 415, 422].includes(error.status) ? 'editor.binary'
    : download ? 'editor.downloadFailed' : file ? 'editor.loadFileFailed' : 'editor.loadFilesFailed'
  return <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t(key)}</Alert>
}

function EditorIcon({ name }: { name: 'files' | 'search' | 'dashboard' | 'history' | 'download' | 'close' }) {
  const paths: Record<typeof name, ReactNode> = {
    files: <path d="M8 7V3h9l4 4v10h-4M4 7h9l4 4v10H4zM13 7v4h4" />,
    search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 5 5" /></>,
    dashboard: <path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" />,
    history: <path d="M3 12a9 9 0 1 1 3 7M3 5v7h7m2-5v5l3 2" />,
    download: <path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
  }
  // gate-exempt: SVG icon coordinates describe the icon geometry.
  return <svg className="v2-editor-icon" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor">{paths[name]}</svg>
}

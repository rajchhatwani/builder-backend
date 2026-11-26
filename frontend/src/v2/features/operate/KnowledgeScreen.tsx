import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, ReadOnlyNote } from '../../patterns'
import { Button, Checkbox, EmptyState, Grid, Input, Stack, Textarea } from '../../ui'
import { aiText, resultLimit, roleIssue, sourceRoles } from '../../validators/operateAi'
import { sourcesOptions, useAddSource, useAiAccess, useAskKnowledge, useDeleteSource, useSearchKnowledge } from './api/ai'
import type { Source } from './api/ai'
import { runtimeError } from './api/live'
import type { LiveProps, Session } from './api/live'
import { canWrite } from './api/operate'
import { AiActions, AiFeedback, AiPermission, AiRuntime, useAiFormat } from './components/AiRuntime'
import { useOperateDate, useOperateSearch } from './components/Common'
import { Columns, data, key, Pager, Panel, serverFields, text } from './components/Runtime'

export default function KnowledgeScreen(props: LiveProps) {
  return <AiRuntime id={props} title={'knowledge'}>{session => <Knowledge session={session} writable={canWrite(props)} />}</AiRuntime>
}

const LIMIT = 50
const focusTitle = () => document.querySelector<HTMLInputElement>('[data-testid="source-title"]')?.focus()

function Knowledge({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const date = useOperateDate()
  const format = useAiFormat()
  const { search, change } = useOperateSearch()
  const page = search.page ?? 1
  const list = useQuery(sourcesOptions(session, { limit: LIMIT, offset: (page - 1) * LIMIT }))
  const access = useAiAccess(session, writable)
  const [notice, setNotice] = useState<'sourceAdded' | 'sourceDeleted'>()
  return <Stack gap={4}>
    <AiActions id={session.projectId} settings="knowledgesettings" testId="sources-refresh"
      refresh={() => Promise.all([list.refetch(), access.retry()])} />
    <p className="v2-muted" data-testid="knowledge-untrusted">{t(key('knowledgePlainText'))}</p>
    {notice && <p role="status" data-testid="source-notice">{t(key(notice))}</p>}
    <Panel title={'sources'}>
      {list.isPending || list.isError ? <AiFeedback error={list.error} retry={list.refetch} /> :
        list.data.items.length ? <Columns label={'sources'} names={['title', 'passages', 'allowed_roles', 'visibility', 'ownerId', 'created', 'manage']}
          rows={list.data.items.map(source => ({ id: source.id, testId: 'source-row', cells: [
            data(t, source.title), format.count(source.chunk_count), data(t, source.allowed_roles.join(', ')),
            t(key(source.owner_only ? 'ownerOnly' : 'sharedRoles')), data(t, source.owner_id), date(source.created_at),
            writable && (access.manage || source.owner_id === access.owner) ?
              <DeleteSource session={session} source={source} onDeleted={() => {
                setNotice('sourceDeleted')
                if (page > 1 && list.data.items.length === 1) change({ page: page - 1 })
              }} /> : data(t, null),
          ] }))} /> :
          <EmptyState title={t(key(access.manage ? 'noSources' : 'noVisibleSources'))} action={access.manage ?
            <Button onClick={focusTitle}>{t(key('addSource'))}</Button> :
            <Button onClick={() => void list.refetch()}>{t(key('refresh'))}</Button>} />}
      <Pager label={'sources'} page={page} total={list.data?.total ?? 0} size={LIMIT} change={page => change({ page })} />
    </Panel>
    <AiPermission access={access}>
      {access.manage ? <AddSource session={session} access={access} onAdded={() => {
        setNotice('sourceAdded')
        change({ page: undefined })
      }} /> : writable && <ReadOnlyNote>{t(key('sourceReadOnly'))}</ReadOnlyNote>}
    </AiPermission>
    <Grid>
      <SearchPassages session={session} />
      {access.ask ? <AskLibrary session={session} /> : !access.pending && !access.error &&
        <Panel title={'askLibrary'}><ReadOnlyNote>{t(key('askReadOnly'))}</ReadOnlyNote></Panel>}
    </Grid>
  </Stack>
}

function AddSource({ session, access, onAdded }: {
  session: Session; access: ReturnType<typeof useAiAccess>; onAdded: () => void
}) {
  const t = useT()
  const request = useAddSource(session)
  const [revision, setRevision] = useState(0)
  const errors = serverFields(request.error, {}, path => path.startsWith('allowed_roles.') ? 'allowed_roles' : path)
  const failure = runtimeError(request.error)
  if (failure?.code === 'content_too_large') errors.text = { key: key('value'), values: { value: failure.message } }
  if (failure && ['unknown_role', 'visibility_conflict', 'visibility_required'].includes(failure.code)) {
    errors.allowed_roles = { key: key('value'), values: { value: failure.message } }
  }
  return <Panel title={'addSource'}>
    <Form key={revision} preserveFocusOnSubmit fields={[
      { name: 'title', label: t(key('title')), validateWith: aiText('enterTitle', 200), errorTestId: 'source-create-error',
        control: attrs => <Input {...attrs} maxLength={200} data-testid="source-title" /> },
      { name: 'text', label: t(key('sourceText')), validateWith: aiText('pasteSource', access.textLimit),
        control: attrs => <Textarea {...attrs} maxLength={access.textLimit} data-testid="source-text" /> },
      { name: 'allowed_roles', label: t(key('allowed_roles')),
        hint: access.roles.length ? t(key('knownSourceRoles'), { roles: access.roles.join(', ') }) : t(key('sourceRolesHint')),
        validateWith: (value, form) => roleIssue(value, form.has('owner_only'), access.roles),
        control: attrs => <Input {...attrs} data-testid="source-roles" /> },
      { name: 'owner_only', label: t(key('onlyICanSee')), ownLabel: true,
        control: attrs => <Checkbox {...attrs} label={t(key('onlyICanSee'))} data-testid="source-owner" /> },
    ]} pending={request.isPending} serverErrors={errors}
      submitProps={{ 'data-testid': 'source-create' }} submitLabel={t(key(request.isPending ? 'addingSource' : 'addSource'))}
      onSubmit={form => {
        const roles = sourceRoles(text(form, 'allowed_roles'))
        request.mutate({ title: text(form, 'title'), text: String(form.get('text')),
          allowed_roles: roles.length ? roles : undefined, owner_only: form.has('owner_only') || undefined },
        { onSuccess: () => { setRevision(revision + 1); onAdded() } })
      }} />
    <AiFeedback error={request.error} retry={request.reset} write />
  </Panel>
}

function DeleteSource({ session, source, onDeleted }: { session: Session; source: Source; onDeleted: () => void }) {
  const t = useT()
  const request = useDeleteSource(session, source.id)
  return <Stack>
    <ConfirmDestructive trigger={<Button variant="danger" data-testid="source-delete"
      aria-label={t(key('deleteNamedSource'), { title: source.title })}>{t(key('delete'))}</Button>}
      title={t(key('deleteSource'))} description={t(key('deleteSourceHelp'), { title: source.title })}
      action={t(key('deleteSource'))} pending={request.isPending} onConfirm={async () => {
        await request.mutateAsync(undefined).then(onDeleted, () => undefined)
      }} />
    <AiFeedback error={request.error} retry={request.reset} write />
  </Stack>
}

function KnowledgeQuestion({ ask, pending, error, submit }: {
  ask?: boolean; pending: boolean; error: unknown; submit: (question: string, limit: number) => void
}) {
  const t = useT()
  const name = ask ? 'question' : 'query'
  const action = ask ? 'ask' : 'search'
  const length = ask ? 1000 : 500
  const max = ask ? 10 : 20
  return <Form preserveFocusOnSubmit fields={[
    { name, label: t(key(ask ? 'question' : 'searchQuery')), validateWith: aiText(ask ? 'enterQuestion' : 'enterQuery', length),
      control: attrs => <Input {...attrs} maxLength={length} data-testid={action + '-' + name} /> },
    { name: 'limit', label: t(key(ask ? 'citationLimit' : 'resultLimit')), validateWith: resultLimit(max),
      control: attrs => <Input {...attrs} type="number" min={1} max={max} step={1} defaultValue={ask ? 4 : 5} data-testid={action + '-limit'} /> },
  ]} pending={pending} serverErrors={serverFields(error)}
    submitProps={{ 'data-testid': action + '-run' }} submitLabel={t(key(pending ? (ask ? 'asking' : 'searching') : action))}
    onSubmit={form => submit(text(form, name), Number(text(form, 'limit')))} />
}

function SearchPassages({ session }: { session: Session }) {
  const t = useT()
  const format = useAiFormat()
  const request = useSearchKnowledge(session)
  const hits = request.data?.data.hits
  return <Panel title={'searchPassages'}>
    <KnowledgeQuestion pending={request.isPending} error={request.error} submit={(query, limit) => request.mutate({ query, limit })} />
    <AiFeedback error={request.error} retry={request.reset} write />
    <div aria-live="polite">
      {hits && (hits.length ? <ol className="v2-stack v2-ai-list">{hits.map(hit => <li key={hit.chunk_id} data-testid="search-hit"><Stack gap={1}>
        <strong>{data(t, hit.title)}</strong>
        <span>{t(key('passageScore'), { position: format.count(hit.position), score: format.bp(hit.score_bp) })}</span>
        <p className="v2-ai-reader">{data(t, hit.text)}</p>
      </Stack></li>)}</ol> : <p>{t(key('noPassages'))}</p>)}
    </div>
  </Panel>
}

function AskLibrary({ session }: { session: Session }) {
  const t = useT()
  const format = useAiFormat()
  const request = useAskKnowledge(session)
  const answer = request.data?.data
  return <Panel title={'askLibrary'}>
    <KnowledgeQuestion ask pending={request.isPending} error={request.error} submit={(question, limit) => request.mutate({ question, limit })} />
    <AiFeedback error={request.error} retry={request.reset} write />
    <div aria-live="polite">
      {answer && <Stack>
        <p>{t(key(answer.grounded ? 'grounded' : 'ungrounded'))}</p>
        <p data-testid="ask-answer" className="v2-ai-reader">{data(t, answer.answer)}</p>
        {answer.citations.length ? <ol className="v2-stack v2-ai-list">{answer.citations.map(citation => <li key={citation.chunk_id} data-testid="ask-citation">
          <Stack gap={1}><strong>{data(t, citation.title)}</strong>
            <span>{t(key('citationScore'), { score: format.bp(citation.score_bp) })}</span>
            <blockquote className="v2-ai-reader">{data(t, citation.quote)}</blockquote></Stack>
        </li>)}</ol> : <p>{t(key('noCitations'))}</p>}
      </Stack>}
    </div>
  </Panel>
}

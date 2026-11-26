import { useMemo, useState } from 'react'
import { useLanguage, useT } from '../../i18n'
import { ConflictBanner, ConfirmDestructive, Form, ReadOnlyNote } from '../../patterns'
import { Alert, Button, Card, Disclosure, EmptyState, Field, Grid, Input, Select, Skeleton, Stack, Table, useToast } from '../../ui'
import { entryEmailChecks, entryLimits } from '../../validators'
import { statusCode } from './api/status'
import { shareFieldErrors, useShareMutation, workspaceError } from './api/workspace'
import type { MemberRole, useWorkspaceRole } from './api/workspace'

const roles = ['viewer', 'editor', 'owner'] as const
const isRole = (value: string): value is MemberRole => roles.some(role => role === value)

export default function ShareProject({ id, name, userId, onIntegrations, role, members }: {
  id: string; name: string; userId: string; onIntegrations: () => void
} & ReturnType<typeof useWorkspaceRole>) {
  const t = useT()
  const { language } = useLanguage()
  const toast = useToast()
  const mutation = useShareMutation(id)
  const [email, setEmail] = useState('')
  const [newRole, setNewRole] = useState<MemberRole>('viewer')
  const status = statusCode(mutation.error)
  const error = workspaceError(mutation.error)
  const editable = role === 'owner' && status !== 403 && status !== 423
  const busy = mutation.isPending
  const disabled = busy || members.isFetching
  const roleOptions = roles.map(value => ({ value, label: t('share.role.' + value) }))
  const retry = () => { void members.refetch() }
  const reload = () => { mutation.reset(); retry() }
  const serverErrors = useMemo(() => shareFieldErrors(mutation.error), [mutation.error])
  const addErrors = mutation.variables?.kind === 'add' && Object.keys(serverErrors).length > 0
  const roleError = mutation.variables?.kind === 'role' ? serverErrors.role : undefined
  const staleMember = error === 'not_found' && mutation.variables?.kind !== 'add'
  const writeMessage = t(error === 'last_owner' ? 'share.lastOwner'
    : error === 'conflict' ? 'share.conflict'
    : staleMember ? 'share.staleMember'
    : error === 'impersonation_blocked' || error === 'impersonation_read_only' ? 'share.viewing'
    : error === 'forbidden' ? 'share.ownerRequired'
    : status === 423 ? 'shell.lockedBody'
    : error === 'org_mfa_required' ? 'shell.mfaBody'
    : status === 422 ? 'share.validationFailed'
    : status === 409 ? 'share.changeConflict'
    : status ? 'share.writeError' : 'share.transport')
  const date = new Intl.DateTimeFormat(language, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  const roster = members.data ?? []
  const columns = [
    { id: 'member', label: t('share.member') },
    { id: 'role', label: t('share.roleLabel') },
    { id: 'mcp', label: t('share.mcp') },
    ...(editable ? [{ id: 'actions', label: t('share.actions') }] : []),
  ]

  return <Stack className="v2-share-content">
    {status === 409
      ? <ConflictBanner onReload={reload}>{writeMessage}</ConflictBanner>
      : mutation.isError && !addErrors && !roleError && <Alert tone="danger"
        action={staleMember || !editable ? <Button onClick={reload}>{t('common.reload')}</Button> : undefined}>{writeMessage}</Alert>}
    {members.isPending ? <Skeleton lines={4} label={t('share.loading')} />
      : members.isError ? <Alert tone="danger" action={<Button onClick={retry}>{t('share.retry')}</Button>}>
        {t(statusCode(members.error) === 403 ? 'status.forbidden' : 'share.loadError')}
      </Alert>
      : !roster.length ? <EmptyState title={t('share.empty')} description={t('share.emptyHelp')}
        action={<Button onClick={retry}>{t('share.retry')}</Button>} />
      : <>
        <Table label={t('share.title')} columns={columns} rows={roster.map(member => {
          const mcp = t(member.mcp_enabled ? 'share.on' : 'share.off')
          const added = new Date(member.created_at)
          const memberName = t(member.user_id === userId ? 'share.you' : 'common.serverText', { text: member.name || member.email })
          const rowError = roleError && mutation.variables?.kind === 'role' && mutation.variables.user === member.user_id
            ? t(roleError.key, roleError.values) : undefined
          return { id: member.user_id, cells: [
            <Stack gap={1}>
              <strong>{memberName}</strong>
              <span className="v2-muted">{t('common.serverText', { text: member.email })}</span>
              {Number.isFinite(added.getTime()) && <time className="v2-muted v2-small" dateTime={member.created_at}>
                {t('share.addedDate', { date: date.format(added) })}
              </time>}
            </Stack>,
            editable ? <Field error={rowError}>{attrs => <Select value={member.role} options={roleOptions} disabled={disabled}
              triggerProps={{ ...attrs, 'aria-label': t('share.memberRole', { name: member.email }) }}
              onValueChange={value => {
                if (isRole(value)) mutation.mutate({ kind: 'role', user: member.user_id, role: value },
                  { onSuccess: () => toast({ title: t('share.roleSaved'), tone: 'success' }) })
              }} />}</Field> : t('share.role.' + member.role),
            mcp,
            ...(editable ? [<ConfirmDestructive
              trigger={<Button variant="danger" disabled={disabled} aria-label={t('share.removeMember', { name: member.email })}>{t('share.remove')}</Button>}
              title={t('share.removeTitle', { name: member.email })} description={t('share.removeConfirm')}
              action={t('share.remove')} closeLabel={t('share.cancel')} disabled={disabled}
              error={mutation.variables?.kind === 'remove' && mutation.variables.user === member.user_id && mutation.isError ? writeMessage : undefined}
              onConfirm={async () => {
                try {
                  await mutation.mutateAsync({ kind: 'remove', user: member.user_id })
                  toast({ title: t('share.removed'), tone: 'success' })
                } catch (cause) {
                  if (workspaceError(cause) !== 'not_found') throw cause
                }
              }} />] : []),
          ] }
        })} />
        {editable ? <>
          <Card><Form fields={[
            { name: 'email', label: t('share.email'), validate: entryEmailChecks,
              control: attrs => <Input {...attrs} type="email" maxLength={entryLimits.email}
                placeholder={t('share.emailPlaceholder')} value={email} onChange={event => setEmail(event.target.value)} /> },
            { name: 'role', label: t('share.roleLabel'), hint: t('share.roleHelp.' + newRole),
              control: ({ disabled, name: _name, ...attrs }) =>
                <Select triggerProps={attrs} disabled={disabled}
                  options={roleOptions} value={newRole} onValueChange={value => { if (isRole(value)) setNewRole(value) }} /> },
          ]} layout={fields => <Grid>{fields.email}{fields.role}</Grid>}
          serverErrors={addErrors ? serverErrors : undefined}
          submitLabel={t('share.add')} submitProps={{ disabled: !email.trim() || disabled }} preserveFocusOnSubmit pending={busy}
          onSubmit={() => mutation.mutate({ kind: 'add', email: email.trim(), role: newRole }, {
            onSuccess: () => { setEmail(''); toast({ title: t('share.added'), tone: 'success' }) },
          })} /></Card>
          <Stack gap={1}>
            <p className="v2-muted">{t('share.mcpHint')}</p>
            <Button onClick={onIntegrations}>{t('nav.integrations')}</Button>
          </Stack>
        </> : <ReadOnlyNote>{t('share.readOnly')}</ReadOnlyNote>}
        <Card><Disclosure label={t('share.diagram')}>
          <Stack gap={2}>
            <strong>{t('common.serverText', { text: name })}</strong>
            <ul className="v2-share-branches">{roster.map(member => <li key={member.user_id}>
              {t('share.diagramMember', { name: member.name || member.email, role: t('share.role.' + member.role),
                mcp: t(member.mcp_enabled ? 'share.on' : 'share.off') })}
            </li>)}</ul>
          </Stack>
        </Disclosure></Card>
      </>}
  </Stack>
}

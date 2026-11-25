import { useState } from 'react'
import type { RefObject } from 'react'
import { useT } from '../../i18n'
import { ConflictBanner, ConfirmDestructive, Form, ListRow, ReadOnlyNote } from '../../patterns'
import { Alert, Badge, Button, EmptyState, Field, Input, Row, Select, Sheet, Skeleton, Stack, Switch, useToast } from '../../ui'
import { entryLimits, validators } from '../../validators'
import { statusCode } from './api/status'
import { useShareMutation, workspaceError } from './api/workspace'
import type { MemberRole, useWorkspaceRole } from './api/workspace'

const roles = ['viewer', 'editor', 'owner'] as const
const isRole = (value: string): value is MemberRole => roles.some(role => role === value)

export function ShareProject({ id, open, onOpenChange, role, members, returnFocus }: {
  id: string; open: boolean; onOpenChange: (open: boolean) => void; returnFocus?: RefObject<HTMLElement | null>
} & ReturnType<typeof useWorkspaceRole>) {
  const t = useT()
  const toast = useToast()
  const mutation = useShareMutation(id)
  const [newRole, setNewRole] = useState<MemberRole>('viewer')
  const editable = role === 'owner' && statusCode(mutation.error) !== 403
  const roleOptions = roles.map(value => ({ value, label: t('share.role.' + value) }))
  const reload = () => { mutation.reset(); void members.refetch() }
  const error = workspaceError(mutation.error)
  const busy = mutation.isPending
  const unknownEmail = error === 'user_unavailable' && mutation.variables?.kind === 'add'

  return <Sheet title={t('share.title')} open={open} onOpenChange={onOpenChange} returnFocus={returnFocus}
    trigger={!returnFocus ? <Button>{t('share.open')}</Button> : undefined}>
    <Stack className="v2-share-content">
      {members.isPending ? <Skeleton lines={4} label={t('share.loading')} />
        : members.isError ? <Alert tone="danger" action={<Button onClick={reload}>{t('common.retry')}</Button>}>{t('share.loadError')}</Alert>
        : <>
          {!editable && <ReadOnlyNote>{t('share.readOnly')}</ReadOnlyNote>}
          {!members.data.length && <EmptyState title={t('share.empty')} action={<Button onClick={reload}>{t('common.reload')}</Button>} />}
          {members.data.map(member => <ListRow key={member.user_id}
            title={t('common.serverText', { text: member.name || member.email })}
            detail={t('common.serverText', { text: member.email })}
            actions={<Row>
              {editable ? <>
                <Field label={t('share.memberRole', { name: member.email })}>{attrs =>
                  <Select triggerProps={attrs} value={member.role} options={roleOptions} disabled={busy}
                    onValueChange={role => { if (isRole(role)) mutation.mutate({ kind: 'role', user: member.user_id, role },
                      { onSuccess: () => toast({ title: t('share.roleSaved'), tone: 'success' }) }) }} />
                }</Field>
                <Switch label={t('share.mcp', { name: member.email })} checked={member.mcp_enabled}
                  disabled={busy} onChange={event => mutation.mutate({ kind: 'mcp', user: member.user_id, enabled: event.target.checked },
                    { onSuccess: () => toast({ title: t('share.mcpSaved'), tone: 'success' }) })} />
                <ConfirmDestructive trigger={<Button variant="danger" disabled={busy} aria-label={t('share.removeMember', { name: member.email })}>{t('share.remove')}</Button>}
                  title={t('share.remove')} description={t('share.removeConfirm', { name: member.email })}
                  action={t('share.remove')} error={error === 'last_owner' && mutation.variables?.kind === 'remove'
                    && mutation.variables.user === member.user_id ? t('share.lastOwner') : undefined}
                  onConfirm={async () => {
                    await mutation.mutateAsync({ kind: 'remove', user: member.user_id })
                    toast({ title: t('share.removed'), tone: 'success' })
                  }} />
              </> : <Badge>{t('share.role.' + member.role)}</Badge>}
            </Row>} />)}
          {editable && <Stack gap={2}>
            <Form fields={[
              { name: 'email', label: t('share.email'), validate: [validators.required, validators.email, validators.length(entryLimits.email)],
                control: attrs => <Input {...attrs} type="email" maxLength={entryLimits.email} /> },
              { name: 'role', label: t('share.roleLabel'), control: attrs => <Select triggerProps={attrs}
                options={roleOptions} value={newRole} onValueChange={value => { if (isRole(value)) setNewRole(value) }} /> },
            ]} serverErrors={unknownEmail ? { email: { key: 'share.unknownEmail' } } : undefined} submitLabel={t('share.add')} pending={busy}
            onSubmit={values => mutation.mutate({ kind: 'add', email: String(values.get('email')).trim(), role: newRole },
              { onSuccess: () => toast({ title: t('share.added'), tone: 'success' }) })} />
          </Stack>}
        </>}
      {statusCode(mutation.error) === 409 ? <ConflictBanner onReload={reload}>
        {t(error === 'last_owner' ? 'share.lastOwner' : 'share.conflict')}
      </ConflictBanner> : mutation.isError && !unknownEmail && <Alert tone="danger">{t('share.writeError')}</Alert>}
    </Stack>
  </Sheet>
}

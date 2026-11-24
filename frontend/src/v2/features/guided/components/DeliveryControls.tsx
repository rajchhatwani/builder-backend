import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { SectionSearch } from '../../../projectNavigation'
import { useT } from '../../../i18n'
import { ConflictBanner, ConfirmDestructive, Form } from '../../../patterns'
import { Alert, Button, Dialog, Input } from '../../../ui'
import { validators } from '../../../validators'
import type { Approval } from '../api/delivery'
import { errorCode, errorStatus } from '../api/guided'
import { useGuidedError } from './GuidedFeedback'

export function ProjectLink({ projectId, section, search, children, primary }: {
  projectId: string; section: string; children: ReactNode; primary?: boolean; search?: SectionSearch
}) {
  return <Button asChild variant={primary ? 'primary' : 'default'}>
    <Link to="/projects/$projectId/$section" params={{ projectId, section }} search={search}>{children}</Link>
  </Button>
}

export function DeliveryError({ error, reload }: { error: unknown; reload: () => void }) {
  const t = useT()
  const describe = useGuidedError()
  if (!error) return null
  if (errorStatus(error) === 409) return <ConflictBanner onReload={reload}>{describe(error)}</ConflictBanner>
  if (errorStatus(error) === 403) {
    const code = errorCode(error)
    return <Alert tone="danger">{code === 'separation_of_duties' ? t('approval.separation') : t('guided.forbidden')}</Alert>
  }
  const code = errorCode(error)
  const message = code && ['gates_busy', 'preview_capacity', 'preview_org_capacity', 'preview_quota', 'workspace_not_ready', 'previews_disabled', 'previews_off', 'spec_invalid'].includes(code)
    ? t('delivery.errors.' + code) : describe(error)
  return <Alert tone="danger">{message}</Alert>
}

export function ConfirmAction({ label, title, description, pending, onConfirm, destructive = true, disabled, testId }: {
  label: string; title: string; description: string; pending: boolean; onConfirm: () => Promise<unknown>; destructive?: boolean; disabled?: boolean; testId?: string
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [failed, setFailed] = useState(false)
  const trigger = <Button disabled={pending || disabled} data-testid={testId}>{label}</Button>
  if (destructive) return <ConfirmDestructive trigger={trigger} title={title} description={description}
    action={label} onConfirm={async () => { await onConfirm() }} pending={pending} />
  return <Dialog open={open} onOpenChange={value => { setFailed(false); setOpen(value) }} trigger={trigger} title={title} description={description}
    actions={<Button variant="primary" disabled={pending} onClick={async () => {
      try { await onConfirm(); setOpen(false) } catch { setFailed(true) }
    }}>{t('approval.confirm')}</Button>}>
    {failed && <Alert tone="danger">{t('common.actionFailed')}</Alert>}
  </Dialog>
}

export function TextAction({ title, label, max, pending, onSubmit }: {
  title: string; label: string; max: number; pending: boolean; onSubmit: (text: string) => Promise<unknown>
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [failed, setFailed] = useState(false)
  return <Dialog title={title} open={open} onOpenChange={value => {
    setOpen(value); setFailed(false)
  }} trigger={<Button disabled={pending}>{title}</Button>}>
    <Form pending={pending} submitLabel={title} formError={failed ? t('common.actionFailed') : undefined}
      fields={[{ name: 'text', label, validate: [validators.required, validators.length(max)], control: attrs => <Input {...attrs} /> }]}
      onSubmit={async data => {
        try { await onSubmit(String(data.get('text')).trim()); setOpen(false) } catch { setFailed(true) }
      }} />
  </Dialog>
}

export function ApprovalLink({ projectId, approval }: { projectId: string; approval: Approval }) {
  return <ProjectLink projectId={projectId} section={approval.kind === 'A' ? 'plan' : 'approvals'}
    search={{ run: approval.run_id, approval: approval.id }}>{approval.subject}</ProjectLink>
}


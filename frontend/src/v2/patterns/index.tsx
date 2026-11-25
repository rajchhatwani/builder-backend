import { useState } from 'react'
import type { ReactElement, ReactNode, RefObject } from 'react'
import { useT } from '../i18n'
import { Alert, Badge, Button, Card, Dialog, Row, Spinner, Stack } from '../ui'
import type { Tone } from '../ui'
export * from './Form'
export * from './DataTable'

export function ConfirmDestructive({ trigger, title, description, action, onConfirm, pending, error, children, disabled, closeLabel, open: controlledOpen, onOpenChange, returnFocus }: {
  trigger?: ReactElement
  open?: boolean
  onOpenChange?: (open: boolean) => void
  returnFocus?: RefObject<HTMLElement | null>
  title: string
  description: string
  action: string
  closeLabel?: string
  onConfirm: () => void | Promise<void>
  pending?: boolean
  error?: string
  children?: ReactNode
  disabled?: boolean
}) {
  const [localOpen, setLocalOpen] = useState(false)
  const open = controlledOpen ?? localOpen
  const setOpen = onOpenChange ?? setLocalOpen
  const [working, setWorking] = useState(false)
  const [failed, setFailed] = useState(false)
  const t = useT()
  const busy = Boolean(pending || working)
  return (
    <Dialog title={title} description={description} trigger={trigger} open={open} onOpenChange={setOpen} returnFocus={returnFocus} closeLabel={closeLabel}
      actions={<Button variant="danger" disabled={busy || disabled} onClick={async () => {
        setWorking(true)
        setFailed(false)
        try {
          await onConfirm()
          setOpen(false)
        } catch {
          setFailed(true)
        } finally {
          setWorking(false)
        }
      }}>{busy && <Spinner />}{action}</Button>}>
      {children}
      {(error || failed) && <Alert tone="danger">{error ?? t('common.actionFailed')}</Alert>}
    </Dialog>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <header>
      <Stack gap={1}>
        <Row className="v2-spread"><h1>{title}</h1>{actions}</Row>
        {description && <p className="v2-muted">{description}</p>}
      </Stack>
    </header>
  )
}

export function SettingsSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card>
      <Stack gap={4}>
        <Stack gap={1}><h2>{title}</h2>{description && <p className="v2-muted">{description}</p>}</Stack>
        {children}
      </Stack>
    </Card>
  )
}

export function ConflictBanner({ onReload, action, children }: { onReload?: () => void; action?: ReactNode; children?: ReactNode }) {
  const t = useT()
  return <Alert tone="warning" action={action ?? (onReload && <Button onClick={onReload}>{t('common.reload')}</Button>)}>{children ?? t('common.conflict')}</Alert>
}

export function ReadOnlyNote({ children }: { children?: ReactNode }) {
  const t = useT()
  return <Alert>{children ?? t('common.readOnly')}</Alert>
}

export function RoleGate({ allowed, children, fallback = <ReadOnlyNote /> }: { allowed: boolean; children: ReactNode; fallback?: ReactNode }) {
  return allowed ? children : fallback
}

export function ListRow({ title, detail, actions }: { title: ReactNode; detail?: ReactNode; actions?: ReactNode }) {
  return <Row className="v2-spread"><Stack gap={1}><strong>{title}</strong>{detail && <span className="v2-muted">{detail}</span>}</Stack>{actions}</Row>
}

export function StatusPill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <Badge tone={tone}>{children}</Badge>
}

export function SaveBar({ dirty, pending, saved, readOnly, onSave, onDiscard }: {
  dirty: boolean; pending?: boolean; saved?: boolean; readOnly?: boolean; onSave: () => void; onDiscard: () => void
}) {
  const t = useT()
  return (
    <Row className="v2-save-bar v2-spread">
      <span role="status">{pending ? t('common.saving') : dirty ? t('common.unsaved') : saved ? t('common.saved') : ''}</span>
      <Row>
        <Button disabled={!dirty || pending} onClick={onDiscard}>{t('common.discard')}</Button>
        <Button variant="primary" disabled={!dirty || pending || readOnly} onClick={onSave}>{t('common.save')}</Button>
      </Row>
    </Row>
  )
}

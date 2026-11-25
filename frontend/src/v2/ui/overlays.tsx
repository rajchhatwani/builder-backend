import * as DialogBase from '@radix-ui/react-dialog'
import * as MenuBase from '@radix-ui/react-dropdown-menu'
import * as PopoverBase from '@radix-ui/react-popover'
import * as TooltipBase from '@radix-ui/react-tooltip'
import type { ReactElement, ReactNode, RefObject } from 'react'
import { useLanguage, useT } from '../i18n'
import { Button } from './controls'
import { Row, Stack } from './layout'

type DialogProps = {
  title: string
  description?: string
  trigger?: ReactElement
  children: ReactNode
  actions?: ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  sheet?: boolean
  closeLabel?: string
  returnFocus?: RefObject<HTMLElement | null>
}

export function Dialog({ title, description, trigger, children, actions, open, onOpenChange, sheet, closeLabel, returnFocus }: DialogProps) {
  const t = useT()
  return (
    <DialogBase.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <DialogBase.Trigger asChild>{trigger}</DialogBase.Trigger>}
      <DialogBase.Portal>
        <DialogBase.Overlay className="v2-overlay" />
        <DialogBase.Content className="v2-dialog" data-sheet={sheet || undefined} onCloseAutoFocus={returnFocus && (event => {
          event.preventDefault()
          returnFocus.current?.focus()
        })}>
          <Stack gap={4}>
            <Stack gap={1}>
              <DialogBase.Title>{title}</DialogBase.Title>
              <DialogBase.Description className={description ? 'v2-muted' : 'v2-visually-hidden'}>{description ?? title}</DialogBase.Description>
            </Stack>
            {children}
            <Row className="v2-dialog-actions">
              {actions}
              <DialogBase.Close asChild><Button>{closeLabel ?? t('common.close')}</Button></DialogBase.Close>
            </Row>
          </Stack>
        </DialogBase.Content>
      </DialogBase.Portal>
    </DialogBase.Root>
  )
}

export function Sheet(props: DialogProps) { return <Dialog {...props} sheet /> }

type MenuItem = { id: string; label: string; onSelect: () => void; disabled?: boolean }

export function Menu({ trigger, items, label }: { trigger: ReactElement; items: MenuItem[]; label?: string }) {
  const { dir } = useLanguage()
  return (
    <MenuBase.Root dir={dir}>
      <MenuBase.Trigger asChild>{trigger}</MenuBase.Trigger>
      <MenuBase.Portal>
        <MenuBase.Content className="v2-popup" align="end">
          {label && <MenuBase.Label className="v2-menu-label">{label}</MenuBase.Label>}
          {items.map(({ id, label, onSelect, disabled }) => (
            <MenuBase.Item key={id} className="v2-option" onSelect={onSelect} disabled={disabled}>{label}</MenuBase.Item>
          ))}
        </MenuBase.Content>
      </MenuBase.Portal>
    </MenuBase.Root>
  )
}

export const Dropdown = Menu

export function Popover({ trigger, children, label }: { trigger: ReactElement; children: ReactNode; label: string }) {
  return (
    <PopoverBase.Root>
      <PopoverBase.Trigger asChild>{trigger}</PopoverBase.Trigger>
      <PopoverBase.Portal>
        <PopoverBase.Content className="v2-popup v2-popover" align="start" aria-label={label}>{children}</PopoverBase.Content>
      </PopoverBase.Portal>
    </PopoverBase.Root>
  )
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <TooltipBase.Provider>{children}</TooltipBase.Provider>
}

export function Tooltip({ trigger, children }: { trigger: ReactElement; children: ReactNode }) {
  return (
    <TooltipBase.Root>
      <TooltipBase.Trigger asChild>{trigger}</TooltipBase.Trigger>
      <TooltipBase.Portal>
        <TooltipBase.Content className="v2-popup v2-tooltip">{children}</TooltipBase.Content>
      </TooltipBase.Portal>
    </TooltipBase.Root>
  )
}

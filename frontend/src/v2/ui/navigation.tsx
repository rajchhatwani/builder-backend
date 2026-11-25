import * as TabsBase from '@radix-ui/react-tabs'
import type { ReactNode } from 'react'
import { Button } from './controls'
import { Row } from './layout'
import { useLanguage, useT } from '../i18n'

export function Tabs({ label, value, onChange, items, keepMounted }: {
  label: string; value: string; onChange: (value: string) => void; keepMounted?: boolean
  items: { id: string; label: string; content: ReactNode; disabled?: boolean }[]
}) {
  const { dir } = useLanguage()
  return (
    <TabsBase.Root dir={dir} value={value} onValueChange={onChange}>
      <TabsBase.List className="v2-tabs" aria-label={label}>
        {items.map(item => <TabsBase.Trigger key={item.id} value={item.id} disabled={item.disabled} className="v2-tab">{item.label}</TabsBase.Trigger>)}
      </TabsBase.List>
      {items.map(item => <TabsBase.Content key={item.id} className="v2-tab-panel" value={item.id}
        forceMount={keepMounted ? true : undefined} {...(keepMounted ? { hidden: item.id !== value } : {})}>{item.content}</TabsBase.Content>)}
    </TabsBase.Root>
  )
}

export function Breadcrumb({ items, label }: { items: { id: string; content: ReactNode }[]; label?: string }) {
  const t = useT()
  return (
    <nav aria-label={label ?? t('common.breadcrumb')}>
      <ol className="v2-breadcrumb">
        {items.map((item, index) => (
          <li key={item.id} aria-current={index === items.length - 1 ? 'page' : undefined}>
            {index > 0 && <span aria-hidden>/</span>}{item.content}
          </li>
        ))}
      </ol>
    </nav>
  )
}

export function Pagination({ label, page, pages, onChange }: {
  label: string; page: number; pages: number; onChange: (page: number) => void
}) {
  const t = useT()
  return (
    <nav aria-label={t('common.pagination', { label })}>
      <Row>
        <Button disabled={page <= 1} onClick={() => onChange(page - 1)}>{t('common.previous')}</Button>
        <span aria-live="polite">{t('common.page', { page, pages: Math.max(1, pages) })}</span>
        <Button disabled={page >= pages} onClick={() => onChange(page + 1)}>{t('common.next')}</Button>
      </Row>
    </nav>
  )
}

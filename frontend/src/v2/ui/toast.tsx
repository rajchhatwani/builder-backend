import * as Base from '@radix-ui/react-toast'
import { createContext, useContext, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useT } from '../i18n'
import { Button } from './controls'
import { Row } from './layout'

type Message = { title: string; tone?: 'success' | 'danger' }
const ToastContext = createContext<(message: Message) => void>(() => {})

export function Toast({ message, onClose }: { message: Message; onClose: () => void }) {
  const t = useT()
  return (
    <Base.Root className="v2-toast" data-tone={message.tone} onOpenChange={open => { if (!open) onClose() }}>
      <Row>
        <Base.Title>{message.title}</Base.Title>
        <Base.Close asChild><Button variant="ghost">{t('common.close')}</Button></Base.Close>
      </Row>
    </Base.Root>
  )
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const t = useT()
  const nextId = useRef(0)
  const [messages, setMessages] = useState<(Message & { id: number })[]>([])
  return (
    <Base.Provider label={t('common.notification')}>
      <ToastContext.Provider value={message => {
        const id = ++nextId.current
        setMessages(current => [...current, { ...message, id }])
      }}>
        {children}
        {messages.map(message => <Toast key={message.id} message={message} onClose={() => setMessages(current => current.filter(item => item.id !== message.id))} />)}
        <Base.Viewport className="v2-toast-viewport" label={t('common.notifications')} />
      </ToastContext.Provider>
    </Base.Provider>
  )
}

export function useToast() { return useContext(ToastContext) }

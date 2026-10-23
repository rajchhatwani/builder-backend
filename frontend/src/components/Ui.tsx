import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { Modal } from './Modal'

interface ConfirmOptions {
  title: string
  message?: string
  confirmLabel?: string
  /** Styles the confirm button as destructive. */
  danger?: boolean
}

type ToastKind = 'success' | 'danger'

interface UiApi {
  confirm: (options: ConfirmOptions) => Promise<boolean>
  toast: (text: string, kind?: ToastKind) => void
}

const UiContext = createContext<UiApi | null>(null)

export function useUi(): UiApi {
  const ctx = useContext(UiContext)
  if (!ctx) throw new Error('useUi must be used inside <UiProvider>')
  return ctx
}

interface ToastItem {
  id: number
  text: string
  kind: ToastKind
}

/** Provides in-app confirmation dialogs and toast messages (instead of window.confirm). */
export function UiProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<ConfirmOptions | null>(null)
  const resolver = useRef<((ok: boolean) => void) | null>(null)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(0)

  const confirm = useCallback((options: ConfirmOptions) => {
    setPending(options)
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve
    })
  }, [])

  function settle(ok: boolean) {
    resolver.current?.(ok)
    resolver.current = null
    setPending(null)
  }

  const toast = useCallback((text: string, kind: ToastKind = 'success') => {
    const id = nextId.current++
    setToasts((list) => [...list, { id, text, kind }])
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 4000)
  }, [])

  return (
    <UiContext.Provider value={{ confirm, toast }}>
      {children}

      <Modal open={pending !== null} onClose={() => settle(false)}>
        <form
          method="dialog"
          onSubmit={(e) => {
            e.preventDefault()
            settle(true)
          }}
        >
          <header>
            <h3>{pending?.title}</h3>
            {pending?.message && <p>{pending.message}</p>}
          </header>
          <footer>
            <button type="button" className="outline" onClick={() => settle(false)}>
              Cancel
            </button>
            <button type="submit" data-variant={pending?.danger ? 'danger' : undefined}>
              {pending?.confirmLabel ?? 'Confirm'}
            </button>
          </footer>
        </form>
      </Modal>

      <div className="toast-stack" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role="alert" data-variant={t.kind}>
            {t.text}
          </div>
        ))}
      </div>
    </UiContext.Provider>
  )
}

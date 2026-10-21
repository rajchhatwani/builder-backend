import { useEffect, useRef, type ReactNode } from 'react'

interface ModalProps {
  open: boolean
  onClose: () => void
  children: ReactNode
}

/**
 * Thin wrapper around a native <dialog>. Oat styles `dialog > form > header`,
 * `> div`, and `> footer` directly, so children should provide that structure
 * themselves rather than this component imposing its own.
 */
export function Modal({ open, onClose, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return <dialog ref={ref} onClose={onClose}>{children}</dialog>
}

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'

export type ToastLevel = 'info' | 'success' | 'warning' | 'error'
interface Toast { id: number; level: ToastLevel; message: string }
interface ToastContextValue { notify: (message: string, level?: ToastLevel) => void; toasts: Toast[]; dismiss: (id: number) => void }

const ToastContext = createContext<ToastContextValue | null>(null)

const icons: Record<ToastLevel, typeof Info> = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle }
const styles: Record<ToastLevel, string> = {
  info: 'border-brand-500/40 text-ink',
  success: 'border-emerald-500/40 text-ink',
  warning: 'border-amber-500/50 text-ink',
  error: 'border-red-500/50 text-ink',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => setToasts((current) => current.filter((toast) => toast.id !== id)), [])
  const notify = useCallback(
    (message: string, level: ToastLevel = 'info') => {
      const id = Date.now() + Math.random()
      setToasts((current) => [...current, { id, level, message }])
      window.setTimeout(() => dismiss(id), 6000)
    },
    [dismiss],
  )

  const value = useMemo(() => ({ notify, toasts, dismiss }), [notify, toasts, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-96 flex-col gap-2">
        {toasts.map((toast) => {
          const Icon = icons[toast.level]
          return (
            <div key={toast.id} role="status" className={`pointer-events-auto flex animate-fade-in items-start gap-3 rounded-xl border bg-surface-elevated p-3 shadow-lg ${styles[toast.level]}`}>
              <Icon className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="flex-1 text-sm">{toast.message}</p>
              <button aria-label="Fermer la notification" className="text-ink-faint hover:text-ink" onClick={() => dismiss(toast.id)}>
                <X className="h-4 w-4" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToasts(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToasts doit être utilisé dans ToastProvider')
  return context
}

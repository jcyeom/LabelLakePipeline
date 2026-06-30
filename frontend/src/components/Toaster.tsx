import { useUiStore } from '@/stores/uiStore'

const kindStyles: Record<string, string> = {
  success: 'bg-green-600',
  error: 'bg-red-600',
  info: 'bg-gray-800',
}

export function Toaster() {
  const toasts = useUiStore((s) => s.toasts)
  const dismiss = useUiStore((s) => s.dismissToast)
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          onClick={() => dismiss(t.id)}
          className={`cursor-pointer rounded px-4 py-2 text-sm text-white shadow-lg ${kindStyles[t.kind]}`}
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}

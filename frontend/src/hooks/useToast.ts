import { useUiStore } from '@/stores/uiStore'

export function useToast() {
  const pushToast = useUiStore((s) => s.pushToast)
  return {
    success: (msg: string) => pushToast('success', msg),
    error: (msg: string) => pushToast('error', msg),
    info: (msg: string) => pushToast('info', msg),
  }
}

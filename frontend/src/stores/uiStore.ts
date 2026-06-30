import { create } from 'zustand'

export type ToastKind = 'success' | 'error' | 'info'
export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

interface UiState {
  toasts: Toast[]
  sidebarOpen: boolean
  pushToast: (kind: ToastKind, message: string) => void
  dismissToast: (id: number) => void
  toggleSidebar: () => void
}

let nextId = 1

export const useUiStore = create<UiState>((set) => ({
  toasts: [],
  sidebarOpen: true,
  pushToast: (kind, message) => {
    const id = nextId++
    set((s) => ({ toasts: [...s.toasts, { id, kind, message }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4000)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
}))

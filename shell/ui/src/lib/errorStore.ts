import { create } from "zustand"

export interface ActionError {
  id: number
  message: string
}

interface ErrorState {
  errors: ActionError[]
  push: (message: string) => void
  dismiss: (id: number) => void
}

let nextId = 1

/** Failed actions (move, rename, delete, ...) waiting to be shown as toasts.
 * Fed by the query client's mutation cache, so every action reports its
 * error without each component having to render one itself. */
export const useErrorStore = create<ErrorState>((set) => ({
  errors: [],
  push: (message) =>
    set((state) => ({
      // The last few are enough; a burst of identical failures shows once.
      errors: state.errors.some((e) => e.message === message)
        ? state.errors
        : [...state.errors.slice(-2), { id: nextId++, message }],
    })),
  dismiss: (id) => set((state) => ({ errors: state.errors.filter((e) => e.id !== id) })),
}))

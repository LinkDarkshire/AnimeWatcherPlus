import "@tanstack/react-query"

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      /** The form shows this action's error itself -- no extra toast. */
      showsOwnError?: boolean
    }
  }
}

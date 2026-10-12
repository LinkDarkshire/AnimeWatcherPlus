import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import "./index.css"
import App from "./App.tsx"
import { I18nProvider } from "./i18n/I18nContext"
import { UpdateGate } from "./components/UpdateGate"
import { useErrorStore } from "./lib/errorStore"

const queryClient = new QueryClient({
  // Every failed action shows up as a toast, unless its form already shows
  // the error itself (meta.showsOwnError).
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (!mutation.meta?.showsOwnError) useErrorStore.getState().push(error.message)
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <UpdateGate>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </UpdateGate>
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
)

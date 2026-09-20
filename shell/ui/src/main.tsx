import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import "./index.css"
import App from "./App.tsx"
import { I18nProvider } from "./i18n/I18nContext"
import { UpdateGate } from "./components/UpdateGate"

const queryClient = new QueryClient({
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

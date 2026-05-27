import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoginPage } from '@/pages/LoginPage'
import { BusquedaPage } from '@/pages/BusquedaPage'
import { LotePage } from '@/pages/LotePage'
import { HistorialPage } from '@/pages/HistorialPage'
import { PanelPage } from '@/pages/PanelPage'
import { UsuariosPage } from '@/pages/UsuariosPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/app">
        <Routes>
          {/* Público */}
          <Route path="/login" element={<LoginPage />} />

          {/* Privado — con sidebar */}
          <Route element={<AppLayout />}>
            <Route index element={<Navigate to="/busqueda" replace />} />
            <Route path="/busqueda"  element={<BusquedaPage />} />
            <Route path="/lote"      element={<LotePage />} />
            <Route path="/historial" element={<HistorialPage />} />
            <Route path="/panel"     element={<PanelPage />} />
            <Route path="/usuarios"  element={<UsuariosPage />} />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/busqueda" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

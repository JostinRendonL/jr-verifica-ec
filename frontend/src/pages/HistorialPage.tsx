import { useState, useCallback } from 'react'
import { Search, Filter, FileText, Pencil, Check, X, RefreshCw } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { SemaforoBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { NivelSemaforo } from '@/types'

interface EntradaHistorial {
  id: string
  cedula: string
  nombre?: string
  semaforo: NivelSemaforo
  timestamp: number
  operador_nombre?: string
  tipo: string
  edad_seg: number
}

const SEMAFOROS: { label: string; value: string }[] = [
  { label: 'Todos', value: '' },
  { label: '✅ APTO',        value: 'APTO' },
  { label: '🟡 OBSERVACIÓN', value: 'OBSERVACIÓN' },
  { label: '🔴 RECHAZAR',    value: 'RECHAZAR' },
  { label: '🚨 CRÍTICO',     value: 'CRÍTICO' },
  { label: '⚪ SIN DATOS',   value: 'SIN DATOS' },
]

function formatTs(ts: number) {
  return new Date(ts * 1000).toLocaleString('es-EC', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function HistorialPage() {
  const queryClient = useQueryClient()
  const [filtroCedula, setFiltroCedula] = useState('')
  const [filtroSemaforo, setFiltroSemaforo] = useState('')
  const [editando, setEditando] = useState<{ id: string; valor: string } | null>(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['historial', filtroCedula, filtroSemaforo],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filtroCedula) params.set('cedula', filtroCedula)
      if (filtroSemaforo) params.set('semaforo', filtroSemaforo)
      params.set('limite', '200')
      const res = await api.get(`/api/historial?${params}`)
      return res.data as { entradas: EntradaHistorial[]; total: number }
    },
  })

  const editarNombre = useMutation({
    mutationFn: async ({ cedula, nombre }: { cedula: string; nombre: string }) => {
      const form = new FormData()
      form.append('nombre', nombre)
      await api.post(`/historial/cedula/${cedula}/nombre`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['historial'] })
      setEditando(null)
    },
  })

  const descargarPDF = useCallback((entradaId: string) => {
    window.open(`/historial/${entradaId}/pdf`, '_blank')
  }, [])

  const entradas = data?.entradas ?? []
  const total = data?.total ?? 0

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Historial de Verificaciones</h1>
          <p className="text-sm text-gray-500 mt-1">
            Registro completo de consultas · <span className="font-medium text-gray-700">{total.toLocaleString()}</span> registros totales
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => refetch()}>
          <RefreshCw className="w-3.5 h-3.5" />
          Actualizar
        </Button>
      </div>

      {/* Filtros */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={filtroCedula}
            onChange={e => setFiltroCedula(e.target.value)}
            placeholder="Ej. 0912345678"
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-700 focus:border-transparent"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-gray-400" />
          <select
            value={filtroSemaforo}
            onChange={e => setFiltroSemaforo(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-700 bg-white"
          >
            {SEMAFOROS.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
        {(filtroCedula || filtroSemaforo) && (
          <button
            onClick={() => { setFiltroCedula(''); setFiltroSemaforo('') }}
            className="text-xs text-gray-500 hover:text-gray-700 underline"
          >
            Limpiar filtros
          </button>
        )}
        <p className="text-sm text-gray-500 ml-auto">
          Mostrando {entradas.length.toLocaleString()} de {total.toLocaleString()} registros
        </p>
      </div>

      {/* Tabla */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400 gap-3">
            <RefreshCw className="w-5 h-5 animate-spin" />
            <span className="text-sm">Cargando historial...</span>
          </div>
        ) : entradas.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-400 gap-2">
            <FileText className="w-10 h-10" />
            <p className="text-sm">No se encontraron registros</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Cédula</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Nombre</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Semáforo</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Fecha/Hora</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Operador</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {entradas.map(e => (
                  <tr key={e.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">{e.cedula}</td>
                    <td className="px-4 py-3">
                      {editando?.id === e.id ? (
                        <div className="flex items-center gap-1.5">
                          <input
                            autoFocus
                            type="text"
                            value={editando.valor}
                            onChange={ev => setEditando({ id: e.id, valor: ev.target.value })}
                            onKeyDown={ev => {
                              if (ev.key === 'Enter') editarNombre.mutate({ cedula: e.cedula, nombre: editando.valor })
                              if (ev.key === 'Escape') setEditando(null)
                            }}
                            className="text-sm border border-navy-300 rounded px-2 py-1 w-44 focus:outline-none focus:ring-1 focus:ring-navy-700"
                          />
                          <button onClick={() => editarNombre.mutate({ cedula: e.cedula, nombre: editando.valor })}
                            className="text-green-600 hover:text-green-700">
                            <Check className="w-4 h-4" />
                          </button>
                          <button onClick={() => setEditando(null)} className="text-gray-400 hover:text-gray-600">
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 group">
                          <span className={cn('text-sm', e.nombre ? 'text-gray-800' : 'text-gray-400 italic')}>
                            {e.nombre || 'Sin nombre'}
                          </span>
                          <button
                            onClick={() => setEditando({ id: e.id, valor: e.nombre || '' })}
                            className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-gray-600 transition-opacity"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {e.semaforo
                        ? <SemaforoBadge nivel={e.semaforo} size="sm" />
                        : <span className="text-gray-400 text-xs">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">{formatTs(e.timestamp)}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">{e.operador_nombre || '—'}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => descargarPDF(e.id)}
                          title="Descargar PDF"
                          className="p-1.5 text-gray-400 hover:text-navy-700 hover:bg-navy-50 rounded-md transition-colors"
                        >
                          <FileText className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

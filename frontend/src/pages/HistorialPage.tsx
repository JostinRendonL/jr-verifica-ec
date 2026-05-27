import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search, Filter, FileText, Pencil, Check, X, RefreshCw,
  Trash2, UserX, Eye, Plus, Download,
} from 'lucide-react'
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

const SEMAFOROS = [
  { label: 'Todos', value: '' },
  { label: '✅ APTO',        value: 'APTO' },
  { label: '🟡 OBSERVACIÓN', value: 'OBSERVACIÓN' },
  { label: '🔴 RECHAZAR',    value: 'RECHAZAR' },
  { label: '🚨 CRÍTICO',     value: 'CRÍTICO' },
  { label: '⚪ SIN DATOS',   value: 'SIN DATOS' },
]

function formatEdad(seg: number) {
  if (seg < 60)    return <span className="text-emerald-600 font-medium flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse inline-block" />hace {seg}s</span>
  if (seg < 3600)  return <span className="text-gray-700">hace {Math.floor(seg / 60)} min</span>
  if (seg < 86400) return <span className="text-gray-600">hace {Math.floor(seg / 3600)}h</span>
  return <span className="text-gray-400">hace {Math.floor(seg / 86400)}d</span>
}

export function HistorialPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [filtroCedula, setFiltroCedula]   = useState('')
  const [filtroSemaforo, setFiltroSemaforo] = useState('')
  const [editando, setEditando]           = useState<{ id: string; cedula: string; valor: string } | null>(null)

  // Modal derecho al olvido
  const [modalOlvido, setModalOlvido]     = useState(false)
  const [olvidoCedula, setOlvidoCedula]   = useState('')
  const [olvidoMotivo, setOlvidoMotivo]   = useState('Solicitud del titular')
  const [olvidoMsg, setOlvidoMsg]         = useState('')

  // Toast de éxito
  const [toast, setToast] = useState('')
  function mostrarToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(''), 3500)
  }

  // ── Query ──────────────────────────────────────────────────────────────────
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['historial', filtroCedula, filtroSemaforo],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filtroCedula)   params.set('cedula', filtroCedula)
      if (filtroSemaforo) params.set('semaforo', filtroSemaforo)
      params.set('limite', '200')
      const res = await api.get(`/api/historial?${params}`)
      return res.data as { entradas: EntradaHistorial[]; total: number }
    },
  })

  // ── Mutations ──────────────────────────────────────────────────────────────
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

  const eliminarEntrada = useMutation({
    mutationFn: async (id: string) => {
      await api.post(`/historial/${id}/borrar`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['historial'] })
      mostrarToast('Entrada eliminada del historial.')
    },
  })

  const limpiarCache = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/historial/limpiar')
      return res.data as { ok: boolean; n: number }
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['historial'] })
      mostrarToast(`Caché limpiado. Se eliminaron ${data.n} entradas.`)
    },
  })

  const derechoAlOlvido = useMutation({
    mutationFn: async ({ cedula, motivo }: { cedula: string; motivo: string }) => {
      const form = new FormData()
      form.append('cedula', cedula)
      form.append('motivo', motivo)
      const res = await api.post('/api/derecho-al-olvido', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data as { ok: boolean; n_hist: number; n_ver: number }
    },
    onSuccess: (data, vars) => {
      queryClient.invalidateQueries({ queryKey: ['historial'] })
      setModalOlvido(false)
      mostrarToast(
        `Derecho al olvido ejecutado para ${vars.cedula}: ${data.n_hist} entrada(s) y ${data.n_ver} código(s) de PDF eliminados.`
      )
      setOlvidoCedula('')
      setOlvidoMotivo('Solicitud del titular')
      setOlvidoMsg('')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error
      setOlvidoMsg(msg ?? 'Error al ejecutar el borrado')
    },
  })

  const descargarPDF = useCallback((id: string) => {
    window.open(`/historial/${id}/pdf`, '_blank')
  }, [])

  const verResultado = useCallback((id: string) => {
    window.open(`/historial/${id}`, '_blank')
  }, [])

  const abrirOlvido = (cedula = '') => {
    setOlvidoCedula(cedula)
    setOlvidoMsg('')
    setModalOlvido(true)
  }

  function handleLimpiar() {
    if (!confirm('¿Borrar TODO el caché y el historial? Esta acción es irreversible. Las próximas consultas re-consultarán desde las fuentes oficiales.')) return
    limpiarCache.mutate()
  }

  function handleEliminar(e: EntradaHistorial) {
    if (!confirm(`¿Borrar la entrada de ${e.cedula}${e.nombre ? ' (' + e.nombre + ')' : ''}? La próxima consulta de esta cédula será nueva.`)) return
    eliminarEntrada.mutate(e.id)
  }

  function handleOlvido(e: React.FormEvent) {
    e.preventDefault()
    if (!/^\d{10}$/.test(olvidoCedula)) { setOlvidoMsg('La cédula debe tener exactamente 10 dígitos.'); return }
    if (!confirm(
      `⚠️ DERECHO AL OLVIDO\n\nVas a borrar TODO rastro de la cédula ${olvidoCedula}:\n• Todas las consultas del historial\n• Todos los códigos de PDFs emitidos\n\nEsta acción es IRREVERSIBLE. ¿Continuar?`
    )) return
    derechoAlOlvido.mutate({ cedula: olvidoCedula, motivo: olvidoMotivo })
  }

  const entradas = data?.entradas ?? []
  const total    = data?.total ?? 0

  return (
    <div className="p-8">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-emerald-600 text-white text-sm font-medium px-4 py-3 rounded-xl shadow-lg flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <Check className="w-4 h-4 flex-shrink-0" />
          {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Historial de Verificaciones</h1>
          <p className="text-sm text-gray-500 mt-1">
            Registro completo de consultas · <span className="font-medium text-gray-700">{total.toLocaleString()}</span> registros totales
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => abrirOlvido()}
            className="flex items-center gap-1.5 text-sm font-medium text-amber-700 border border-amber-200 hover:bg-amber-50 px-3 py-1.5 rounded-lg transition-colors"
          >
            <UserX className="w-4 h-4" />
            Derecho al olvido
          </button>
          {entradas.length > 0 && (
            <button
              onClick={handleLimpiar}
              disabled={limpiarCache.isPending}
              className="flex items-center gap-1.5 text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
            >
              <Trash2 className="w-4 h-4" />
              Limpiar caché
            </button>
          )}
          <Button size="sm" onClick={() => navigate('/busqueda')}>
            <Plus className="w-3.5 h-3.5" />
            Nueva búsqueda
          </Button>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            <RefreshCw className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {/* Filtros */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={filtroCedula}
            onChange={e => setFiltroCedula(e.target.value)}
            placeholder="Buscar por cédula..."
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-700 focus:border-transparent font-mono"
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
          Mostrando {entradas.length.toLocaleString()} de {total.toLocaleString()}
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
          <div className="flex flex-col items-center justify-center py-16 text-gray-400 gap-3">
            <FileText className="w-10 h-10" />
            <p className="text-sm">No se encontraron registros</p>
            <Button size="sm" onClick={() => navigate('/busqueda')}>
              <Plus className="w-3.5 h-3.5" />
              Hacer primera búsqueda
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Fecha</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Cédula</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Nombre</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Nivel</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Operador</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {entradas.map(e => (
                  <tr key={e.id} className="hover:bg-gray-50 transition-colors group">
                    <td className="px-4 py-3 text-xs whitespace-nowrap">{formatEdad(e.edad_seg)}</td>
                    <td className="px-4 py-3 font-mono text-xs font-bold text-gray-900 whitespace-nowrap">{e.cedula}</td>
                    <td className="px-4 py-3">
                      {editando?.id === e.id ? (
                        <div className="flex items-center gap-1.5">
                          <input
                            autoFocus
                            type="text"
                            value={editando.valor}
                            onChange={ev => setEditando({ ...editando, valor: ev.target.value })}
                            onKeyDown={ev => {
                              if (ev.key === 'Enter')  editarNombre.mutate({ cedula: e.cedula, nombre: editando.valor })
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
                        <div className="flex items-center gap-1.5 group/nombre">
                          <span className={cn('text-sm', e.nombre ? 'text-gray-800' : 'text-gray-400 italic')}>
                            {e.nombre || '—'}
                          </span>
                          <button
                            onClick={() => setEditando({ id: e.id, cedula: e.cedula, valor: e.nombre || '' })}
                            className="opacity-0 group-hover/nombre:opacity-100 text-gray-400 hover:text-gray-600 transition-opacity"
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
                    <td className="px-4 py-3 text-xs text-gray-500">{e.operador_nombre || '—'}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-0.5 opacity-60 group-hover:opacity-100 transition-opacity">
                        {/* Ver resultado */}
                        <button
                          onClick={() => verResultado(e.id)}
                          title="Ver resultado completo"
                          className="p-1.5 text-gray-500 hover:text-navy-700 hover:bg-navy-50 rounded-md transition-colors flex items-center gap-1 text-xs font-semibold"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          Ver
                        </button>
                        <span className="text-gray-200 mx-0.5">·</span>
                        {/* PDF */}
                        <button
                          onClick={() => descargarPDF(e.id)}
                          title="Descargar PDF"
                          className="p-1.5 text-gray-500 hover:text-navy-700 hover:bg-navy-50 rounded-md transition-colors flex items-center gap-1 text-xs font-semibold"
                        >
                          <Download className="w-3.5 h-3.5" />
                          PDF
                        </button>
                        <span className="text-gray-200 mx-0.5">·</span>
                        {/* Eliminar entrada */}
                        <button
                          onClick={() => handleEliminar(e)}
                          title="Eliminar esta entrada del caché"
                          disabled={eliminarEntrada.isPending}
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        <span className="text-gray-200 mx-0.5">·</span>
                        {/* Derecho al olvido */}
                        <button
                          onClick={() => abrirOlvido(e.cedula)}
                          title="Derecho al olvido — borrar TODO rastro (LOPDP)"
                          className="p-1.5 text-gray-400 hover:text-amber-600 hover:bg-amber-50 rounded-md transition-colors"
                        >
                          <UserX className="w-3.5 h-3.5" />
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

      {/* Modal Derecho al Olvido */}
      {modalOlvido && (
        <div
          className="fixed inset-0 bg-slate-950/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={e => { if (e.target === e.currentTarget) setModalOlvido(false) }}
        >
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-7">
            <div className="flex items-start gap-4 mb-5">
              <div className="w-12 h-12 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center flex-shrink-0">
                <UserX className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-gray-900">Derecho al olvido</h3>
                <p className="text-sm text-gray-500 mt-1">
                  LOPDP Art. 14 — Esta acción borra <strong>todo rastro</strong> de la persona:
                  historial de consultas + códigos de verificación de PDFs emitidos.{' '}
                  <span className="text-red-600 font-semibold">Es irreversible.</span>
                </p>
              </div>
            </div>

            <form onSubmit={handleOlvido} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wider">
                  Cédula del titular
                </label>
                <input
                  type="text"
                  value={olvidoCedula}
                  onChange={e => setOlvidoCedula(e.target.value.replace(/\D/g, '').slice(0, 10))}
                  placeholder="0000000000"
                  maxLength={10}
                  required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm font-mono tracking-wide focus:outline-none focus:ring-2 focus:ring-amber-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wider">
                  Motivo (evidencia legal)
                </label>
                <input
                  type="text"
                  value={olvidoMotivo}
                  onChange={e => setOlvidoMotivo(e.target.value)}
                  required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
                />
                <p className="text-xs text-gray-400 mt-1">Quedará registrado en logs para evidencia de cumplimiento.</p>
              </div>

              {olvidoMsg && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{olvidoMsg}</p>
              )}

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setModalOlvido(false)}
                  className="flex-1 text-sm font-medium text-gray-700 border border-gray-300 rounded-xl py-2.5 hover:bg-gray-50 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={derechoAlOlvido.isPending || olvidoCedula.length !== 10}
                  className="flex-1 flex items-center justify-center gap-2 text-sm font-semibold text-white bg-amber-600 hover:bg-amber-700 rounded-xl py-2.5 transition-colors disabled:opacity-50"
                >
                  <UserX className="w-4 h-4" />
                  {derechoAlOlvido.isPending ? 'Ejecutando...' : 'Ejecutar borrado'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

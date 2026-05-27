import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, RefreshCw, Clock, Shield, BookOpen, Scale, Award, FileText } from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { SemaforoBadge } from '@/components/ui/Badge'
import { cn } from '@/lib/utils'
import type { ResultadoVerificacion } from '@/types'

interface FuenteCheck {
  id: string
  label: string
  desc: string
  icon: React.ElementType
  formKey: string
}

const FUENTES: FuenteCheck[] = [
  { id: 'bachiller', label: 'Bachiller (Educación)',      desc: 'SENESCYT / MinEduc',          icon: BookOpen,  formKey: 'bachiller' },
  { id: 'satje',     label: 'SATJE (Legal)',              desc: 'Función Judicial del Ecuador', icon: Scale,     formKey: 'satje' },
  { id: 'setec',     label: 'SETEC (Certificaciones)',    desc: 'Competencias laborales',       icon: Award,     formKey: 'setec_check' },
  { id: 'fiscalia',  label: 'Fiscalía (Antecedentes)',    desc: 'Registros penales',            icon: Shield,    formKey: 'fiscalia_check' },
]

export function BusquedaPage() {
  const navigate = useNavigate()
  const [cedula, setCedula] = useState('')
  const [fuentes, setFuentes] = useState({ bachiller: true, satje: true, setec_check: false, fiscalia_check: false })
  const [forzar, setForzar] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [resultado, setResultado] = useState<ResultadoVerificacion | null>(null)

  function toggleFuente(key: string) {
    setFuentes(prev => ({ ...prev, [key]: !prev[key as keyof typeof prev] }))
  }

  async function handleBuscar(e: React.FormEvent) {
    e.preventDefault()
    if (!cedula.trim()) return
    const ningunaSel = !Object.values(fuentes).some(Boolean)
    if (ningunaSel) { setError('Selecciona al menos una fuente'); return }

    setError('')
    setResultado(null)
    setLoading(true)

    try {
      const form = new FormData()
      form.append('cedula', cedula.trim())
      Object.entries(fuentes).forEach(([k, v]) => { if (v) form.append(k, '1') })
      if (forzar) form.append('forzar', '1')

      const res = await api.post<ResultadoVerificacion>('/api/buscar', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResultado(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error
      setError(msg === 'cedula_invalida' ? 'Cédula inválida para Ecuador' : 'Error al consultar. Intenta de nuevo.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900">Búsqueda Individual</h1>
        <p className="text-sm text-gray-500 mt-1">Verifica antecedentes de un candidato por cédula</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Formulario */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <form onSubmit={handleBuscar} className="space-y-5">
            {/* Cédula */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Cédula de Identidad
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  value={cedula}
                  onChange={e => setCedula(e.target.value.replace(/\D/g, '').slice(0, 10))}
                  placeholder="0912345678"
                  maxLength={10}
                  className="w-full pl-9 pr-4 py-2.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-700 focus:border-transparent"
                />
              </div>
              <p className="text-xs text-gray-400 mt-1">{cedula.length}/10 dígitos</p>
            </div>

            {/* Fuentes */}
            <div>
              <p className="text-sm font-medium text-gray-700 mb-2">Fuentes a consultar</p>
              <div className="space-y-2">
                {FUENTES.map(({ id, label, desc, icon: Icon, formKey }) => (
                  <label
                    key={id}
                    className={cn(
                      'flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                      fuentes[formKey as keyof typeof fuentes]
                        ? 'border-navy-700 bg-navy-900/5'
                        : 'border-gray-200 hover:border-gray-300',
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={fuentes[formKey as keyof typeof fuentes]}
                      onChange={() => toggleFuente(formKey)}
                      className="sr-only"
                    />
                    <div className={cn(
                      'w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0',
                      fuentes[formKey as keyof typeof fuentes] ? 'bg-navy-700 border-navy-700' : 'border-gray-300',
                    )}>
                      {fuentes[formKey as keyof typeof fuentes] && (
                        <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </div>
                    <Icon className="w-4 h-4 text-gray-500 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800">{label}</p>
                      <p className="text-xs text-gray-500">{desc}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Forzar re-consulta */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={forzar}
                onChange={e => setForzar(e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 text-navy-700"
              />
              <div className="flex items-center gap-1.5">
                <RefreshCw className="w-3.5 h-3.5 text-gray-400" />
                <span className="text-sm text-gray-600">Forzar re-consulta (ignorar caché)</span>
              </div>
            </label>

            {error && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
            )}

            <Button type="submit" loading={loading} className="w-full" size="lg">
              <Search className="w-4 h-4" />
              {loading ? 'Verificando...' : 'Verificar Candidato'}
            </Button>
          </form>
        </div>

        {/* Resultado inline */}
        <div>
          {loading && (
            <div className="bg-white rounded-xl border border-gray-200 p-8 shadow-sm flex flex-col items-center justify-center gap-4">
              <div className="w-12 h-12 rounded-full border-4 border-navy-700 border-t-transparent animate-spin" />
              <div className="text-center">
                <p className="font-medium text-gray-800">Consultando fuentes...</p>
                <p className="text-sm text-gray-500 mt-1">Esto puede tomar 10–30 segundos</p>
              </div>
              <div className="grid grid-cols-2 gap-2 w-full mt-2">
                {FUENTES.filter(f => fuentes[f.formKey as keyof typeof fuentes]).map(({ id, label, icon: Icon }) => (
                  <div key={id} className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2">
                    <Icon className="w-3.5 h-3.5 flex-shrink-0" />
                    <span className="truncate">{label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {resultado && !loading && (
            <ResultadoCard resultado={resultado} onVerDetalle={() => navigate(`/historial`)} />
          )}

          {!loading && !resultado && (
            <div className="bg-gray-50 rounded-xl border border-gray-200 border-dashed p-8 flex flex-col items-center justify-center text-center gap-3">
              <FileText className="w-10 h-10 text-gray-300" />
              <p className="text-sm text-gray-400">El resultado aparecerá aquí</p>
            </div>
          )}
        </div>
      </div>

      {/* Búsquedas recientes */}
      <RecentesSection />
    </div>
  )
}

// ── Resultado card ────────────────────────────────────────────────────────────
function ResultadoCard({ resultado, onVerDetalle }: { resultado: ResultadoVerificacion; onVerDetalle: () => void }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-navy-900 px-5 py-4">
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Reporte de Candidato</p>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-white font-bold text-lg leading-tight">
              {resultado.nombre || 'Sin nombre'}
            </p>
            <p className="text-white/50 text-xs mt-0.5">ID: {resultado.cedula}</p>
          </div>
          {resultado.semaforo && <SemaforoBadge nivel={resultado.semaforo as never} size="md" />}
        </div>
        {resultado._cache && (
          <div className="flex items-center gap-1 mt-2 text-white/40 text-xs">
            <Clock className="w-3 h-3" />
            <span>Resultado cacheado — {resultado.hace_cuanto || resultado.fecha}</span>
          </div>
        )}
      </div>

      {/* Fuentes */}
      <div className="p-4 space-y-2">
        {resultado.bachiller && (
          <FuenteRow icon={BookOpen} label="Bachiller (Educación)" estado={resultado.bachiller.estado}
            detalle={resultado.bachiller.titulo || resultado.bachiller.institucion} />
        )}
        {resultado.satje && (
          <FuenteRow icon={Scale} label="SATJE (Legal)" estado={resultado.satje.estado}
            detalle={resultado.satje.estado === 'CON_PROCESOS'
              ? `${resultado.satje.procesos?.length ?? 0} proceso(s)` : 'Sin procesos'} />
        )}
        {resultado.setec && (
          <FuenteRow icon={Award} label="SETEC (Certificaciones)" estado={resultado.setec.estado}
            detalle={resultado.setec.certificaciones?.length
              ? `${resultado.setec.certificaciones.length} certificación(es)` : 'Sin certificaciones'} />
        )}
        {resultado.fiscalia && (
          <FuenteRow icon={Shield} label="Fiscalía (Antecedentes)" estado={resultado.fiscalia.estado}
            detalle={resultado.fiscalia.estado === 'CON_REGISTROS'
              ? `${resultado.fiscalia.registros?.length ?? 0} registro(s)` : 'Sin registros'} />
        )}
      </div>

      <div className="px-4 pb-4">
        <button
          onClick={onVerDetalle}
          className="w-full text-sm text-navy-700 hover:text-navy-900 font-medium py-2 border border-navy-200 rounded-lg hover:bg-navy-50 transition-colors"
        >
          Ver en historial →
        </button>
      </div>
    </div>
  )
}

function FuenteRow({ icon: Icon, label, estado, detalle }: {
  icon: React.ElementType; label: string; estado: string; detalle?: string
}) {
  const ok = estado === 'ENCONTRADO' || estado === 'SIN_PROCESOS' || estado === 'SIN_REGISTROS'
  const warn = estado === 'CON_PROCESOS' || estado === 'CON_REGISTROS'
  const err = estado === 'ERROR' || estado === 'NO_ENCONTRADO'
  return (
    <div className="flex items-center gap-3 p-2.5 rounded-lg bg-gray-50">
      <Icon className="w-4 h-4 text-gray-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-gray-700">{label}</p>
        {detalle && <p className="text-xs text-gray-500 truncate">{detalle}</p>}
      </div>
      <span className={cn(
        'text-xs font-semibold px-2 py-0.5 rounded-md',
        ok && 'bg-green-100 text-green-700',
        warn && 'bg-red-100 text-red-700',
        err && 'bg-gray-100 text-gray-500',
      )}>
        {ok ? 'OK' : warn ? 'ALERTA' : 'ERROR'}
      </span>
    </div>
  )
}

// ── Búsquedas recientes ───────────────────────────────────────────────────────
function RecentesSection() {
  const [recientes, setRecientes] = useState<{ cedula: string; nombre?: string; semaforo: string; timestamp: number }[]>([])

  // Carga al montar
  useState(() => {
    api.get('/api/historial?limite=5').then(res => {
      setRecientes(res.data.entradas?.slice(0, 5) ?? [])
    }).catch(() => {})
  })

  if (!recientes.length) return null

  return (
    <div className="mt-8">
      <div className="flex items-center gap-2 mb-3">
        <Clock className="w-4 h-4 text-gray-400" />
        <h2 className="text-sm font-semibold text-gray-700">Búsquedas recientes</h2>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm divide-y divide-gray-100">
        {recientes.map(r => (
          <div key={r.cedula} className="flex items-center gap-4 px-4 py-3">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">{r.nombre || 'Sin nombre'}</p>
              <p className="text-xs text-gray-500">{r.cedula}</p>
            </div>
            {r.semaforo && <SemaforoBadge nivel={r.semaforo as never} size="sm" />}
          </div>
        ))}
      </div>
    </div>
  )
}

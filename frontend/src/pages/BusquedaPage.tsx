import { useState, useEffect } from 'react'
import {
  Search, RefreshCw, Clock, Shield, BookOpen, Scale, Award, FileText,
  CheckCircle, XCircle, AlertTriangle, AlertOctagon, ShieldCheck,
  GraduationCap, Gavel, MinusCircle, Download, ArrowLeft, Database,
} from 'lucide-react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { ResultadoVerificacion, ResultadoBachiller, ResultadoSatje, ResultadoSetec, ResultadoFiscalia } from '@/types'

interface FuenteCheck {
  id: string
  label: string
  desc: string
  icon: React.ElementType
  formKey: string
}

const FUENTES: FuenteCheck[] = [
  { id: 'bachiller', label: 'Bachiller (Educación)',   desc: 'SENESCYT / MinEduc',          icon: BookOpen, formKey: 'bachiller' },
  { id: 'satje',     label: 'SATJE (Legal)',           desc: 'Función Judicial del Ecuador', icon: Scale,    formKey: 'satje' },
  { id: 'setec',     label: 'SETEC (Certificaciones)', desc: 'Competencias laborales',       icon: Award,    formKey: 'setec_check' },
  { id: 'fiscalia',  label: 'Fiscalía (Antecedentes)', desc: 'Registros penales',            icon: Shield,   formKey: 'fiscalia_check' },
]

// Semáforo → clases de gradiente hero
const SEM_HERO: Record<string, { gradient: string; text: string }> = {
  'APTO':        { gradient: 'from-emerald-500 via-emerald-600 to-teal-700',    text: 'text-emerald-50' },
  'OBSERVACIÓN': { gradient: 'from-amber-500 via-amber-600 to-orange-700',      text: 'text-amber-50' },
  'RECHAZAR':    { gradient: 'from-red-500 via-red-600 to-red-800',             text: 'text-red-50' },
  'CRÍTICO':     { gradient: 'from-red-900 via-red-950 to-slate-950',           text: 'text-red-100' },
  '':            { gradient: 'from-slate-600 via-slate-700 to-slate-900',       text: 'text-slate-100' },
}

function semaforoHero(sem?: string) {
  return SEM_HERO[sem ?? ''] ?? SEM_HERO['']
}

export function BusquedaPage() {
  const [cedula, setCedula]     = useState('')
  const [fuentes, setFuentes]   = useState({ bachiller: true, satje: true, setec_check: false, fiscalia_check: false })
  const [forzar, setForzar]     = useState(false)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
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

  async function handleReverificar() {
    if (!resultado) return
    // Reconstruye las fuentes a partir de lo que vino en el resultado
    setFuentes({
      bachiller:      !!resultado.bachiller,
      satje:          !!resultado.satje,
      setec_check:    !!resultado.setec,
      fiscalia_check: !!resultado.fiscalia,
    })
    setCedula(resultado.cedula)
    setForzar(true)
    setResultado(null)
    // Pequeño delay para que el estado se actualice, luego submit
    setTimeout(() => {
      document.getElementById('buscar-form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    }, 50)
  }

  async function handlePdf() {
    if (!resultado) return
    try {
      const form = new FormData()
      form.append('cedula', resultado.cedula)
      if (resultado.bachiller) form.append('bachiller', '1')
      if (resultado.satje)     form.append('satje', '1')
      if (resultado.setec)     form.append('setec_check', '1')
      if (resultado.fiscalia)  form.append('fiscalia_check', '1')
      const res = await api.post('/pdf', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `verificacion_${resultado.cedula}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // silent fail — user can try from historial
    }
  }

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900">Búsqueda Individual</h1>
        <p className="text-sm text-gray-500 mt-1">Verifica antecedentes de un candidato por cédula</p>
      </div>

      {/* Form + placeholder row */}
      <div className={cn('grid gap-6', resultado || loading ? 'grid-cols-1 lg:grid-cols-[380px_1fr]' : 'grid-cols-1 lg:grid-cols-2')}>
        {/* Formulario */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm self-start">
          <form id="buscar-form" onSubmit={handleBuscar} className="space-y-5">
            {/* Cédula */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Cédula de Identidad</label>
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
                  <label key={id} className={cn(
                    'flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                    fuentes[formKey as keyof typeof fuentes]
                      ? 'border-navy-700 bg-navy-900/5'
                      : 'border-gray-200 hover:border-gray-300',
                  )}>
                    <input type="checkbox" checked={fuentes[formKey as keyof typeof fuentes]}
                      onChange={() => toggleFuente(formKey)} className="sr-only" />
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
              <input type="checkbox" checked={forzar} onChange={e => setForzar(e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 text-navy-700" />
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

        {/* Resultado / placeholder */}
        <div>
          {loading && <LoadingCard fuentes={FUENTES.filter(f => fuentes[f.formKey as keyof typeof fuentes])} />}
          {resultado && !loading && <ResultadoCompleto resultado={resultado} onPdf={handlePdf} onNuevaBusqueda={() => setResultado(null)} onReverificar={handleReverificar} />}
          {!loading && !resultado && (
            <div className="bg-gray-50 rounded-xl border border-gray-200 border-dashed p-12 flex flex-col items-center justify-center text-center gap-3">
              <FileText className="w-12 h-12 text-gray-300" />
              <p className="text-sm text-gray-400">El resultado aparecerá aquí</p>
              <p className="text-xs text-gray-300">Ingresa una cédula ecuatoriana y selecciona las fuentes</p>
            </div>
          )}
        </div>
      </div>

      {/* Búsquedas recientes */}
      {!resultado && <RecentesSection onSelect={c => setCedula(c)} />}
    </div>
  )
}

// ── Loading card ──────────────────────────────────────────────────────────────
function LoadingCard({ fuentes }: { fuentes: FuenteCheck[] }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-8 shadow-sm flex flex-col items-center justify-center gap-4">
      <div className="w-14 h-14 rounded-full border-4 border-navy-700 border-t-transparent animate-spin" />
      <div className="text-center">
        <p className="font-semibold text-gray-800">Consultando fuentes oficiales...</p>
        <p className="text-sm text-gray-500 mt-1">Esto puede tomar 10–30 segundos</p>
      </div>
      <div className="grid grid-cols-2 gap-2 w-full mt-2">
        {fuentes.map(({ id, label, icon: Icon }) => (
          <div key={id} className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2">
            <Icon className="w-3.5 h-3.5 flex-shrink-0 animate-pulse" />
            <span className="truncate">{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Resultado completo ────────────────────────────────────────────────────────
function ResultadoCompleto({ resultado, onPdf, onNuevaBusqueda, onReverificar }: {
  resultado: ResultadoVerificacion
  onPdf: () => void
  onNuevaBusqueda: () => void
  onReverificar: () => void
}) {
  const sem   = resultado.semaforo ?? ''
  const hero  = semaforoHero(sem)

  return (
    <div className="space-y-4">
      {/* Cache banner */}
      {resultado._cache && (
        <div className="flex items-center justify-between gap-3 bg-blue-50 border border-blue-200 rounded-lg px-4 py-2.5">
          <div className="flex items-center gap-2 text-sm text-blue-800">
            <Database className="w-4 h-4 flex-shrink-0 text-blue-500" />
            <span>
              <strong>Resultado desde caché.</strong>
              {resultado.hace_cuanto ? ` Consultado ${resultado.hace_cuanto}.` : ''}
            </span>
          </div>
          <button
            onClick={onReverificar}
            className="flex items-center gap-1.5 text-xs font-semibold text-blue-700 border border-blue-300 hover:bg-blue-100 px-2.5 py-1.5 rounded-lg transition-colors flex-shrink-0"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Re-verificar
          </button>
        </div>
      )}

      {/* Hero — Veredicto */}
      <div className={cn('relative overflow-hidden rounded-2xl bg-gradient-to-br text-white shadow-lg', hero.gradient)}>
        <div className="absolute -top-24 -right-24 w-64 h-64 bg-white/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-64 h-64 bg-white/5 rounded-full blur-3xl" />
        <div className="relative p-6 sm:p-8">
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-white/60 mb-3">Veredicto oficial</p>
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div>
              <p className="text-4xl sm:text-5xl font-extrabold tracking-tight">
                {sem || 'Sin veredicto'}
              </p>
              {sem === '' && (
                <p className="text-white/60 text-sm mt-1">Selecciona Bachiller + SATJE para obtener semáforo</p>
              )}
            </div>
            <div className="text-left sm:text-right flex-shrink-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-white/60 mb-1">Cédula</p>
              <p className="font-mono text-xl font-bold">{resultado.cedula}</p>
            </div>
          </div>
          <div className="mt-5 pt-5 border-t border-white/15">
            <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-white/60 mb-1">Nombre oficial</p>
            <p className="text-xl sm:text-2xl font-bold tracking-tight">
              {resultado.nombre || <span className="opacity-50 italic text-base font-normal">No disponible</span>}
            </p>
          </div>
          {resultado.fecha && (
            <p className="text-xs text-white/40 mt-3">Verificado: {resultado.fecha}</p>
          )}
        </div>
      </div>

      {/* Bachiller */}
      {resultado.bachiller && <BachillerCard b={resultado.bachiller} />}

      {/* SATJE */}
      {resultado.satje && <SatjeCard s={resultado.satje} />}

      {/* SETEC */}
      {resultado.setec && <SetecCard st={resultado.setec} />}

      {/* Fiscalía */}
      {resultado.fiscalia && <FiscaliaCard f={resultado.fiscalia} />}

      {/* Acciones */}
      <div className="flex flex-col sm:flex-row gap-3 pt-1">
        <button
          onClick={onNuevaBusqueda}
          className="flex-1 flex items-center justify-center gap-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-xl py-3 hover:bg-gray-50 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Nueva búsqueda
        </button>
        <button
          onClick={onPdf}
          className="flex-1 flex items-center justify-center gap-2 text-sm font-semibold text-white bg-navy-700 hover:bg-navy-800 rounded-xl py-3 transition-colors"
        >
          <Download className="w-4 h-4" />
          Descargar PDF oficial
        </button>
      </div>
    </div>
  )
}

// ── Bachiller ─────────────────────────────────────────────────────────────────
function BachillerCard({ b }: { b: ResultadoBachiller }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0">
          <GraduationCap className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-bold text-gray-900">Bachiller</h3>
          <p className="text-xs text-gray-500">Ministerio de Educación del Ecuador</p>
        </div>
      </div>

      {b.estado === 'ENCONTRADO' ? (
        <div className="rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-emerald-50/30 p-5">
          <div className="flex items-start gap-3 mb-4">
            <div className="w-9 h-9 rounded-xl bg-emerald-500 text-white flex items-center justify-center flex-shrink-0 shadow-md shadow-emerald-500/30">
              <CheckCircle className="w-5 h-5" />
            </div>
            <div>
              <p className="font-bold text-emerald-900">Título confirmado oficialmente</p>
              <p className="text-xs text-emerald-700 mt-0.5">Registro oficial verificado</p>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3 pl-12">
            {b.titulo && (
              <div>
                <p className="text-[10px] uppercase tracking-wider font-bold text-emerald-700/80 mb-0.5">Título</p>
                <p className="text-sm font-bold text-gray-900">{b.titulo}</p>
              </div>
            )}
            {b.especialidad && (
              <div>
                <p className="text-[10px] uppercase tracking-wider font-bold text-emerald-700/80 mb-0.5">Especialidad</p>
                <p className="text-sm font-bold text-gray-900">{b.especialidad}</p>
              </div>
            )}
            {b.institucion && (
              <div className="sm:col-span-2">
                <p className="text-[10px] uppercase tracking-wider font-bold text-emerald-700/80 mb-0.5">Institución</p>
                <p className="text-sm font-bold text-gray-900">{b.institucion}</p>
              </div>
            )}
            {b.fecha_grado && (
              <div>
                <p className="text-[10px] uppercase tracking-wider font-bold text-emerald-700/80 mb-0.5">Año de grado</p>
                <p className="text-sm font-bold text-gray-900 font-mono">{b.fecha_grado.slice(0, 4)}</p>
              </div>
            )}
          </div>
        </div>
      ) : b.estado === 'NO_ENCONTRADO' ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-amber-500 text-white flex items-center justify-center flex-shrink-0">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-amber-900">Sin registro oficial</p>
            <p className="text-sm text-amber-800 mt-0.5">No existe título de bachiller registrado para esta cédula en el Ministerio.</p>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-gray-400 text-white flex items-center justify-center flex-shrink-0">
            <XCircle className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-gray-700">Error de consulta</p>
            <p className="text-sm text-gray-600 mt-0.5">{b.detalle || 'No se pudo completar la consulta'}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── SATJE ─────────────────────────────────────────────────────────────────────
function SatjeCard({ s }: { s: ResultadoSatje }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0">
          <Gavel className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-bold text-gray-900">Procesos Judiciales</h3>
          <p className="text-xs text-gray-500">SATJE — Función Judicial del Ecuador</p>
        </div>
      </div>

      {s.estado === 'SIN_PROCESOS' ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-emerald-500 text-white flex items-center justify-center flex-shrink-0 shadow-md shadow-emerald-500/30">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-emerald-900">Sin procesos judiciales</p>
            <p className="text-sm text-emerald-800 mt-0.5">No tiene causas activas como demandado ni como actor en la Función Judicial.</p>
          </div>
        </div>
      ) : s.estado === 'TIENE_PROCESOS' ? (
        <div className="space-y-4">
          {/* Contadores */}
          <div className="grid grid-cols-2 gap-3">
            <div className={cn('rounded-xl p-4 text-center border',
              (s.total_demandado ?? 0) > 0
                ? 'bg-gradient-to-br from-red-50 to-red-50/30 border-red-200'
                : 'bg-gray-50 border-gray-200')}>
              <p className={cn('text-4xl font-extrabold tracking-tight font-mono',
                (s.total_demandado ?? 0) > 0 ? 'text-red-700' : 'text-gray-400')}>
                {s.total_demandado ?? 0}
              </p>
              <p className={cn('text-[10px] uppercase tracking-wider font-bold mt-1',
                (s.total_demandado ?? 0) > 0 ? 'text-red-700' : 'text-gray-500')}>
                Como demandado
              </p>
            </div>
            <div className={cn('rounded-xl p-4 text-center border',
              (s.total_actor ?? 0) > 0
                ? 'bg-gradient-to-br from-amber-50 to-amber-50/30 border-amber-200'
                : 'bg-gray-50 border-gray-200')}>
              <p className={cn('text-4xl font-extrabold tracking-tight font-mono',
                (s.total_actor ?? 0) > 0 ? 'text-amber-700' : 'text-gray-400')}>
                {s.total_actor ?? 0}
              </p>
              <p className={cn('text-[10px] uppercase tracking-wider font-bold mt-1',
                (s.total_actor ?? 0) > 0 ? 'text-amber-700' : 'text-gray-500')}>
                Como actor
              </p>
            </div>
          </div>

          {/* Delitos */}
          {s.delitos && s.delitos.length > 0 && (
            <div className="rounded-xl border border-red-200 bg-gradient-to-br from-red-50 to-red-50/30 p-5">
              <div className="flex items-center gap-2.5 mb-3">
                <div className="w-8 h-8 rounded-lg bg-red-500 text-white flex items-center justify-center shadow-md shadow-red-500/30">
                  <AlertOctagon className="w-4 h-4" />
                </div>
                <p className="font-bold text-red-900">Delitos detectados</p>
              </div>
              <ul className="space-y-2 pl-11">
                {s.delitos.map((d, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-red-900">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 mt-2 flex-shrink-0" />
                    <span className="font-medium">{d}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-gray-400 text-white flex items-center justify-center flex-shrink-0">
            <XCircle className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-gray-700">Error de consulta</p>
            <p className="text-sm text-gray-600 mt-0.5">{s.detalle || 'No se pudo completar la consulta'}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── SETEC ─────────────────────────────────────────────────────────────────────
function SetecCard({ st }: { st: ResultadoSetec }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center flex-shrink-0">
          <Award className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-bold text-gray-900">Capacitaciones Oficiales</h3>
          <p className="text-xs text-gray-500">SETEC — Ministerio de Trabajo del Ecuador</p>
        </div>
      </div>

      {st.estado === 'TIENE_CERTIFICADOS' ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-2xl font-extrabold text-violet-700 font-mono">{st.total ?? st.cursos?.length ?? 0}</span>
            <span className="text-xs font-bold text-violet-600 uppercase tracking-wider">
              certificación{(st.total ?? 0) !== 1 ? 'es' : ''} registrada{(st.total ?? 0) !== 1 ? 's' : ''}
            </span>
          </div>
          <ul className="space-y-2">
            {(st.cursos ?? []).map((curso, i) => (
              <li key={i} className="flex items-start gap-2.5 rounded-lg border border-violet-100 bg-violet-50/50 px-4 py-2.5">
                <div className="w-5 h-5 rounded-full bg-violet-500 text-white flex items-center justify-center flex-shrink-0 mt-0.5">
                  <CheckCircle className="w-3 h-3" />
                </div>
                <span className="text-sm font-semibold text-gray-800">{curso}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : st.estado === 'SIN_CERTIFICADOS' ? (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-gray-200 text-gray-500 flex items-center justify-center flex-shrink-0">
            <MinusCircle className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-gray-700">Sin certificaciones registradas</p>
            <p className="text-sm text-gray-500 mt-0.5">No tiene cursos registrados en el SETEC.</p>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-gray-300 text-gray-500 flex items-center justify-center flex-shrink-0">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-gray-600">Portal no disponible</p>
            <p className="text-sm text-gray-500 mt-0.5">{st.detalle || 'No se pudo consultar el SETEC en este momento.'}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Fiscalía ──────────────────────────────────────────────────────────────────
function FiscaliaCard({ f }: { f: ResultadoFiscalia }) {
  const sospechosas = (f.noticias ?? []).filter(n =>
    ['SOSPECHOSO', 'IMPUTADO', 'PROCESADO', 'ACUSADO', 'SENTENCIADO', 'INVESTIGADO'].includes(n.rol ?? ''),
  )

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className={cn('w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0',
          f.tiene_antecedentes ? 'bg-red-50 text-red-600' : 'bg-gray-50 text-gray-500')}>
          <Shield className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-bold text-gray-900">Noticias del Delito</h3>
          <p className="text-xs text-gray-500">SIAF — Fiscalía General del Estado del Ecuador</p>
        </div>
      </div>

      {f.estado === 'SOSPECHOSO' ? (
        <div className="space-y-3">
          <div className="rounded-xl border border-red-200 bg-red-50 p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-xl bg-red-500 text-white flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div>
                <p className="font-bold text-red-800">
                  Aparece como sospechoso en {f.como_sospechoso} noticia(s)
                </p>
                <p className="text-sm text-red-600 mt-0.5">{f.detalle}</p>
              </div>
            </div>
            {sospechosas.length > 0 && (
              <ul className="space-y-2 mt-3">
                {sospechosas.map((n, i) => (
                  <li key={i} className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-white px-4 py-3">
                    <div className="w-5 h-5 rounded-full bg-red-500 text-white flex items-center justify-center flex-shrink-0 mt-0.5">
                      <XCircle className="w-3 h-3" />
                    </div>
                    <div className="text-sm flex flex-wrap gap-x-2 gap-y-0.5 items-baseline">
                      <span className="font-bold text-red-800">{n.delito || 'Delito no especificado'}</span>
                      {n.fecha && <span className="text-gray-500">{n.fecha}</span>}
                      {n.lugar && <span className="text-gray-400">· {n.lugar}</span>}
                      {n.rol && (
                        <span className="text-xs font-semibold text-red-600 bg-red-100 px-2 py-0.5 rounded-full">
                          {n.rol}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : f.estado === 'DENUNCIANTE' ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-amber-100 text-amber-600 flex items-center justify-center flex-shrink-0">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-amber-800">Aparece como denunciante/víctima</p>
            <p className="text-sm text-amber-700 mt-0.5">{f.detalle} — No implica responsabilidad penal.</p>
          </div>
        </div>
      ) : f.estado === 'SIN_ANTECEDENTES' ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-emerald-100 text-emerald-600 flex items-center justify-center flex-shrink-0">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-emerald-800">Sin antecedentes en Fiscalía</p>
            <p className="text-sm text-emerald-700 mt-0.5">No se encontraron noticias del delito para esta cédula.</p>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-gray-300 text-gray-500 flex items-center justify-center flex-shrink-0">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <p className="font-bold text-gray-600">Portal no disponible</p>
            <p className="text-sm text-gray-500 mt-0.5">{f.detalle || 'No se pudo consultar la Fiscalía en este momento.'}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Búsquedas recientes ───────────────────────────────────────────────────────
function RecentesSection({ onSelect }: { onSelect: (cedula: string) => void }) {
  const [recientes, setRecientes] = useState<{ cedula: string; nombre?: string; semaforo: string }[]>([])

  useEffect(() => {
    api.get('/api/historial?limite=5').then(res => {
      setRecientes(res.data.entradas?.slice(0, 5) ?? [])
    }).catch(() => {})
  }, [])

  if (!recientes.length) return null

  const SEM_COLOR: Record<string, string> = {
    'APTO': 'bg-emerald-100 text-emerald-700',
    'OBSERVACIÓN': 'bg-amber-100 text-amber-700',
    'RECHAZAR': 'bg-red-100 text-red-700',
    'CRÍTICO': 'bg-red-900 text-red-100',
    'SIN DATOS': 'bg-gray-100 text-gray-500',
  }

  return (
    <div className="mt-8">
      <div className="flex items-center gap-2 mb-3">
        <Clock className="w-4 h-4 text-gray-400" />
        <h2 className="text-sm font-semibold text-gray-700">Búsquedas recientes</h2>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm divide-y divide-gray-100">
        {recientes.map(r => (
          <button
            key={r.cedula}
            onClick={() => onSelect(r.cedula)}
            className="w-full flex items-center gap-4 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">{r.nombre || 'Sin nombre'}</p>
              <p className="text-xs text-gray-500">{r.cedula}</p>
            </div>
            {r.semaforo && (
              <span className={cn('text-xs font-semibold px-2.5 py-1 rounded-full flex-shrink-0',
                SEM_COLOR[r.semaforo] ?? 'bg-gray-100 text-gray-500')}>
                {r.semaforo}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

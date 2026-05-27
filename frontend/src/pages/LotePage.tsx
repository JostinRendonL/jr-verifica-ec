import { useState, useRef } from 'react'
import { Upload, FileSpreadsheet, X, Download, CheckCircle, BookOpen, Scale, Award, Shield } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { SemaforoBadge } from '@/components/ui/Badge'
import { cn } from '@/lib/utils'
import type { NivelSemaforo } from '@/types'

interface JobStatus {
  id: string
  tipo: string
  estado: 'pendiente' | 'procesando' | 'completado' | 'error'
  total: number
  procesados: number
  progreso: number
  error?: string
  puede_descargar: boolean
  semaforos?: Record<NivelSemaforo, number>
}

const FUENTES = [
  { label: 'Bachiller (Educación)',   formKey: 'bachiller',      icon: BookOpen },
  { label: 'SATJE (Legal)',           formKey: 'satje',          icon: Scale },
  { label: 'SETEC (Certificaciones)', formKey: 'setec_check',    icon: Award },
  { label: 'Fiscalía (Antecedentes)', formKey: 'fiscalia_check', icon: Shield },
]

export function LotePage() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [archivo, setArchivo] = useState<File | null>(null)
  const [fuentes, setFuentes] = useState({ bachiller: true, satje: true, setec_check: false, fiscalia_check: false })
  const [jobId, setJobId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  // Polling mientras el job esté activo
  const { data: job } = useQuery<JobStatus>({
    queryKey: ['job', jobId],
    queryFn: async () => {
      const res = await api.get(`/job/${jobId}/status`)
      return res.data
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const estado = query.state.data?.estado
      return (estado === 'procesando' || estado === 'pendiente') ? 2000 : false
    },
  })

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.files[0]
    if (f?.name.endsWith('.xlsx')) setArchivo(f)
  }

  async function handleSubir() {
    if (!archivo) return
    const ningunaSel = !Object.values(fuentes).some(Boolean)
    if (ningunaSel) { setError('Selecciona al menos una fuente'); return }

    setError('')
    setUploading(true)
    try {
      const form = new FormData()
      form.append('archivo', archivo)
      Object.entries(fuentes).forEach(([k, v]) => { if (v) form.append(k, '1') })
      const res = await api.post<{ job_id: string; total: number }>('/api/procesar', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setJobId(res.data.job_id)
      setArchivo(null)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error
      setError(msg === 'excel_invalido' ? 'El archivo Excel no tiene el formato correcto'
        : msg === 'archivo_vacio' ? 'El archivo no contiene cédulas'
        : 'Error al subir el archivo. Intenta de nuevo.')
    } finally {
      setUploading(false)
    }
  }

  function resetear() {
    setJobId(null)
    setArchivo(null)
    setError('')
  }

  const procesando = job?.estado === 'procesando' || job?.estado === 'pendiente'
  const completado = job?.estado === 'completado'
  const conError   = job?.estado === 'error'

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900">Verificación por Lote</h1>
        <p className="text-sm text-gray-500 mt-1">Sube un Excel con cédulas y verifica múltiples candidatos en paralelo</p>
      </div>

      {/* Panel de carga — solo si no hay job activo */}
      {!jobId && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
          {/* Drop zone */}
          <div
            onDrop={handleDrop}
            onDragOver={e => e.preventDefault()}
            onClick={() => fileRef.current?.click()}
            className={cn(
              'border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors',
              archivo ? 'border-navy-400 bg-navy-50' : 'border-gray-300 hover:border-gray-400',
            )}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={e => setArchivo(e.target.files?.[0] ?? null)}
            />
            {archivo ? (
              <div className="flex items-center justify-center gap-3">
                <FileSpreadsheet className="w-8 h-8 text-navy-700" />
                <div className="text-left">
                  <p className="font-medium text-gray-800">{archivo.name}</p>
                  <p className="text-sm text-gray-500">{(archivo.size / 1024).toFixed(0)} KB</p>
                </div>
                <button onClick={e => { e.stopPropagation(); setArchivo(null) }}
                  className="ml-2 text-gray-400 hover:text-gray-600">
                  <X className="w-5 h-5" />
                </button>
              </div>
            ) : (
              <div>
                <Upload className="w-10 h-10 text-gray-300 mx-auto mb-3" />
                <p className="font-medium text-gray-700">Arrastra tu Excel aquí o haz clic para seleccionar</p>
                <p className="text-sm text-gray-400 mt-1">Formato: .xlsx con columna "Cédula"</p>
              </div>
            )}
          </div>

          {/* Fuentes */}
          <div>
            <p className="text-sm font-medium text-gray-700 mb-2">Fuentes a consultar</p>
            <div className="grid grid-cols-2 gap-2">
              {FUENTES.map(({ label, formKey, icon: Icon }) => (
                <label key={formKey}
                  className={cn(
                    'flex items-center gap-2 p-3 rounded-lg border cursor-pointer text-sm transition-colors',
                    fuentes[formKey as keyof typeof fuentes]
                      ? 'border-navy-700 bg-navy-900/5 text-navy-900 font-medium'
                      : 'border-gray-200 text-gray-600 hover:border-gray-300',
                  )}
                >
                  <input type="checkbox" className="sr-only"
                    checked={fuentes[formKey as keyof typeof fuentes]}
                    onChange={() => setFuentes(p => ({ ...p, [formKey]: !p[formKey as keyof typeof p] }))} />
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  {label}
                </label>
              ))}
            </div>
          </div>

          {/* Descarga plantilla */}
          <a href="/plantilla" className="flex items-center gap-2 text-sm text-navy-700 hover:underline w-fit">
            <Download className="w-4 h-4" />
            Descargar plantilla Excel
          </a>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}

          <Button onClick={handleSubir} loading={uploading} disabled={!archivo} size="lg" className="w-full">
            <Upload className="w-4 h-4" />
            {uploading ? 'Subiendo...' : 'Iniciar Verificación'}
          </Button>
        </div>
      )}

      {/* Estado del job */}
      {job && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          {/* Header estado */}
          <div className={cn(
            'px-6 py-4',
            procesando && 'bg-navy-900',
            completado && 'bg-green-700',
            conError && 'bg-red-700',
          )}>
            <p className="text-white/60 text-xs uppercase tracking-wider mb-1">
              {procesando ? 'Ejecutando Verificación' : completado ? 'Verificación Completada' : 'Error en Verificación'}
            </p>
            <div className="flex items-center justify-between">
              <p className="text-white font-bold text-xl">
                {procesando && `${job.procesados} / ${job.total}`}
                {completado && `${job.total} candidatos verificados`}
                {conError && 'Se produjo un error'}
              </p>
              {procesando && (
                <span className="text-white/80 text-lg font-semibold">{job.progreso.toFixed(0)}%</span>
              )}
              {completado && <CheckCircle className="w-7 h-7 text-white/80" />}
            </div>

            {/* Barra de progreso */}
            {procesando && (
              <div className="mt-3 bg-white/20 rounded-full h-2 overflow-hidden">
                <div
                  className="h-full bg-white rounded-full transition-all duration-500"
                  style={{ width: `${job.progreso}%` }}
                />
              </div>
            )}
          </div>

          {/* Desglose semáforo */}
          {(procesando || completado) && (
            <div className="px-6 py-4 grid grid-cols-2 sm:grid-cols-4 gap-3 border-b border-gray-100">
              {(['APTO', 'OBSERVACIÓN', 'RECHAZAR', 'CRÍTICO'] as NivelSemaforo[]).map(nivel => (
                <div key={nivel} className="text-center">
                  <p className="text-2xl font-bold text-gray-800">
                    {job.semaforos?.[nivel] ?? 0}
                  </p>
                  <SemaforoBadge nivel={nivel} size="sm" className="mt-1" />
                </div>
              ))}
            </div>
          )}

          {/* Workers activos */}
          {procesando && (
            <div className="px-6 py-3 flex items-center gap-2 bg-navy-50">
              <div className="flex gap-1">
                {[1, 2, 3].map(i => (
                  <span key={i} className="w-2 h-2 bg-navy-700 rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </div>
              <p className="text-xs text-navy-700 font-medium">3 workers activos en paralelo</p>
            </div>
          )}

          {/* Acciones */}
          <div className="px-6 py-4 flex items-center gap-3">
            {completado && job.puede_descargar && (
              <Button onClick={() => window.open(`/job/${job.id}/descargar`, '_blank')} size="sm">
                <Download className="w-4 h-4" />
                Descargar Reporte Excel
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={resetear}>
              Nueva verificación
            </Button>
          </div>

          {conError && job.error && (
            <div className="px-6 pb-4">
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {job.error}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

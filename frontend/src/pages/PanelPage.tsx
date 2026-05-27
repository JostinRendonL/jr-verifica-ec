import { useQuery } from '@tanstack/react-query'
import { RefreshCw, TrendingUp, Clock, DollarSign, CheckCircle } from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import type { NivelSemaforo } from '@/types'

interface Stats {
  total: number
  hoy: number
  semana: number
  mes: number
  niveles: Record<NivelSemaforo | string, number>
  por_dia: Record<string, number>
}

const NIVEL_COLOR: Record<string, string> = {
  'APTO':        'bg-green-500',
  'OBSERVACIÓN': 'bg-amber-400',
  'RECHAZAR':    'bg-red-500',
  'CRÍTICO':     'bg-red-900',
  'SIN DATOS':   'bg-gray-300',
}

const NIVEL_TEXT: Record<string, string> = {
  'APTO':        'text-green-700',
  'OBSERVACIÓN': 'text-amber-700',
  'RECHAZAR':    'text-red-700',
  'CRÍTICO':     'text-red-900',
  'SIN DATOS':   'text-gray-500',
}

export function PanelPage() {
  const { data: stats, isLoading, refetch } = useQuery<Stats>({
    queryKey: ['stats'],
    queryFn: async () => {
      const res = await api.get('/api/stats')
      return res.data
    },
    staleTime: 1000 * 60 * 2, // 2 min cache
  })

  // Calcular horas ahorradas (estimado: 3 min por verificación manual)
  const horasAhorradas = stats ? Math.round((stats.total * 3) / 60) : 0
  // Valor estimado (3 min de RRHH a $10/h = $0.5 por verificación)
  const valorAhorrado = stats ? Math.round(stats.total * 0.5) : 0

  // Distribucion del mes para el donut
  const niveles = stats?.niveles ?? {}
  const totalMes = Object.values(niveles).reduce((a, b) => a + b, 0)

  // Actividad por día (últimos 30 días)
  const porDia = stats?.por_dia ?? {}
  const dias = Object.entries(porDia).sort(([a], [b]) => a.localeCompare(b)).slice(-30)
  const maxDia = Math.max(...dias.map(([, v]) => v), 1)

  return (
    <div className="p-8">
      <div className="flex items-start justify-between mb-8">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-1">Executive Dashboard</p>
          <h1 className="text-2xl font-semibold text-gray-900">Panel de Control</h1>
          <p className="text-sm text-gray-500 mt-1">Rendimiento Operativo · últimos 30 días</p>
        </div>
        <button onClick={() => refetch()}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors">
          <RefreshCw className="w-4 h-4" />
          Actualizar
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-24 text-gray-400 gap-3">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span className="text-sm">Cargando estadísticas...</span>
        </div>
      ) : (
        <div className="space-y-6">
          {/* KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              icon={CheckCircle}
              label="Total Verificaciones"
              value={stats?.total.toLocaleString() ?? '0'}
              sub={`${stats?.mes.toLocaleString()} este mes`}
              iconColor="text-navy-700"
              iconBg="bg-navy-50"
            />
            <KpiCard
              icon={Clock}
              label="Horas Ahorradas"
              value={`${horasAhorradas.toLocaleString()}h`}
              sub="Basado en 3 min por caso manual"
              iconColor="text-blue-600"
              iconBg="bg-blue-50"
            />
            <KpiCard
              icon={DollarSign}
              label="Dinero Ahorrado (USD)"
              value={`$${valorAhorrado.toLocaleString()}`}
              sub="Estimado vs. proceso manual"
              iconColor="text-green-600"
              iconBg="bg-green-50"
            />
            <KpiCard
              icon={TrendingUp}
              label="Hoy"
              value={stats?.hoy.toLocaleString() ?? '0'}
              sub={`${stats?.semana.toLocaleString()} esta semana`}
              iconColor="text-amber-600"
              iconBg="bg-amber-50"
            />
          </div>

          {/* Gráficos */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Actividad 30 días */}
            <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <p className="text-sm font-semibold text-gray-800 mb-4">Actividad (30 Días)</p>
              <div className="flex items-end gap-1 h-32">
                {dias.map(([fecha, count]) => (
                  <div key={fecha} className="flex-1 flex flex-col items-center gap-1 group relative"
                    title={`${fecha}: ${count}`}>
                    <div
                      className="w-full bg-navy-700 rounded-t-sm hover:bg-navy-600 transition-colors cursor-pointer"
                      style={{ height: `${Math.max(4, (count / maxDia) * 100)}%` }}
                    />
                  </div>
                ))}
                {dias.length === 0 && (
                  <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
                    Sin datos suficientes
                  </div>
                )}
              </div>
            </div>

            {/* Distribución semáforo */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <p className="text-sm font-semibold text-gray-800 mb-4">Distribución Semáforo</p>
              <div className="space-y-2.5">
                {(['APTO', 'OBSERVACIÓN', 'RECHAZAR', 'CRÍTICO', 'SIN DATOS'] as const).map(nivel => {
                  const count = niveles[nivel] ?? 0
                  const pct = totalMes > 0 ? Math.round((count / totalMes) * 100) : 0
                  return (
                    <div key={nivel}>
                      <div className="flex items-center justify-between mb-1">
                        <span className={cn('text-xs font-medium', NIVEL_TEXT[nivel])}>{nivel}</span>
                        <span className="text-xs text-gray-500">{count.toLocaleString()} ({pct}%)</span>
                      </div>
                      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className={cn('h-full rounded-full transition-all duration-700', NIVEL_COLOR[nivel])}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
                <p className="text-xs text-gray-400 pt-1">Total: {totalMes.toLocaleString()} este mes</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function KpiCard({ icon: Icon, label, value, sub, iconColor, iconBg }: {
  icon: React.ElementType; label: string; value: string; sub: string
  iconColor: string; iconBg: string
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
          <p className="text-xs text-gray-400 mt-1">{sub}</p>
        </div>
        <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0', iconBg)}>
          <Icon className={cn('w-5 h-5', iconColor)} />
        </div>
      </div>
    </div>
  )
}

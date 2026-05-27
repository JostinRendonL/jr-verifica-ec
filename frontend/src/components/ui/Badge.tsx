import { cn } from '@/lib/utils'
import type { NivelSemaforo } from '@/types'

// ─── Semáforo badge ─────────────────────────────────────────────────────────
const SEMAFORO_CONFIG: Record<NivelSemaforo, { label: string; className: string }> = {
  'APTO':        { label: '✅ APTO',        className: 'bg-green-100 text-green-800 border-green-200' },
  'OBSERVACIÓN': { label: '🟡 OBSERVACIÓN', className: 'bg-amber-100 text-amber-800 border-amber-200' },
  'RECHAZAR':    { label: '🔴 RECHAZAR',    className: 'bg-red-100 text-red-800 border-red-200' },
  'CRÍTICO':     { label: '🚨 CRÍTICO',     className: 'bg-red-900 text-white border-red-900' },
  'SIN DATOS':   { label: '⚪ SIN DATOS',   className: 'bg-gray-100 text-gray-600 border-gray-200' },
}

interface SemaforoBadgeProps {
  nivel: NivelSemaforo
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function SemaforoBadge({ nivel, size = 'md', className }: SemaforoBadgeProps) {
  const config = SEMAFORO_CONFIG[nivel] ?? SEMAFORO_CONFIG['SIN DATOS']
  return (
    <span
      className={cn(
        'inline-flex items-center font-semibold border rounded-lg',
        size === 'sm' && 'px-2 py-0.5 text-xs',
        size === 'md' && 'px-3 py-1 text-sm',
        size === 'lg' && 'px-5 py-2 text-base',
        config.className,
        className,
      )}
    >
      {config.label}
    </span>
  )
}

// ─── Badge genérico ──────────────────────────────────────────────────────────
type Variant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'outline'

const VARIANT_CLASS: Record<Variant, string> = {
  default: 'bg-gray-100 text-gray-700 border-gray-200',
  success: 'bg-green-100 text-green-800 border-green-200',
  warning: 'bg-amber-100 text-amber-800 border-amber-200',
  danger:  'bg-red-100 text-red-800 border-red-200',
  info:    'bg-blue-100 text-blue-800 border-blue-200',
  outline: 'bg-transparent text-gray-600 border-gray-300',
}

interface BadgeProps {
  children: React.ReactNode
  variant?: Variant
  className?: string
}

export function Badge({ children, variant = 'default', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-0.5 text-xs font-medium border rounded-md',
        VARIANT_CLASS[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}

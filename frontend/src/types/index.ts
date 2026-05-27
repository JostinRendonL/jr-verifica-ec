// ─── Semáforo ──────────────────────────────────────────────────────────────
export type NivelSemaforo =
  | 'APTO'
  | 'OBSERVACIÓN'
  | 'RECHAZAR'
  | 'CRÍTICO'
  | 'SIN DATOS'

// ─── Fuentes individuales ───────────────────────────────────────────────────
export interface ResultadoBachiller {
  estado: 'ENCONTRADO' | 'NO_ENCONTRADO' | 'ERROR'
  institucion?: string
  titulo?: string
  fecha_grado?: string
  num_refrendacion?: string
}

export interface ResultadoSatje {
  estado: 'SIN_PROCESOS' | 'CON_PROCESOS' | 'ERROR'
  procesos?: Array<{
    causa: string
    rol: string
    fecha: string
    juzgado: string
    delito?: string
  }>
}

export interface ResultadoSetec {
  estado: 'ENCONTRADO' | 'NO_ENCONTRADO' | 'ERROR'
  certificaciones?: Array<{
    nombre: string
    vigente: boolean
    fecha_vencimiento?: string
  }>
}

export interface ResultadoFiscalia {
  estado: 'SIN_REGISTROS' | 'CON_REGISTROS' | 'ERROR'
  registros?: Array<{
    delito: string
    fecha: string
    ciudad?: string
    rol?: string
  }>
}

// ─── Resultado completo de una cédula ──────────────────────────────────────
export interface ResultadoVerificacion {
  cedula: string
  nombre?: string
  semaforo: NivelSemaforo
  bachiller?: ResultadoBachiller
  satje?: ResultadoSatje
  setec?: ResultadoSetec
  fiscalia?: ResultadoFiscalia
  timestamp?: string
  cached?: boolean
  hace_cuanto?: string
}

// ─── Historial ─────────────────────────────────────────────────────────────
export interface EntradaHistorial {
  id: number
  cedula: string
  nombre?: string
  semaforo: NivelSemaforo
  timestamp: string
  usuario_id?: string
  tipo: string
}

// ─── Lote ──────────────────────────────────────────────────────────────────
export interface ProgresoLote {
  job_id: string
  total: number
  procesados: number
  estado: 'pendiente' | 'procesando' | 'completado' | 'error'
  semaforos: {
    APTO: number
    'OBSERVACIÓN': number
    RECHAZAR: number
    'CRÍTICO': number
    'SIN DATOS': number
  }
  error?: string
}

// ─── Usuario ────────────────────────────────────────────────────────────────
export interface Usuario {
  id: string
  email: string
  nombre: string
  rol: 'admin' | 'operador'
  activo: boolean
  created_at: string
  total_busquedas?: number
}

// ─── Auth ────────────────────────────────────────────────────────────────────
export interface MeResponse {
  autenticado: boolean
  usuario_id?: string
  email?: string
  rol?: 'admin' | 'operador'
}

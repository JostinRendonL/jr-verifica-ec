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
  nombre?: string
  titulo?: string
  especialidad?: string
  institucion?: string
  fecha_grado?: string
  detalle?: string
}

export interface CausaSatje {
  idJuicio?: string
  materia?: string
  delito?: string
  nombreDemandado?: string
  nombreActor?: string
  fechaIngreso?: string
  juzgado?: string
  estadoJuicio?: string
}

export interface ResultadoSatje {
  estado: 'SIN_PROCESOS' | 'TIENE_PROCESOS' | 'ERROR'
  total_demandado?: number
  total_actor?: number
  delitos?: string[]
  nombre?: string
  causas_demandado?: CausaSatje[]
  causas_actor?: CausaSatje[]
  detalle?: string
}

export interface ResultadoSetec {
  estado: 'TIENE_CERTIFICADOS' | 'SIN_CERTIFICADOS' | 'ERROR'
  cursos?: string[]
  total?: number
  detalle?: string
  nombre?: string
}

export interface NoticiaFiscalia {
  delito?: string
  fecha?: string
  lugar?: string
  rol?: string
}

export interface ResultadoFiscalia {
  estado: 'SIN_ANTECEDENTES' | 'SOSPECHOSO' | 'DENUNCIANTE' | 'ERROR'
  tiene_antecedentes?: boolean
  como_sospechoso?: number
  como_denunciante?: number
  total_noticias?: number
  noticias?: NoticiaFiscalia[]
  delitos?: string[]
  detalle?: string
}

// ─── Resultado completo de una cédula ──────────────────────────────────────
export interface ResultadoVerificacion {
  cedula: string
  nombre?: string
  semaforo?: string
  bachiller?: ResultadoBachiller
  satje?: ResultadoSatje
  setec?: ResultadoSetec
  fiscalia?: ResultadoFiscalia
  fecha?: string
  _cache?: boolean
  hace_cuanto?: string
}

// ─── Historial ─────────────────────────────────────────────────────────────
export interface EntradaHistorial {
  id: number
  cedula: string
  nombre?: string
  semaforo: string
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
  creado_ts?: number
  ultimo_login?: number
}

// ─── Auth ────────────────────────────────────────────────────────────────────
export interface MeResponse {
  autenticado: boolean
  usuario_id?: string
  email?: string
  rol?: 'admin' | 'operador'
  nombre?: string
}

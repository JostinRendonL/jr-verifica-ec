import { useState } from 'react'
import { UserPlus, ToggleLeft, ToggleRight, RefreshCw, Shield, User } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/utils'
import { useAuth } from '@/hooks/useAuth'

interface UsuarioAPI {
  id: string
  email: string
  nombre: string
  rol: 'admin' | 'operador'
  activo: boolean
  creado_ts: number
  ultimo_login?: number
}

function formatTs(ts?: number) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleDateString('es-EC', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export function UsuariosPage() {
  const queryClient = useQueryClient()
  const { usuario } = useAuth()
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState({ email: '', nombre: '', rol: 'operador' })
  const [formError, setFormError] = useState('')
  const [tempPass, setTempPass] = useState('')

  const { data: usuarios = [], isLoading } = useQuery<UsuarioAPI[]>({
    queryKey: ['usuarios'],
    queryFn: async () => {
      const res = await api.get('/api/usuarios')
      return res.data
    },
  })

  const toggleActivo = useMutation({
    mutationFn: async ({ id, activo }: { id: string; activo: boolean }) => {
      const endpoint = activo ? `/api/usuarios/${id}/desactivar` : `/api/usuarios/${id}/reactivar`
      await api.post(endpoint)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['usuarios'] }),
  })

  const crearUsuario = useMutation({
    mutationFn: async () => {
      const f = new FormData()
      f.append('email', form.email)
      f.append('nombre', form.nombre)
      f.append('rol', form.rol)
      const res = await api.post<{ ok: boolean; id: string; temp_password: string }>('/api/usuarios/crear', f, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['usuarios'] })
      setTempPass(data.temp_password)
      setForm({ email: '', nombre: '', rol: 'operador' })
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error
      setFormError(msg ?? 'Error al crear usuario')
    },
  })

  if (usuario?.rol !== 'admin') {
    return (
      <div className="p-8 flex flex-col items-center justify-center min-h-64 text-gray-400 gap-2">
        <Shield className="w-10 h-10" />
        <p className="text-sm">Solo los administradores pueden ver esta sección</p>
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Gestión de Equipo</h1>
          <p className="text-sm text-gray-500 mt-1">Administra los accesos y roles de los operadores en el sistema</p>
        </div>
        <Button onClick={() => { setModalOpen(true); setTempPass(''); setFormError('') }}>
          <UserPlus className="w-4 h-4" />
          Invitar Usuario
        </Button>
      </div>

      {/* Tabla */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400 gap-3">
            <RefreshCw className="w-5 h-5 animate-spin" />
            <span className="text-sm">Cargando usuarios...</span>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Nombre</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Rol</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Creado</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Último acceso</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600 text-xs uppercase tracking-wide">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {usuarios.map(u => (
                <tr key={u.id} className={cn('hover:bg-gray-50 transition-colors', !u.activo && 'opacity-60')}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-navy-100 flex items-center justify-center flex-shrink-0">
                        <User className="w-4 h-4 text-navy-700" />
                      </div>
                      <div>
                        <p className="font-medium text-gray-800">{u.nombre}</p>
                        <p className="text-xs text-gray-500">{u.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={u.rol === 'admin' ? 'info' : u.activo ? 'success' : 'default'}>
                      {u.rol === 'admin' ? '⚙ Admin' : u.activo ? 'Operador' : 'Inactivo'}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{formatTs(u.creado_ts)}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{formatTs(u.ultimo_login)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {u.id !== usuario?.usuario_id && (
                        <button
                          title={u.activo ? 'Desactivar' : 'Reactivar'}
                          onClick={() => toggleActivo.mutate({ id: u.id, activo: u.activo })}
                          className={cn(
                            'p-1.5 rounded-md transition-colors',
                            u.activo
                              ? 'text-gray-400 hover:text-red-600 hover:bg-red-50'
                              : 'text-green-600 hover:bg-green-50',
                          )}
                        >
                          {u.activo ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 text-xs text-gray-500">
          Mostrando {usuarios.length} de {usuarios.length} usuarios
        </div>
      </div>

      {/* Modal crear usuario */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            {tempPass ? (
              // Mostrar contraseña temporal
              <div className="text-center space-y-4">
                <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mx-auto">
                  <UserPlus className="w-6 h-6 text-green-600" />
                </div>
                <h2 className="text-lg font-semibold text-gray-900">Usuario creado</h2>
                <p className="text-sm text-gray-500">
                  Comparte esta contraseña temporal con el nuevo usuario. Deberá cambiarla al iniciar sesión.
                </p>
                <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3">
                  <p className="text-xs text-gray-500 mb-1">Contraseña temporal</p>
                  <p className="font-mono font-bold text-gray-900 text-lg tracking-wider">{tempPass}</p>
                </div>
                <Button onClick={() => { setModalOpen(false); setTempPass('') }} className="w-full">
                  Entendido
                </Button>
              </div>
            ) : (
              // Formulario
              <>
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Invitar Usuario</h2>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">Nombre completo</label>
                    <input type="text" value={form.nombre}
                      onChange={e => setForm(p => ({ ...p, nombre: e.target.value }))}
                      placeholder="Carlos Mendoza"
                      className="w-full px-3 py-2.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-700" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">Email corporativo</label>
                    <input type="email" value={form.email}
                      onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                      placeholder="carlos@empresa.ec"
                      className="w-full px-3 py-2.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-700" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">Rol</label>
                    <select value={form.rol}
                      onChange={e => setForm(p => ({ ...p, rol: e.target.value }))}
                      className="w-full px-3 py-2.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-700 bg-white">
                      <option value="operador">Operador</option>
                      <option value="admin">Administrador</option>
                    </select>
                  </div>

                  {formError && (
                    <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{formError}</p>
                  )}

                  <div className="flex gap-3 pt-2">
                    <Button variant="secondary" onClick={() => setModalOpen(false)} className="flex-1">
                      Cancelar
                    </Button>
                    <Button
                      loading={crearUsuario.isPending}
                      onClick={() => { setFormError(''); crearUsuario.mutate() }}
                      className="flex-1"
                      disabled={!form.email || !form.nombre}
                    >
                      Crear usuario
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

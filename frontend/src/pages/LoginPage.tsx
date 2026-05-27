import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShieldCheck, Loader2 } from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

export function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const form = new FormData()
      form.append('usuario', email)
      form.append('clave', password)
      await api.post('/login', form, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
      navigate('/busqueda')
    } catch {
      setError('Credenciales incorrectas. Intenta de nuevo.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Panel izquierdo — Deep Navy */}
      <div className="hidden lg:flex w-[42%] bg-navy-900 flex-col justify-between p-10 relative overflow-hidden">
        {/* Fondo decorativo */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_#274470_0%,_transparent_60%)] opacity-60 pointer-events-none" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_#060d1a_0%,_transparent_70%)] pointer-events-none" />

        {/* Logo */}
        <div className="relative flex items-center gap-3">
          <div className="w-8 h-8 bg-white/10 border border-white/20 rounded-lg flex items-center justify-center">
            <ShieldCheck className="w-4 h-4 text-white" />
          </div>
          <span className="text-white font-semibold text-sm">JR Verifica EC</span>
        </div>

        {/* Tagline */}
        <div className="relative">
          <h1 className="text-white text-4xl font-bold leading-tight tracking-tight">
            Verifica a tus<br />candidatos en<br />
            <span className="text-white/80">segundos, no en días.</span>
          </h1>
          <p className="text-white/50 text-sm mt-4 leading-relaxed max-w-xs">
            Plataforma B2B de alta precisión para la validación de
            antecedentes y credenciales. Seguridad y cumplimiento
            a velocidad empresarial.
          </p>
        </div>

        {/* Footer */}
        <p className="relative text-white/30 text-xs">
          © 2024 JR Automata. Todos los derechos reservados.
        </p>
      </div>

      {/* Panel derecho — Formulario */}
      <div className="flex-1 flex items-center justify-center p-8 bg-white">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h2 className="text-2xl font-semibold text-gray-900">Iniciar Sesión</h2>
            <p className="text-sm text-gray-500 mt-1">
              Ingresa tus credenciales corporativas para acceder al portal.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Correo Electrónico Corporativo
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="usuario@empresa.com"
                required
                className={cn(
                  'w-full px-3.5 py-2.5 text-sm border rounded-lg bg-white',
                  'focus:outline-none focus:ring-2 focus:ring-navy-700 focus:border-transparent',
                  'placeholder:text-gray-400',
                  error ? 'border-red-400' : 'border-gray-300',
                )}
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-sm font-medium text-gray-700">Contraseña</label>
                <a href="/reset-password" className="text-xs text-navy-700 hover:underline">
                  ¿Recuperar contraseña?
                </a>
              </div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                className={cn(
                  'w-full px-3.5 py-2.5 text-sm border rounded-lg bg-white',
                  'focus:outline-none focus:ring-2 focus:ring-navy-700 focus:border-transparent',
                  error ? 'border-red-400' : 'border-gray-300',
                )}
              />
            </div>

            {error && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 bg-navy-700 hover:bg-navy-800 text-white font-medium py-2.5 rounded-lg transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              Ingresar al Panel →
            </button>
          </form>

          <p className="text-center text-xs text-gray-400 mt-6">
            ¿Problemas para acceder?{' '}
            <a href="mailto:soporte@jrautomata.com" className="text-navy-700 hover:underline">
              Contactar soporte técnico
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}

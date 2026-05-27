import { NavLink } from 'react-router-dom'
import { Search, FileSpreadsheet, Clock, LayoutDashboard, Users, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/hooks/useAuth'

const NAV = [
  { to: '/busqueda',       label: 'Búsqueda',        Icon: Search },
  { to: '/lote',           label: 'Lote',             Icon: FileSpreadsheet },
  { to: '/historial',      label: 'Historial',        Icon: Clock },
  { to: '/panel',          label: 'Panel de Control', Icon: LayoutDashboard },
]

const NAV_ADMIN = [
  { to: '/usuarios', label: 'Usuarios', Icon: Users },
]

export function Sidebar() {
  const { usuario } = useAuth()

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-navy-900 flex flex-col z-30">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-navy-700">
        <div className="w-7 h-7 bg-white/10 rounded-md flex items-center justify-center">
          <span className="text-white font-bold text-xs">JR</span>
        </div>
        <div>
          <p className="text-white font-semibold text-sm leading-none">JR Verifica EC</p>
          <p className="text-navy-600 text-[10px] mt-0.5 text-white/40">by JR Automata</p>
        </div>
      </div>

      {/* Nueva Verificación CTA */}
      <div className="px-3 pt-4">
        <NavLink
          to="/busqueda"
          className="flex items-center gap-2 w-full bg-white/10 hover:bg-white/15 text-white text-sm font-medium px-3 py-2 rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          Nueva Verificación
        </NavLink>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 pt-4 space-y-0.5 overflow-y-auto">
        {NAV.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-white/15 text-white font-medium'
                  : 'text-white/60 hover:text-white hover:bg-white/10',
              )
            }
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            {label}
          </NavLink>
        ))}

        {usuario?.rol === 'admin' && (
          <>
            <div className="pt-3 pb-1 px-3">
              <p className="text-white/25 text-[10px] uppercase tracking-widest font-medium">Admin</p>
            </div>
            {NAV_ADMIN.map(({ to, label, Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                    isActive
                      ? 'bg-white/15 text-white font-medium'
                      : 'text-white/60 hover:text-white hover:bg-white/10',
                  )
                }
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {label}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      {/* Footer usuario */}
      <div className="px-3 pb-4 pt-2 border-t border-navy-700 mt-2">
        <p className="text-white/70 text-xs truncate px-2">{usuario?.email ?? '...'}</p>
        <p className="text-white/30 text-[10px] px-2 capitalize">{usuario?.rol ?? ''}</p>
      </div>
    </aside>
  )
}

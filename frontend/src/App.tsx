import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import Login from '@/pages/Login'
import Overview from '@/pages/Overview'
import Approvals from '@/pages/Approvals'
import Policies from '@/pages/Policies'
import Audit from '@/pages/Audit'
import Servers from '@/pages/Servers'
import Agents from '@/pages/Agents'
import Users from '@/pages/Users'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/approvals', label: 'Approvals' },
  { to: '/policies', label: 'Policies' },
  { to: '/audit', label: 'Audit Log' },
  { to: '/servers', label: 'Servers' },
  { to: '/agents', label: 'Agents' },
  { to: '/users', label: 'Users', admin: true },
]

function Shell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="w-60 shrink-0 border-r bg-sidebar p-4 flex flex-col gap-1">
        <div
          className="mb-4 cursor-pointer px-2 text-lg font-semibold tracking-tight"
          onClick={() => navigate('/')}
        >
          🛡️ Wardenix
        </div>
        {NAV.filter((n) => !n.admin || user?.role === 'admin').map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              cn(
                'rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                  : 'text-muted-foreground hover:bg-sidebar-accent/50',
              )
            }
          >
            {n.label}
          </NavLink>
        ))}
        <div className="mt-auto border-t pt-3 text-xs text-muted-foreground">
          <div className="truncate px-2">{user?.email}</div>
          <div className="px-2 pb-2 uppercase tracking-wide">{user?.role}</div>
          <Button variant="outline" size="sm" className="w-full" onClick={logout}>
            Log out
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-8">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/policies" element={<Policies />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/servers" element={<Servers />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/users" element={<Users />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) {
    return <div className="grid min-h-screen place-items-center text-muted-foreground">Loading…</div>
  }
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/*" element={user ? <Shell /> : <Navigate to="/login" replace />} />
    </Routes>
  )
}

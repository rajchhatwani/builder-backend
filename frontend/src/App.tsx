import { useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './components/AuthProvider'
import { Layout } from './components/Layout'
import { PasswordForm } from './components/PasswordForm'
import { ProjectsSidebar, SECTIONS, type Section } from './components/Sidebar'
import { UiProvider } from './components/Ui'
import { AccountPage } from './pages/AccountPage'
import { AdminApp, parseAdminSection, type AdminSection } from './pages/admin/AdminApp'
import { LoginPage } from './pages/LoginPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ProjectWorkspace } from './pages/ProjectWorkspace'

type Route =
  | { page: 'projects' }
  | { page: 'account' }
  | { page: 'admin'; section: AdminSection }
  | { page: 'project'; projectId: string; section: Section }

/** Routes live in the URL hash (#/p/<id>/<section>), so reloads and back/forward keep your place. */
function parseHash(hash: string): Route {
  if (hash.startsWith('#/admin')) return { page: 'admin', section: parseAdminSection(hash) }
  if (hash.startsWith('#/account')) return { page: 'account' }
  const match = hash.match(/^#\/p\/([^/]+)(?:\/([a-z]+))?/)
  if (!match) return { page: 'projects' }
  const section = SECTIONS.find((s) => s.id === match[2])?.id ?? 'overview'
  return { page: 'project', projectId: match[1], section }
}

/** Shown instead of the app when an administrator handed out a temporary password. */
function MustChangePassword() {
  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h2>Choose a new password</h2>
        <p className="muted">Your password was set by an administrator. Replace it to continue.</p>
        <PasswordForm />
      </div>
    </div>
  )
}

/** Everything that needs a signed-in customer. */
function CustomerApp({ route }: { route: Route }) {
  const { state } = useAuth()
  if (state.status === 'loading') return <p className="empty-state">Loading…</p>
  if (state.status === 'anon') return <LoginPage />
  if (state.user.must_change_password) return <MustChangePassword />

  if (route.page === 'project') {
    return <ProjectWorkspace projectId={route.projectId} section={route.section} />
  }
  return (
    <Layout sidebar={<ProjectsSidebar />}>
      {route.page === 'account' ? <AccountPage /> : <ProjectsPage />}
    </Layout>
  )
}

function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return (
    <UiProvider>
      {route.page === 'admin' ? (
        <AdminApp section={route.section} />
      ) : (
        <AuthProvider>
          <CustomerApp route={route} />
        </AuthProvider>
      )}
    </UiProvider>
  )
}

export default App

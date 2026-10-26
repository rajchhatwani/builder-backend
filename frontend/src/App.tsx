import { useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './components/AuthProvider'
import { Layout } from './components/Layout'
import { PasswordForm } from './components/PasswordForm'
import { QuotaPrompt } from './components/QuotaPrompt'
import { ProjectsSidebar, SECTIONS, type Section } from './components/Sidebar'
import { UiProvider } from './components/Ui'
import { AccountPage } from './pages/AccountPage'
import { AdminApp, parseAdminSection, type AdminSection } from './pages/admin/AdminApp'
import { LoginPage } from './pages/LoginPage'
import { OrgPlanPage } from './pages/OrgPlanPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ProjectWorkspace } from './pages/ProjectWorkspace'

type Route =
  | { page: 'projects' }
  | { page: 'account' }
  | { page: 'org-plan'; slug: string }
  | { page: 'admin'; section: AdminSection }
  | { page: 'project'; projectId: string; section: Section }

/** Routes live in the URL hash (#/p/<id>/<section>), so reloads and back/forward keep your place. */
function parseHash(hash: string): Route {
  if (hash.startsWith('#/admin')) return { page: 'admin', section: parseAdminSection(hash) }
  if (hash.startsWith('#/account')) return { page: 'account' }
  // Only the Plan tab of the org console exists so far; #/org/<slug> lands on it too.
  const org = hash.match(/^#\/org\/([^/?]+)/)
  if (org) return { page: 'org-plan', slug: decodeURIComponent(org[1]) }
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
    return (
      <>
        <ProjectWorkspace projectId={route.projectId} section={route.section} />
        <QuotaPrompt />
      </>
    )
  }
  return (
    <Layout sidebar={<ProjectsSidebar />}>
      {route.page === 'account' ? (
        <AccountPage />
      ) : route.page === 'org-plan' ? (
        <OrgPlanPage slug={route.slug} />
      ) : (
        <ProjectsPage />
      )}
      <QuotaPrompt />
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

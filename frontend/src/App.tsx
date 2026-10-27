import { useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './components/AuthProvider'
import { Layout } from './components/Layout'
import { PasswordForm } from './components/PasswordForm'
import { OrgLockedPrompt } from './components/OrgLockedPrompt'
import { OrgMfaPrompt } from './components/OrgMfaPrompt'
import { QuotaPrompt } from './components/QuotaPrompt'
import { ProjectsSidebar, SECTIONS, type Section } from './components/Sidebar'
import { UiProvider } from './components/Ui'
import { AccountPage } from './pages/AccountPage'
import { AdminApp, parseAdminSection, type AdminSection } from './pages/admin/AdminApp'
import { LoginPage } from './pages/LoginPage'
import { InvitationsPage } from './pages/InvitationsPage'
import { OrgConsole, type OrgTab } from './pages/OrgConsole'
import { ProjectsPage } from './pages/ProjectsPage'
import { ProjectWorkspace } from './pages/ProjectWorkspace'

type Route =
  | { page: 'projects' }
  | { page: 'account' }
  | { page: 'org'; slug: string; tab: OrgTab }
  | { page: 'invitations'; token?: string }
  | { page: 'sso-complete' }
  | { page: 'admin'; section: AdminSection }
  | { page: 'project'; projectId: string; section: Section }

const ORG_TABS: OrgTab[] = ['people', 'invites', 'projects', 'plan', 'audit', 'sso', 'policies']

/** Routes live in the URL hash (#/p/<id>/<section>), so reloads and back/forward keep your place. */
function parseHash(hash: string): Route {
  if (hash.startsWith('#/admin')) return { page: 'admin', section: parseAdminSection(hash) }
  if (hash.startsWith('#/account')) return { page: 'account' }
  if (hash.startsWith('#/invitations')) return { page: 'invitations' }
  // The API sends a finished SSO sign-in here with the refresh cookie already set (§4.2).
  if (hash.startsWith('#/sso/complete')) return { page: 'sso-complete' }
  const invite = hash.match(/^#\/invite\/([^/?]+)/)
  if (invite) return { page: 'invitations', token: decodeURIComponent(invite[1]) }
  // #/org/<slug> → People (§8.1); /invites, /projects, /plan, /audit, /sso, /policies are the other tabs.
  const org = hash.match(/^#\/org\/([^/?]+)(?:\/([a-z]+))?/)
  if (org) {
    const tab = ORG_TABS.find((t) => t === org[2]) ?? 'people'
    return { page: 'org', slug: decodeURIComponent(org[1]), tab }
  }
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

/** The session was resumed from the cookie the SSO callback set; move on to the projects. */
function SsoComplete() {
  useEffect(() => {
    window.location.replace('#/')
  }, [])
  return <p className="empty-state">Signing you in…</p>
}

/** Everything that needs a signed-in customer. */
function CustomerApp({ route }: { route: Route }) {
  const { state } = useAuth()
  if (state.status === 'loading') return <p className="empty-state">Loading…</p>
  if (state.status === 'anon') return <LoginPage />
  if (state.user.must_change_password) return <MustChangePassword />
  if (route.page === 'sso-complete') return <SsoComplete />

  if (route.page === 'project') {
    return (
      <>
        <ProjectWorkspace projectId={route.projectId} section={route.section} />
        <QuotaPrompt />
        <OrgLockedPrompt />
        <OrgMfaPrompt />
      </>
    )
  }
  return (
    <Layout sidebar={<ProjectsSidebar />}>
      {route.page === 'account' ? (
        <AccountPage />
      ) : route.page === 'org' ? (
        <OrgConsole slug={route.slug} tab={route.tab} />
      ) : route.page === 'invitations' ? (
        <InvitationsPage key={route.token ?? ''} token={route.token} />
      ) : (
        <ProjectsPage />
      )}
      <QuotaPrompt />
      <OrgLockedPrompt />
      <OrgMfaPrompt />
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

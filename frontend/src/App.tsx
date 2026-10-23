import { useEffect, useState } from 'react'
import { Layout } from './components/Layout'
import { ProjectsSidebar, SECTIONS, type Section } from './components/Sidebar'
import { UiProvider } from './components/Ui'
import { ProjectsPage } from './pages/ProjectsPage'
import { ProjectWorkspace } from './pages/ProjectWorkspace'

type Route = { page: 'projects' } | { page: 'project'; projectId: string; section: Section }

/** Routes live in the URL hash (#/p/<id>/<section>), so reloads and back/forward keep your place. */
function parseHash(hash: string): Route {
  const match = hash.match(/^#\/p\/([^/]+)(?:\/([a-z]+))?/)
  if (!match) return { page: 'projects' }
  const section = SECTIONS.find((s) => s.id === match[2])?.id ?? 'overview'
  return { page: 'project', projectId: match[1], section }
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
      {route.page === 'project' ? (
        <ProjectWorkspace projectId={route.projectId} section={route.section} />
      ) : (
        <Layout sidebar={<ProjectsSidebar />}>
          <ProjectsPage />
        </Layout>
      )}
    </UiProvider>
  )
}

export default App

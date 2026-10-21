import { useState } from 'react'
import { Layout } from './components/Layout'
import { ProjectDetailPage } from './pages/ProjectDetailPage'
import { ProjectsPage } from './pages/ProjectsPage'
import type { Project } from './api/types'

function App() {
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)

  return (
    <Layout>
      {selectedProject ? (
        <ProjectDetailPage project={selectedProject} onBack={() => setSelectedProject(null)} />
      ) : (
        <ProjectsPage onOpenProject={setSelectedProject} />
      )}
    </Layout>
  )
}

export default App

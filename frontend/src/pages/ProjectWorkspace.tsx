import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  AuthConfig,
  Entity,
  KeycloakConfig,
  PaymentsConfig,
  StorageConfig,
  Project,
  ProjectRole,
  Relation,
  ValidationIssue,
} from '../api/types'
import { AuthChecks } from '../components/AuthChecks'
import { AuthConfigPanel } from '../components/AuthConfigPanel'
import { AuthCustomFieldsPanel } from '../components/AuthCustomFieldsPanel'
import { DataModelPanel } from '../components/DataModelPanel'
import { GeneratePanel } from '../components/GeneratePanel'
import { KeycloakPanel } from '../components/KeycloakPanel'
import { PaymentsPanel } from '../components/PaymentsPanel'
import { StoragePanel } from '../components/StoragePanel'
import { Layout } from '../components/Layout'
import { MembersDialog } from '../components/MembersDialog'
import { OverviewPanel, sectionForIssue } from '../components/OverviewPanel'
import { AuthorizationPanel } from '../components/AuthorizationPanel'
import { DeploymentPanel } from '../components/DeploymentPanel'
import { DocumentsPanel } from '../components/DocumentsPanel'
import { ObservabilityPanel } from '../components/ObservabilityPanel'
import { ProjectSidebar, ProjectsSidebar, type Section } from '../components/Sidebar'

interface ProjectWorkspaceProps {
  projectId: string
  section: Section
}

function SubTabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="tab-bar">
      {tabs.map((t) => (
        <button key={t.id} className="tab-btn" aria-selected={value === t.id} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

function PageTitle({ title, children }: { title: string; children: string }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{children}</p>
      </div>
    </div>
  )
}

export function ProjectWorkspace({ projectId, section }: ProjectWorkspaceProps) {
  const [project, setProject] = useState<Project | null>(null)
  const [missing, setMissing] = useState(false)
  const [entities, setEntities] = useState<Entity[]>([])
  const [relations, setRelations] = useState<Relation[]>([])
  const [roles, setRoles] = useState<ProjectRole[]>([])
  const [auth, setAuth] = useState<AuthConfig | null>(null)
  const [keycloak, setKeycloak] = useState<KeycloakConfig | null>(null)
  const [payments, setPayments] = useState<PaymentsConfig | null>(null)
  const [storage, setStorage] = useState<StorageConfig | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[] | null>(null)
  const [generationCount, setGenerationCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [sharing, setSharing] = useState(false)
  // Bumped on every reload so the generate panel drops results for an outdated model.
  const [modelVersion, setModelVersion] = useState(0)

  const [authTab, setAuthTab] = useState<'settings' | 'fields'>('settings')

  const load = useCallback(async () => {
    try {
      const [proj, entityPage, relationPage, rolePage, authConfig, keycloakConfig, paymentsConfig, storageConfig, report, generations] = await Promise.all([
        api.getProject(projectId),
        api.listEntities(projectId, 200, 0),
        api.listRelations(projectId, 200, 0),
        api.listRoles(projectId, 200, 0),
        api.getAuthConfig(projectId).catch(() => null),
        api.getKeycloak(projectId).catch(() => null),
        api.getPayments(projectId).catch(() => null),
        api.getStorage(projectId).catch(() => null),
        api.validateProject(projectId).catch(() => null),
        api.listGenerations(projectId, 1, 0),
      ])
      setProject(proj)
      setEntities(entityPage.items)
      setRelations(relationPage.items)
      setRoles(rolePage.items)
      setAuth(authConfig)
      setKeycloak(keycloakConfig)
      setPayments(paymentsConfig)
      setStorage(storageConfig)
      setIssues(report ? report.issues : null)
      setGenerationCount(generations.total)
      setModelVersion((v) => v + 1)
    } catch {
      setMissing(true)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    setProject(null)
    setLoading(true)
    setMissing(false)
    load()
  }, [load])

  // Auth, role and permission panels save by themselves, so re-check whenever the user moves on.
  useEffect(() => {
    if (!loading) load()
  }, [section])

  if (missing) {
    return (
      <Layout sidebar={<ProjectsSidebar />}>
        <div className="card empty-hero">
          <h2>We can't find this project</h2>
          <p>It may have been deleted, or the backend is not reachable.</p>
          <a className="button" href="#/">
            Back to projects
          </a>
        </div>
      </Layout>
    )
  }

  if (!project) {
    return (
      <Layout sidebar={<ProjectsSidebar />}>
        <p className="empty-state">Loading…</p>
      </Layout>
    )
  }

  const problems: Partial<Record<Section, number>> = {}
  for (const issue of issues ?? []) {
    const s = sectionForIssue(issue)
    problems[s] = (problems[s] ?? 0) + 1
  }

  const keycloakOn = auth?.provider === 'keycloak' && auth.enabled
  const paymentsOn = payments?.enabled === true
  const storageOn = storage?.enabled === true

  return (
    <Layout
      sidebar={
        <ProjectSidebar
          project={project}
          section={section}
          problems={problems}
          on={{ keycloak: keycloakOn, payments: paymentsOn, storage: storageOn }}
          onShare={() => setSharing(true)}
        />
      }
    >
      {section === 'overview' && (
        <OverviewPanel
          projectId={project.id}
          entityCount={entities.length}
          authEnabled={auth?.enabled ?? false}
          keycloakOn={keycloakOn}
          keycloakSaved={keycloak !== null}
          paymentsOn={paymentsOn}
          paymentsSaved={payments !== null}
          storageOn={storageOn}
          storageSaved={storage !== null}
          roleCount={roles.length}
          issues={issues}
          generationCount={generationCount}
        />
      )}

      {section === 'model' && (
        <DataModelPanel
          projectId={project.id}
          entities={entities}
          relations={relations}
          loading={loading}
          onChanged={load}
        />
      )}

      {section === 'auth' && (
        <>
          <PageTitle title="Authentication">How people sign up and sign in to the backend you generate.</PageTitle>
          <SubTabs
            tabs={[
              { id: 'settings', label: 'Settings' },
              { id: 'fields', label: 'Extra sign-up fields' },
            ]}
            value={authTab}
            onChange={setAuthTab}
          />
          <AuthChecks projectId={project.id} checkKey={authTab} />
          {authTab === 'settings' && <AuthConfigPanel projectId={project.id} />}
          {authTab === 'fields' && (
            <AuthCustomFieldsPanel projectId={project.id} keycloak={keycloakOn} />
          )}
        </>
      )}

      {section === 'keycloak' && (
        <>
          <PageTitle title="Keycloak">
            Single sign-on, sign-in with Google or Microsoft, multi-factor sign-in and an admin console for your users.
          </PageTitle>
          <KeycloakPanel
            project={project}
            provider={auth?.provider ?? 'builtin'}
            issues={issues}
            onChanged={load}
          />
        </>
      )}

      {section === 'payments' && (
        <>
          <PageTitle title="Payments">
            Take card payments through a hosted checkout, with refunds, an audit trail and servers sized for your traffic.
          </PageTitle>
          <PaymentsPanel
            project={project}
            entities={entities}
            roles={roles}
            authEnabled={auth?.enabled ?? false}
            issues={issues}
            onChanged={load}
          />
        </>
      )}

      {section === 'storage' && (
        <>
          <PageTitle title="File uploads">
            Accept files of any type, scanned for malware before they are stored in S3 or a MinIO-compatible bucket, with
            role-based access and an audit trail.
          </PageTitle>
          <StoragePanel
            project={project}
            roles={roles}
            authEnabled={auth?.enabled ?? false}
            issues={issues}
            onChanged={load}
          />
        </>
      )}

      {section === 'access' && (
        <>
          <PageTitle title="Authorization">
            Decide who may do what with your data: roles and permissions, or rules over attributes and policies.
          </PageTitle>
          <AuthorizationPanel
            projectId={project.id}
            entities={entities}
            roles={roles}
            keycloak={keycloakOn}
            authEnabled={auth?.enabled ?? false}
            onRolesChanged={() => api.listRoles(project.id, 200, 0).then((p) => setRoles(p.items))}
            onChanged={load}
          />
        </>
      )}

      {section === 'observability' && (
        <>
          <PageTitle title="Observability">
            Traces, metrics and trace-correlated logs from your generated backend, through OpenTelemetry, with secrets kept out.
          </PageTitle>
          <ObservabilityPanel projectId={project.id} onChanged={load} />
        </>
      )}

      {section === 'documents' && (
        <>
          <PageTitle title="Documents">
            Generate invoices, receipts, statements, certificates and more as PDFs: ten ready-made templates you can edit, with totals recomputed on the server.
          </PageTitle>
          <DocumentsPanel projectId={project.id} onChanged={load} />
        </>
      )}

      {section === 'deployment' && (
        <>
          <PageTitle title="Deploy">
            GitHub Actions pipelines and Terraform that put your backend on AWS, Azure or Google Cloud, with no stored cloud credentials.
          </PageTitle>
          <DeploymentPanel projectId={project.id} onChanged={load} />
        </>
      )}

      {section === 'generate' && (
        <>
          <PageTitle title="Generate">Check your model, preview the files, and download the finished backend.</PageTitle>
          <GeneratePanel project={project} modelVersion={modelVersion} />
        </>
      )}
      <MembersDialog
        open={sharing}
        projectId={project.id}
        projectName={project.name}
        onClose={() => setSharing(false)}
      />
    </Layout>
  )
}

import { Suspense, lazy, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, ApiError } from '../api/client'
import type {
  AuthConfig,
  Entity,
  KeycloakConfig,
  Organization,
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
import { IntegrationsPanel } from '../components/IntegrationsPanel'
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
import { useQueryClient } from '@tanstack/react-query'
import { shellV2Enabled } from '../shell/flag'
import { railProblems } from '../shell/home/homeLogic'
import { statusKey, useProjectStatus } from '../shell/home/useProjectStatus'
import { ShellV2 } from '../shell/ShellV2'
import { MachinesPage } from '../shell/machines/MachinesPage'
import type { AnySection } from '../shell/pages'
import { pageFlagOn } from '../shell/pageFlag'

// F1-6A pages: own chunks, kept out of the main bundle
const SettingsPage = lazy(() => import('../shell/behavior/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const SeedPage = lazy(() => import('../shell/behavior/SeedPage').then((m) => ({ default: m.SeedPage })))
const FormsPreviewPage = lazy(() => import('../shell/forms/FormsPreviewPage').then((m) => ({ default: m.FormsPreviewPage })))
const NotificationsPage = lazy(() => import('../shell/notifications/NotificationsPage').then((m) => ({ default: m.NotificationsPage })))
const TimelinePage = lazy(() => import('../shell/timeline/TimelinePage').then((m) => ({ default: m.TimelinePage })))
const HooksPage = lazy(() => import('../shell/behavior/HooksPage').then((m) => ({ default: m.HooksPage })))
const HomePage = lazy(() => import('../shell/home/HomePage').then((m) => ({ default: m.HomePage })))
const RulesPage = lazy(() => import('../shell/rules/RulesPage').then((m) => ({ default: m.RulesPage })))
// F2-2 / F2-3 pages: own chunks. The first four replace an existing panel and sit behind their own flag (ui.<name>=v2).
const PaymentsFormPage = lazy(() => import('../shell/connect/ConfigPages').then((m) => ({ default: m.PaymentsFormPage })))
const StorageFormPage = lazy(() => import('../shell/connect/ConfigPages').then((m) => ({ default: m.StorageFormPage })))
const ObservabilityFormPage = lazy(() => import('../shell/connect/ConfigPages').then((m) => ({ default: m.ObservabilityFormPage })))
const DeploymentFormPage = lazy(() => import('../shell/connect/ConfigPages').then((m) => ({ default: m.DeploymentFormPage })))
const WebhooksPage = lazy(() => import('../shell/connect/WebhooksPage').then((m) => ({ default: m.WebhooksPage })))
const ProvidersPage = lazy(() => import('../shell/connect/ProvidersPage').then((m) => ({ default: m.ProvidersPage })))
const JobsPage = lazy(() => import('../shell/operate/JobsPage').then((m) => ({ default: m.JobsPage })))
const WorkersPage = lazy(() => import('../shell/operate/WorkersPage').then((m) => ({ default: m.WorkersPage })))
const WorkflowsPage = lazy(() => import('../shell/operate/WorkflowsPage').then((m) => ({ default: m.WorkflowsPage })))
const HistoryPage = lazy(() => import('../shell/behavior/HistoryPage').then((m) => ({ default: m.HistoryPage })))

/** The organization that owns this project (one call: projects carry `organization_id`). */
function useProjectOrg(organizationId: string | null | undefined): Organization | null {
  const [found, setFound] = useState<Organization | null>(null)
  useEffect(() => {
    if (!organizationId) return
    let cancelled = false
    api
      .listOrgs()
      .then((page) => !cancelled && setFound(page.items.find((o) => o.id === organizationId) ?? null))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [organizationId])
  return found?.id === organizationId ? found : null
}

interface ProjectWorkspaceProps {
  projectId: string
  section: AnySection
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

/** Old shell by default; the new one when flag ui.shell=v2 is on. The panels inside are the same either way. */
function Frame({
  v2,
  children,
  ...props
}: {
  v2: boolean
  project: Project
  section: AnySection
  problems: Partial<Record<AnySection, number>>
  on: Partial<Record<Section, boolean>>
  onShare: () => void
  org: Organization | null
  children: ReactNode
}) {
  if (v2) return <ShellV2 {...props}>{children}</ShellV2>
  return <Layout sidebar={<ProjectSidebar {...props} />}>{children}</Layout>
}

export function ProjectWorkspace({ projectId, section }: ProjectWorkspaceProps) {
  const [project, setProject] = useState<Project | null>(null)
  const [missing, setMissing] = useState(false)
  // A failed project request that is not "not found" (network, 5xx, unreadable body): shown with a Retry button.
  const [loadError, setLoadError] = useState<string | null>(null)
  // 423: the project's org is waiting for deletion (the global prompt explains and links to it).
  const [locked, setLocked] = useState(false)
  // 403 org_mfa_required: the org requires two-factor (the global prompt explains the way out).
  const [needsMfa, setNeedsMfa] = useState(false)
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
  const org = useProjectOrg(project?.organization_id)
  // New shell only: one status call feeds the rail badges and the Home board (shared Query cache).
  const v2 = shellV2Enabled()
  const queryClient = useQueryClient()
  const statusQuery = useProjectStatus(projectId, v2)

  // Newest load wins: a slow answer to an older load must not overwrite (or break) a newer one.
  const loadSeq = useRef(0)
  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    // Secondary requests: one failing only empties its own panel, never the whole page.
    const soft = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null)
    try {
      const [proj, entityPage, relationPage, rolePage, authConfig, keycloakConfig, paymentsConfig, storageConfig, report, generations] = await Promise.all([
        api.getProject(projectId),
        soft(api.listEntities(projectId, 200, 0)),
        soft(api.listRelations(projectId, 200, 0)),
        soft(api.listRoles(projectId, 200, 0)),
        soft(api.getAuthConfig(projectId)),
        soft(api.getKeycloak(projectId)),
        soft(api.getPayments(projectId)),
        soft(api.getStorage(projectId)),
        soft(api.validateProject(projectId)),
        soft(api.listGenerations(projectId, 1, 0)),
      ])
      if (seq !== loadSeq.current) return
      setProject(proj)
      setEntities(entityPage?.items ?? [])
      setRelations(relationPage?.items ?? [])
      setRoles(rolePage?.items ?? [])
      setAuth(authConfig)
      setKeycloak(keycloakConfig)
      setPayments(paymentsConfig)
      setStorage(storageConfig)
      setIssues(report ? report.issues : null)
      setGenerationCount(generations?.total ?? 0)
      setModelVersion((v) => v + 1)
      setLocked(false)
      setNeedsMfa(false)
      setMissing(false)
      setLoadError(null)
    } catch (err) {
      if (seq !== loadSeq.current) return
      // Only "this project is not there / not yours / locked" is a missing project; anything else is transient.
      const gone = err instanceof ApiError && (err.status === 404 || err.status === 403 || err.status === 423)
      if (gone) {
        setLocked(err.code === 'org_deletion_pending')
        setNeedsMfa(err.code === 'org_mfa_required')
        setMissing(true)
        setLoadError(null)
      } else {
        setLoadError(err instanceof ApiError ? err.message : 'The backend could not be reached')
      }
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [projectId])

  const retry = () => {
    setLoadError(null)
    setLoading(true)
    void load()
  }

  useEffect(() => {
    setProject(null)
    setLoading(true)
    setMissing(false)
    setLoadError(null)
    load()
  }, [load])

  // Anything that reloads the project data (panel saves, moving between sections) also refreshes the status.
  useEffect(() => {
    if (v2 && modelVersion > 0) void queryClient.invalidateQueries({ queryKey: statusKey(projectId) })
  }, [v2, modelVersion, projectId, queryClient])

  // Auth, role and permission panels save by themselves, so re-check whenever the user moves on.
  useEffect(() => {
    if (!loading) load()
  }, [section])

  if (missing) {
    return (
      <Layout sidebar={<ProjectsSidebar />}>
        <div className="card empty-hero">
          <h2>
            {locked
              ? "This project's organization is scheduled for deletion"
              : needsMfa
                ? "This project's organization requires two-factor authentication"
                : "We can't find this project"}
          </h2>
          <p>
            {locked
              ? 'It is locked until the deletion date, and then deleted with its projects. An owner can cancel the deletion from the organization page.'
              : needsMfa
                ? 'Turn on two-factor in your account, then sign in again with your code.'
                : 'It may have been deleted, or the backend is not reachable.'}
          </p>
          <a className="button" href="#/">
            Back to projects
          </a>
        </div>
      </Layout>
    )
  }

  const errorBanner = loadError ? (
    <div className="card" role="alert" data-testid="load-error">
      <p>We could not load this project: {loadError}</p>
      <button type="button" onClick={retry}>
        Retry
      </button>
    </div>
  ) : null

  if (!project) {
    if (errorBanner) {
      return (
        <Layout sidebar={<ProjectsSidebar />}>{errorBanner}</Layout>
      )
    }
    return (
      <Layout sidebar={<ProjectsSidebar />}>
        <p className="empty-state">Loading…</p>
      </Layout>
    )
  }

  let problems: Partial<Record<AnySection, number>> = {}
  if (v2) {
    problems = railProblems(statusQuery.data)
  } else {
    for (const issue of issues ?? []) {
      const s = sectionForIssue(issue)
      problems[s] = (problems[s] ?? 0) + 1
    }
  }

  const keycloakOn = auth?.provider === 'keycloak' && auth.enabled
  const paymentsOn = payments?.enabled === true
  const storageOn = storage?.enabled === true

  return (
    <Frame
      v2={v2}
      project={project}
      section={section}
      problems={problems}
      on={{ keycloak: keycloakOn, payments: paymentsOn, storage: storageOn }}
      onShare={() => setSharing(true)}
      org={org}
    >
      {errorBanner}
      {section === 'overview' && v2 && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <HomePage projectId={project.id} />
        </Suspense>
      )}
      {section === 'overview' && !v2 && (
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

      {section === 'machines' && <MachinesPage projectId={project.id} />}
      {section === 'rules' && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <RulesPage projectId={project.id} />
        </Suspense>
      )}
      {section === 'hooks' && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <HooksPage projectId={project.id} />
        </Suspense>
      )}
      {section === 'timeline' && v2 && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <TimelinePage projectId={project.id} />
        </Suspense>
      )}
      {section === 'notifications' && v2 && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <NotificationsPage projectId={project.id} />
        </Suspense>
      )}
      {section === 'forms' && v2 && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <FormsPreviewPage />
        </Suspense>
      )}
      {section === 'seed' && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <SeedPage projectId={project.id} />
        </Suspense>
      )}
      {(section === 'settings' || section === 'history') && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          {section === 'settings' ? <SettingsPage projectId={project.id} /> : <HistoryPage projectId={project.id} />}
        </Suspense>
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

      {section === 'payments' && v2 && pageFlagOn('payments') && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <PaymentsFormPage projectId={project.id} />
        </Suspense>
      )}
      {section === 'payments' && !(v2 && pageFlagOn('payments')) && (
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

      {section === 'storage' && v2 && pageFlagOn('storage') && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <StorageFormPage projectId={project.id} />
        </Suspense>
      )}
      {section === 'storage' && !(v2 && pageFlagOn('storage')) && (
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

      {section === 'observability' && v2 && pageFlagOn('observability') && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <ObservabilityFormPage projectId={project.id} />
        </Suspense>
      )}
      {section === 'observability' && !(v2 && pageFlagOn('observability')) && (
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

      {section === 'deployment' && v2 && pageFlagOn('deployment') && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          <DeploymentFormPage projectId={project.id} />
        </Suspense>
      )}
      {section === 'deployment' && !(v2 && pageFlagOn('deployment')) && (
        <>
          <PageTitle title="Deploy">
            GitHub Actions pipelines and Terraform that put your backend on AWS, Azure or Google Cloud, with no stored cloud credentials.
          </PageTitle>
          <DeploymentPanel projectId={project.id} onChanged={load} />
        </>
      )}

      {v2 && (section === 'webhooks' || section === 'providers' || section === 'jobs' || section === 'workers' || section === 'workflows') && (
        <Suspense fallback={<p className="empty-state">Loading…</p>}>
          {section === 'webhooks' && <WebhooksPage projectId={project.id} />}
          {section === 'providers' && <ProvidersPage projectId={project.id} />}
          {section === 'jobs' && <JobsPage projectId={project.id} />}
          {section === 'workers' && <WorkersPage projectId={project.id} />}
          {section === 'workflows' && <WorkflowsPage projectId={project.id} />}
        </Suspense>
      )}

      {section === 'integrations' && <IntegrationsPanel projectId={project.id} />}

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
    </Frame>
  )
}

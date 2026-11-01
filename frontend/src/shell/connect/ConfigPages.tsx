import { useCallback } from 'react'
import { api } from '../../api/client'
import type { DeploymentWrite, ObservabilityWrite, PaymentsWrite, StorageWrite } from '../../api/types'
import type { JsonSchema } from '../../forms'
import payments from '../../forms/schemas/payments.json'
import storage from '../../forms/schemas/storage.json'
import observability from '../../forms/schemas/observability.json'
import deployment from '../../forms/schemas/deployment.json'
import { ConfigFormPage } from './ConfigFormPage'

type Cfg = Record<string, unknown>
const asCfg = (x: unknown) => x as Cfg

const switchNote = (what: string) => (c: Cfg) => (
  <>
    {what} is currently <strong>{c.enabled ? 'switched on' : 'switched off'}</strong>. Saving here keeps that as it is. To switch
    it on or off (it shows what will change first), use the classic panel.
  </>
)

export function PaymentsFormPage({ projectId }: { projectId: string }) {
  const load = useCallback(async () => asCfg(await api.getPayments(projectId)), [projectId])
  const save = useCallback(async (b: Cfg) => asCfg(await api.putPayments(projectId, b as unknown as PaymentsWrite)), [projectId])
  return (
    <ConfigFormPage title="Payments" flag="payments" schema={payments as JsonSchema} load={load} save={save} status={switchNote('Payments')}
      intro="Provider, payable entity, currencies, who may do what, scale and webhook security. API keys are never entered here: they are environment variables of the generated project." />
  )
}

export function StorageFormPage({ projectId }: { projectId: string }) {
  const load = useCallback(async () => asCfg(await api.getStorage(projectId)), [projectId])
  const save = useCallback(async (b: Cfg) => asCfg(await api.putStorage(projectId, b as unknown as StorageWrite)), [projectId])
  return (
    <ConfigFormPage title="File uploads" flag="storage" schema={storage as JsonSchema} load={load} save={save} status={switchNote('File uploads')}
      intro="Where files are kept, which types and sizes are allowed, quotas, and who may upload, download and delete." />
  )
}

export function ObservabilityFormPage({ projectId }: { projectId: string }) {
  const load = useCallback(async () => asCfg(await api.getObservability(projectId)), [projectId])
  const save = useCallback(async (b: Cfg) => asCfg(await api.putObservability(projectId, b as unknown as ObservabilityWrite)), [projectId])
  return (
    <ConfigFormPage title="Observability" flag="observability" schema={observability as JsonSchema} load={load} save={save} versioned
      intro="Traces and metrics for the generated API (OpenTelemetry): sampling, which paths to leave out, and which extra keys to hide." />
  )
}

export function DeploymentFormPage({ projectId }: { projectId: string }) {
  const load = useCallback(async () => asCfg(await api.getDeployment(projectId)), [projectId])
  const save = useCallback(async (b: Cfg) => asCfg(await api.putDeployment(projectId, b as unknown as DeploymentWrite)), [projectId])
  return (
    <ConfigFormPage title="Deploy" flag="deployment" schema={deployment as JsonSchema} load={load} save={save} versioned
      intro="Cloud, region and one row per environment. The classic panel also previews the sizing plan for these settings." />
  )
}

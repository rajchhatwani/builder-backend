import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { SettingsSection } from '../../../patterns'
import { Alert, Badge, Card, Row, Skeleton, Stack } from '../../../ui'
import { deliveryLimits } from '../../../validators'
import { deliveryApi, filesOptions } from '../api/delivery'
import { guidedKeys, useGuidedWorkspaces } from '../api/guided'
import { ConfirmAction, DeliveryError, ProjectLink, TextAction } from './DeliveryControls'
import { GuidedLoadError } from './GuidedFeedback'

type Change =
  | { kind: 'create'; name: string }
  | { kind: 'checkpoint'; id: string; name: string }
  | { kind: 'rollback'; id: string; checkpoint: string }
  | { kind: 'discard'; id: string }

export function WorkspacePanel({ projectId, workspaceId, write }: { projectId: string; workspaceId?: string | null; write: boolean }) {
  const t = useT()
  const client = useQueryClient()
  const workspaces = useGuidedWorkspaces(projectId, true)
  const change = useMutation({
    mutationFn: async (action: Change): Promise<unknown> => {
      switch (action.kind) {
        case 'create': return deliveryApi.createWorkspace(projectId, action.name)
        case 'checkpoint': return deliveryApi.checkpoint(projectId, action.id, action.name)
        case 'rollback': return deliveryApi.rollback(projectId, action.id, action.checkpoint)
        case 'discard': return deliveryApi.discardWorkspace(projectId, action.id)
      }
    },
    onSettled: () => client.invalidateQueries({ queryKey: guidedKeys.workspaces(projectId) }),
  })
  return <SettingsSection title={t('build.workspaces')} description={t('build.workspaceIntro')}>
    <DeliveryError error={change.error} reload={() => { change.reset(); void workspaces.refetch() }} />
    {workspaces.isPending ? <Skeleton lines={3} />
      : workspaces.isError ? <GuidedLoadError error={workspaces.error} label={t('build.workspaceError')} retry={() => void workspaces.refetch()} />
      : workspaces.data.length === 0 ? <p>{t('build.noWorkspaces')}</p> : workspaces.data.map(workspace => <Card key={workspace.id}>
        <Stack>
          <Row><h3>{workspace.name}</h3><Badge>{workspace.state}</Badge>{workspace.id === workspaceId && <Badge tone="info">{t('build.runWorkspace')}</Badge>}</Row>
          <p>{t('build.workspaceVersion', { branch: workspace.branch, version: workspace.spec_seq })}</p>
          {workspace.cleanup_incomplete && <Alert tone="warning">{t('build.cleanup')}</Alert>}
          <Row>
            <ProjectLink projectId={projectId} section="see" search={{ workspace: workspace.id }}>{t('build.openPreview')}</ProjectLink>
            {write && workspace.state === 'active' && <TextAction title={t('build.checkpoint')} label={t('build.checkpointName')}
              max={deliveryLimits.checkpoint} pending={change.isPending}
              onSubmit={name => change.mutateAsync({ kind: 'checkpoint', id: workspace.id, name })} />}
            {write && (workspace.state === 'active' || workspace.cleanup_incomplete) && <ConfirmAction
              label={t('common.discard')} title={t('build.discardTitle', { name: workspace.name })} description={t('build.discardBody')}
              pending={change.isPending} onConfirm={() => change.mutateAsync({ kind: 'discard', id: workspace.id })} />}
          </Row>
          {workspace.checkpoints?.map(checkpoint => <Row key={checkpoint.id} className="v2-spread">
            <Stack gap={1}>
              <strong>{checkpoint.label}</strong>
              <span>{t('build.checkpointFacts', { version: checkpoint.spec_seq, date: formatGuidedDate(checkpoint.created_at) })}</span>
              <span>{t(checkpoint.has_data_snapshot ? 'build.snapshot' : 'build.noSnapshot')}</span>
            </Stack>
            {write && workspace.state === 'active' && <ConfirmAction label={t('build.rollback')}
              title={t('build.rollbackTitle', { name: checkpoint.label })} description={t(checkpoint.has_data_snapshot ? 'build.rollbackData' : 'build.rollbackSpec')}
              pending={change.isPending} onConfirm={() => change.mutateAsync({ kind: 'rollback', id: workspace.id, checkpoint: checkpoint.id })} />}
          </Row>)}
        </Stack>
      </Card>)}
    {write && <Row><TextAction title={t('build.createWorkspace')} label={t('build.workspaceName')} max={deliveryLimits.workspace}
      pending={change.isPending} onSubmit={name => change.mutateAsync({ kind: 'create', name })} /></Row>}
  </SettingsSection>
}

export function formatGuidedDate(value: string | null) {
  return value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—'
}

export function DraftFiles({ projectId, workspace, run }: { projectId: string; workspace: string; run: string }) {
  const t = useT()
  const files = useQuery(filesOptions(projectId, workspace))
  return <SettingsSection title={t('build.files')}>
    {files.isPending ? <Skeleton /> : files.isError
      ? <GuidedLoadError error={files.error} retry={() => void files.refetch()} label={t('build.fileError')} />
      : files.data.length === 0 ? <p>{t('build.noFiles')}</p>
      : <Stack>{files.data.map(file => <Row key={file.path} className="v2-spread">
        <ProjectLink projectId={projectId} section="code" search={{ run, workspace, file: file.path }}>{file.path}</ProjectLink>
        <Badge>{t(file.editable ? 'build.custom' : 'common.readOnly')}</Badge>
      </Row>)}</Stack>}
  </SettingsSection>
}

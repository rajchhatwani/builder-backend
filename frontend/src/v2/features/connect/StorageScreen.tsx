import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { openInEditor } from '../../patterns/editorLink'
import { SettingsSection } from '../../patterns'
import { Alert, Button, CodeBlock, Skeleton, Stack } from '../../ui'
import { connectBucket, connectLimits, connectMime, connectPrefix, connectRegion, validators } from '../../validators'
import { statusOptions, storageOptions, useStorageWrite } from './api/connect'
import type { ConnectProps, StorageConfig, StorageWrite } from './api/connect'
import { useFields } from './components/Fields'
import type { EditorProps, Group } from './components/Fields'
import { IssueList, RetryAlert, SettingsPage } from './components/SettingsPage'
import type { Model } from './components/SettingsPage'
import { checked, list, number, optionalNumber, text } from './state/draft'
import type { SettingsDraft } from './state/draft'

const roleActions = ['upload', 'share', 'read', 'read_all', 'delete', 'delete_all', 'operate'] as const
export const storageDefaults: StorageWrite = {
  backend: 's3', bucket: '', region: 'eu-west-1', key_prefix: 'uploads', allowed_types: [], max_file_mb: 25,
  user_quota_mb: null, uploads_per_hour: 60, download_mode: 'proxy', allow_inline_images: false,
  roles: { upload: [], share: [], read: [], read_all: [], delete: [], delete_all: [], operate: [] },
  security: { audit_retention_days: 2555, audit_ip: true, rescan_after_days: 30, scan_timeout_seconds: 120 },
}

const mimeGroups = {
  images: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
  pdf: ['application/pdf'],
  office: [
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  ],
  text: ['text/plain', 'text/csv'],
  archives: ['application/zip', 'application/gzip'],
}

function toWrite(draft: SettingsDraft): StorageWrite {
  return {
    backend: text(draft, 'backend') as StorageWrite['backend'],
    bucket: text(draft, 'bucket').trim(),
    region: text(draft, 'region').trim() || null,
    key_prefix: text(draft, 'key_prefix').trim(),
    allowed_types: list(draft, 'allowed_types'),
    max_file_mb: number(draft, 'max_file_mb'),
    user_quota_mb: optionalNumber(draft, 'user_quota_mb'),
    uploads_per_hour: number(draft, 'uploads_per_hour'),
    download_mode: text(draft, 'download_mode') as StorageWrite['download_mode'],
    allow_inline_images: checked(draft, 'allow_inline_images'),
    roles: {
      upload: list(draft, 'roles.upload'), share: list(draft, 'roles.share'), read: list(draft, 'roles.read'),
      read_all: list(draft, 'roles.read_all'), delete: list(draft, 'roles.delete'), delete_all: list(draft, 'roles.delete_all'),
      operate: list(draft, 'roles.operate'),
    },
    security: {
      audit_retention_days: number(draft, 'security.audit_retention_days'), audit_ip: checked(draft, 'security.audit_ip'),
      rescan_after_days: number(draft, 'security.rescan_after_days'), scan_timeout_seconds: number(draft, 'security.scan_timeout_seconds'),
    },
  }
}

function useStorageGroups(props: EditorProps & { model?: Model }): Group[] {
  const t = useT()
  const { draft, guided, model } = props
  const fields = useFields(props, 'storage')
  const { input, numeric, choice, toggle, values } = fields
  const s3 = text(draft, 'backend') === 's3'
  const translated = (options: string[]) => options.map(value => ({
    value, label: t('connect.storage.options.' + value), description: t('connect.storage.options.' + value + 'Help'),
  }))
  return [
    { title: t('connect.storage.provider'), fields: [
      choice('backend', translated(['s3', 'minio']), { cards: true }),
    ] },
    { title: t('connect.storage.bucket'), description: t('connect.storage.bucketHelp'), fields: [
      input('bucket', [validators.length(connectLimits.bucket), connectBucket], {
        maxLength: connectLimits.bucket, placeholder: t('connect.storage.bucketExample'),
      }),
      input('region', [validators.length(connectLimits.region), ...(s3 ? [connectRegion] : [])], { maxLength: connectLimits.region }),
      input('key_prefix', [validators.length(connectLimits.prefix), connectPrefix], { maxLength: connectLimits.prefix }),
    ] },
    { title: t('connect.storage.limits'), fields: [
      numeric('max_file_mb', 1, 1024),
      numeric('user_quota_mb', 1, 10_000_000, true),
      numeric('uploads_per_hour', 1, 10_000),
      values('allowed_types', connectMime, { placeholder: t('connect.storage.mimeExample'),
        quickAdd: guided ? Object.entries(mimeGroups).map(([group, values]) => ({ label: t('connect.storage.mime.' + group), values })) : undefined }),
    ], extra: guided && <Alert>{t('connect.storage.malware')}</Alert> },
    { title: t('connect.storage.download'), fields: [
      choice('download_mode', translated(['proxy', 'presigned']), { cards: true }), toggle('allow_inline_images'),
    ] },
    fields.permissions(roleActions, model?.auth?.roles?.map(role => ({ value: role.name, label: role.label || role.name })) ?? []),
    { title: t('connect.storage.security'), disclosure: t('connect.storage.securityDisclosure'), fields: [
      numeric('security.audit_retention_days', 365, 36_500), numeric('security.rescan_after_days', 1, 365),
      numeric('security.scan_timeout_seconds', 5, 600), toggle('security.audit_ip'),
    ] },
  ]
}

function fileFields(model?: Model) {
  return (model?.entities ?? []).flatMap(entity => entity.fields
    .filter(field => field.type === 'file').map(field => entity.name + '.' + field.name))
}

function StorageIssues({ projectId }: { projectId: string }) {
  const t = useT()
  const status = useQuery(statusOptions(projectId))
  if (status.isPending) return <Skeleton label={t('common.loading')} />
  if (status.isError) return <RetryAlert message={t('connect.storage.issuesError')} error={status.error} retry={() => void status.refetch()} />
  return <IssueList issues={(status.data?.issues ?? []).filter(issue => issue.path.startsWith('storage') || issue.code === 'storage_required')} />
}

function StorageExtras({ projectId, saved, model }: { projectId: string; saved: StorageConfig | null; model?: Model }) {
  const t = useT()
  const files = fileFields(model)
  const s3 = saved?.backend === 's3'
  return <Stack>
    <SettingsSection title={t('connect.storage.modelFiles')}>
      {files.length ? <Stack gap={1}>{files.map(path => <p key={path}><code>{t('common.serverText', { text: path })}</code></p>)}</Stack>
        : <p className="v2-muted">{t('connect.storage.noFiles')}</p>}
      <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'model' }}>{t('connect.openModel')}</Link></Button>
    </SettingsSection>
    {saved && <>
      <SettingsSection title={t('connect.storage.pipeline')}>
        <ol><li>{t('connect.storage.flowUpload')}</li><li>{t('connect.storage.flowCheck')}</li><li>{t('connect.storage.flowScan')}</li>
          <li>{t('connect.storage.flowStore')}</li><li>{t('connect.storage.options.' + saved.download_mode)}</li></ol>
        <p>{t('connect.storage.lifecycle', {
          timeout: saved.security.scan_timeout_seconds, rescan: saved.security.rescan_after_days, retention: saved.security.audit_retention_days,
        })}</p>
      </SettingsSection>
      <SettingsSection title={t('connect.storage.setup')} description={t('connect.storage.setupHelp')}>
        <CodeBlock code={['APP_ENV', s3 ? 'STORAGE_REGION' : 'STORAGE_ENDPOINT_URL',
          'STORAGE_ACCESS_KEY_ID', 'STORAGE_SECRET_ACCESS_KEY'].join('\n')} label={t('connect.environment')} />
        <p>{t(s3 ? 'connect.storage.awsSetup' : 'connect.storage.compatibleSetup')}</p>
        <p>{t('connect.storage.maintenance')}</p>
        {saved.enabled && <Stack>
          <Button asChild><Link {...openInEditor({ projectId, path: 'deploy/storage/STORAGE.md' })}>{t('connect.storage.openGuide')}</Link></Button>
          {s3 && saved.bucket && <Button asChild>
            <Link {...openInEditor({ projectId, path: 'deploy/storage/iam-policy.json' })}>{t('connect.storage.openPolicy')}</Link>
          </Button>}
        </Stack>}
      </SettingsSection>
    </>}
  </Stack>
}

export default function StorageScreen(props: ConnectProps) {
  const read = useQuery(storageOptions(props.projectId))
  const write = useStorageWrite(props.projectId)
  return <SettingsPage {...props} kind="storage" defaults={storageDefaults} read={read} write={write} useGroups={useStorageGroups} toWrite={toWrite}
    fileFields={fileFields} review={() => <StorageIssues projectId={props.projectId} />} extras={(saved, model) => <StorageExtras projectId={props.projectId} saved={saved} model={model} />} />
}

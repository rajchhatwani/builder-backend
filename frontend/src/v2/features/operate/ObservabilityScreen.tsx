import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { observationValidation } from '../../validators/operate'
import { Alert, Disclosure, EmptyState, Field, Row, Stack, Tabs, Textarea } from '../../ui'
import { canWrite, observationIssues, observationOptions, useObservationWrite } from './api/operate'
import type { ObservabilityWrite, OperateProps } from './api/operate'
import { Issues, LoadState, OperateScreen, RoleNotice, SectionLink, useOperateSearch } from './components/Common'
import { EnableAction, VersionedSettings } from './components/VersionedSettings'
import { obsSchema, withDefaults } from './state/schemas'

export default function ObservabilityScreen(props: OperateProps) {
  return <OperateScreen title={'operate.obs.title'} lead="operate.obs.lead"><Observation {...props} /></OperateScreen>
}

function Observation(props: OperateProps) {
  const { projectId: id } = props
  const t = useT()
  const { search, change } = useOperateSearch()
  const query = useQuery(observationOptions(id))
  const issues = useQuery(observationIssues(id))
  const mutation = useObservationWrite(id)
  const read = query.data
  const writable = canWrite(props)
  const guided = search.tab === 'guided'
  return <Stack gap={4}>
    <Tabs label={t('operate.obs.tabs')} value={guided ? 'guided' : 'form'} onChange={tab => change({ tab })} items={[
      { id: 'form', label: t('operate.settings'), content: null },
      { id: 'guided', label: t('operate.obs.guide'), content: read && <Stack>
        <Disclosure label={t('operate.obs.collect')}><p>{t('operate.obs.collectHelp')}</p></Disclosure>
        <Disclosure label={t('operate.obs.protect')}><Stack><p>{t('operate.obs.protectHelp')}</p>
          <p>{t('operate.data', { value: read.redacted_keys.join(', ') })}</p></Stack></Disclosure>
        <Disclosure label={t('operate.obs.stack')}><Stack gap={1}>
          <p>{t('operate.obs.stackHelp')}</p><p>{t('operate.obs.versions', {
            collector: '0.163.2', jaeger: '2.22.0', prometheus: '3.15.1', sdk: '1.45.1', instrumentation: '0.66b1',
          })}</p>
        </Stack></Disclosure>
      </Stack> },
    ]} />
    <RoleNotice {...props} />
    {!read ? <LoadState error={query.error} retry={query.refetch} /> : <>
      <Issues issues={issues.data?.issues} error={issues.error} retry={issues.refetch} />
      <VersionedSettings title={t('operate.obs.configuration')} schema={obsSchema}
        base={withDefaults(obsSchema, read) as Record<string, unknown>} version={read.version} updatedAt={read.updated_at}
        readOnly={!writable} error={mutation.error} pending={mutation.isPending} saved={mutation.isSuccess}
        loadError={query.isRefetchError ? query.error : undefined}
        validate={value => observationValidation(value, t)}
        fieldOverride={({ path, value, readOnly, error, id, onChange }, touch) => {
          const name = path[0]
          if (!guided || name !== 'exclude_paths' && name !== 'extra_redact_keys') return null
          return <LineField id={id} label={t(name === 'exclude_paths' ? 'operate.obs.paths' : 'operate.obs.keys')}
            value={value as string[]} readOnly={readOnly} error={error} onChange={onChange} touch={touch} />
        }}
        reload={async () => { const result = await query.refetch(); if (result.isSuccess) mutation.reset(); return result.isSuccess }}
        save={(value, version) => mutation.mutateAsync({ ...value, expected_version: version } as ObservabilityWrite)}
        aside={value => {
          const rps = Number(value.expected_rps)
          const ratio = rps > 0 ? Math.max(.01, Math.min(1, Math.floor(200 / (rps * 4) * 100) / 100)) : 1
          return <Stack gap={2}>
            <p>{t('operate.obs.service', { name: read.default_service_name })}</p>
            <Disclosure label={t('operate.obs.sampling')} open={guided || undefined}><Stack gap={1}>
              <p>{t('operate.obs.rpsHelp')}</p>
              <p>{t('operate.obs.advice', { ratio: Math.round(ratio * 100) })}</p>
              <p>{t('operate.obs.savedAdvice', { ratio: Math.round(read.recommended_sample_ratio * 100) })}</p>
              {Number(value.sample_ratio) > ratio && <Alert tone="warning">{t('operate.obs.over')}</Alert>}
            </Stack></Disclosure>
          </Stack>
        }}>
        {(current, enable) => !current.enabled && <EmptyState title={t('operate.obs.off')} description={t('operate.obs.offHint')}
          action={writable && <EnableAction onClick={enable} />} />}
      </VersionedSettings>
    </>}
    <Row><SectionLink id={id} section="traces" label={t('operate.obs.traces')} />
      <SectionLink id={id} section="metrics" label={t('operate.metrics.title')} /></Row>
  </Stack>
}

function LineField({ id, label, value, readOnly, error, onChange, touch }: {
  id: string; label: string; value: string[]; readOnly?: boolean; error?: string; onChange: (value: string[]) => void; touch: () => void
}) {
  const t = useT()
  const [raw, setRaw] = useState<string>()
  return <Field id={id} label={label} error={error && t('operate.data', { value: error })} hint={t('operate.obs.lineHelp')}>
    {attrs => <Textarea {...attrs} readOnly={readOnly} value={raw ?? (value ?? []).join('\n')}
      onBlur={() => { setRaw(undefined); touch() }} onChange={event => {
        setRaw(event.target.value)
        onChange(event.target.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean))
      }} />}
  </Field>
}

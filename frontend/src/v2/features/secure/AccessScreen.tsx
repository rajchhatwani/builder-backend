import { useReducer, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, PageHeader, SettingsSection } from '../../patterns'
import { Alert, DesktopOnlyCard, Stack, Tabs } from '../../ui'
import { accessOptions, controlsApi, weakeningDetails } from './api/controls'
import { codeOf, useSecureMutation } from './api/security'
import { AccessModel } from './AccessModel'
import { AccessPermissions } from './AccessPermissions'
import { AccessRoles } from './AccessRoles'
import { AccessPolicies } from './AccessPolicies'
import { AccessCoverage, AccessSimulator } from './AccessTools'
import { reviewReducer, type AuthorizationEdit } from './state/access'
import { canEdit, LoadFailure, SecureLoading, SecureRole, useSecureSearch, WriteNotice, type SecureProps } from './SecureForm'

export default function AccessScreen(props: SecureProps) {
  const { projectId: id } = props
  const t = useT()
  const [desktop, setDesktop] = useState(() => !document.body.clientWidth || document.body.clientWidth >= 700)
  const { search, tab: changeTab } = useSecureSearch()
  const query = useQuery(accessOptions(id))
  const [review, dispatch] = useReducer(reviewReducer, null)
  const editable = canEdit(props)
  const write = useSecureMutation(id, async ({ edit, confirm }: { edit: AuthorizationEdit; confirm: boolean }) => {
    if (edit.kind === 'settings') return controlsApi.putAuthorization(id, edit.settings, confirm)
    if (!edit.existing) return controlsApi.createRole(id, edit.values, confirm)
    const { name: _name, ...changes } = edit.values
    return controlsApi.updateRole(edit.existing.id, changes, confirm)
  })
  const data = query.data
  const settings = data?.settings
  const tabIds = settings?.model === 'rbac' ? ['model', 'roles', 'permissions'] : ['model', 'roles', 'policies', 'simulator', 'coverage']
  const selected = tabIds.find(value => value === search.tab) ?? 'model'
  const reload = () => {
    dispatch({ type: 'close' })
    write.reset()
    void query.refetch()
  }
  async function save(edit: AuthorizationEdit, confirm = false) {
    try {
      await write.mutateAsync({ edit, confirm })
      dispatch({ type: 'close' })
      if (edit.kind === 'settings' && edit.settings.model !== settings?.model) changeTab('model')
      return true
    } catch (error) {
      if (codeOf(error) === 'access_weakened') {
        dispatch({ type: 'confirm', edit })
        return false
      }
      dispatch({ type: 'close' })
      throw error
    }
  }
  const submit = async (edit: AuthorizationEdit, removePolicies = false) => {
    if (removePolicies) {
      dispatch({ type: 'review', edit })
      return true
    }
    try {
      await save(edit)
      return true
    } catch (error) {
      return edit.kind === 'settings' && codeOf(error) === 'conflict'
    }
  }

  return <Stack gap={4} ref={element => {
    if (!element || typeof ResizeObserver === 'undefined') return
    const viewport = document.body
    const observer = new ResizeObserver(() => setDesktop(viewport.clientWidth >= 700))
    observer.observe(viewport)
    return () => observer.disconnect()
  }}>
    <PageHeader title={t('authorization.title')} description={t('authorization.lead')} />
    <SecureRole {...props} />
    {query.isPending ? <SecureLoading label={t('common.loading')} /> : query.isError ?
      <LoadFailure error={query.error} message={t('authorization.loadError')} retry={reload} /> : data && settings && <>
        <Stack className="v2-phone-only"><DesktopOnlyCard />
          <SettingsSection title={t('authorization.savedSettings')}>
            <p>{t('authorization.currentModel', { model: t(`authorization.model_${settings.model}`) })}</p>
            {settings.version === 0 && !data.roles.length && !data.spec.entities.length && <p>{t('authorization.modelEmpty')}</p>}
          </SettingsSection>
        </Stack>
        {desktop && <Stack className="v2-phone-hidden" gap={4}>
          {!review && codeOf(write.error) !== 'access_weakened' && <WriteNotice error={write.error}
            message={t('authorization.saveError')} saved={write.isSuccess ? t('common.saved') : undefined} reload={reload} />}
          {!!data.issues.length && <SettingsSection title={t('authorization.issues', { count: data.issues.length })}>
            <Stack gap={2}>{data.issues.map((issue, index) => <Alert key={index} tone="warning">
              {t('authorization.issue', { message: issue.message, path: issue.path, code: issue.code })}
            </Alert>)}</Stack>
          </SettingsSection>}
          <Tabs label={t('authorization.title')} value={selected} onChange={changeTab} items={tabIds.map(tab => ({
            id: tab, label: t(`authorization.tab_${tab}`), content: tab === selected ? (() => {
              const shared = { id, ...data, editable, busy: write.isPending, submit }
              switch (tab) {
                case 'roles': return <AccessRoles {...shared} error={write.error} />
                case 'permissions': return <AccessPermissions {...shared} />
                case 'policies': return <AccessPolicies {...shared} error={write.error} />
                case 'simulator': return <AccessSimulator {...shared} />
                case 'coverage': return <AccessCoverage id={id} />
                default: return <AccessModel {...shared} />
              }
            })() : null,
          }))} />
        </Stack>}
      </>}
    {desktop && review && <ConfirmDestructive key={review.confirm ? 'confirm' : 'review'} open pending={write.isPending} onOpenChange={open => { if (!open) dispatch({ type: 'close' }) }}
      title={t(review.removePolicies ? 'authorization.switchBack' : 'authorization.weaken')}
      description={t(review.removePolicies ? 'authorization.switchBackHelp' : 'authorization.weakenHelp')}
      action={t(review.removePolicies ? 'authorization.switchDelete' : 'authorization.saveAnyway')}
      onConfirm={async () => {
        if (!await save(review.edit, review.confirm)) throw new Error('review_required')
      }}>
      <ul>{weakeningDetails(write.error).map((item, index) => <li key={index}>{t('authorization.gaining', item)}</li>)}</ul>
    </ConfirmDestructive>}
  </Stack>
}

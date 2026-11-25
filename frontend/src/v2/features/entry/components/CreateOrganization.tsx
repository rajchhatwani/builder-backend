import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import { Button, Dialog, Input, Stack, useToast } from '../../../ui'
import { checkProjectSlug, projectLimits, validators } from '../../../validators'
import { entryKeys, useEntryAction } from '../api/entry'
import { projectsApi } from '../api/projects'
import { EntryProblem } from './EntryFrame'
import { valueOf } from './fields'
import { authProblem } from './messages'

export function CreateOrganization({ userId }: { userId: string }) {
  const t = useT()
  const navigate = useNavigate()
  const client = useQueryClient()
  const toast = useToast()
  const action = useEntryAction()
  const [open, setOpen] = useState(false)

  return <Dialog title={t('projectList.newOrg')} trigger={<Button>{t('projectList.newOrg')}</Button>} open={open}
    onOpenChange={next => { if (!action.isPending) { action.reset(); setOpen(next) } }} closeLabel={t('projectCreate.cancel')}>
    <Stack>
      {action.isError && <EntryProblem error={action.error} message={t(authProblem(action.error))} />}
      <Form fields={[
        { name: 'name', label: t('projectList.orgName'), validate: [validators.required, validators.length(projectLimits.name)],
          control: attributes => <Input {...attributes} maxLength={projectLimits.name} /> },
        { name: 'slug', label: t('projectCreate.slug'), validate: [validators.length(projectLimits.slug), checkProjectSlug],
          control: attributes => <Input {...attributes} maxLength={projectLimits.slug} /> },
      ]} pending={action.isPending} submitLabel={t('projectList.createOrg')} onSubmit={values => action.run(async () => {
        const org = await projectsApi.createOrganization({
          name: valueOf(values, 'name').trim(), slug: valueOf(values, 'slug').trim() || undefined,
        })
        void client.invalidateQueries({ queryKey: entryKeys.organizations(userId) })
        toast({ title: t('projectList.orgCreated', { name: org.name }), tone: 'success' })
        setOpen(false)
        void navigate({ to: '/org/$slug', params: { slug: org.slug } })
      })} />
    </Stack>
  </Dialog>
}

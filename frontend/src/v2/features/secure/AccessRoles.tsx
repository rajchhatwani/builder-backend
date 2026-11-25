import { useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, SettingsSection } from '../../patterns'
import { Button, Dialog, EmptyState, Grid, Pagination, Row, Table } from '../../ui'
import { accessChecks } from '../../validators'
import type { AccessEditorProps } from './AccessModel'
import { controlsApi, editableError, type ProjectRole } from './api/controls'
import { fieldErrors, useSecureMutation } from './api/security'
import { checkField, duplicateValue, numberField, pickField, readNumber, readText, textField, useSecureSearch, WriteNotice } from './SecureForm'

const columns = ['name', 'label', 'is_default', 'self_assignable', 'invite_only', 'inherits_from', 'position', 'actions'] as const
const sortable = ['name', 'label', 'position'] as const
const pageSize = 10

export function AccessRoles({ id, spec, roles, editable, busy, submit, error }: AccessEditorProps & { error: unknown }) {
  const t = useT()
  const [editing, setEditing] = useState<ProjectRole | 'new'>()
  const { search, page: setPage, filter } = useSecureSearch()
  const sort = sortable.find(key => key === search.view?.split('-')[0]) ?? 'position'
  const descending = search.view?.endsWith('-desc') ?? false
  const sorted = [...roles].sort((left, right) => {
    const compared = sort === 'position' ? left.position - right.position : left[sort].localeCompare(right[sort])
    return (descending ? -1 : 1) * compared || left.name.localeCompare(right.name)
  })
  const pages = Math.ceil(sorted.length / pageSize)
  const page = Math.min(search.page ?? 1, Math.max(1, pages))
  const remove = useSecureMutation(id, controlsApi.deleteRole)
  const role = editing === 'new' ? undefined : editing
  const keycloak = spec.auth?.enabled && spec.auth.provider === 'keycloak'
  const label = (key: typeof columns[number]) => t(`authorization.${key}`)
  const choices = [{ value: '_none', label: t('authorization.none') }, ...roles.filter(item => item.id !== role?.id)
    .map(item => ({ value: item.name, label: item.label }))]
  const fields = [
    textField('name', label('name'), role?.name, role ? { locked: true } : { required: true, max: 60, checks: [
      accessChecks.name, value => duplicateValue(value.trim(), roles.map(item => item.name)),
    ] }),
    textField('label', label('label'), role?.label, { required: true, max: 100 }),
    checkField('is_default', label('is_default'), role?.is_default ?? false),
    ...!keycloak || role?.self_assignable ? [checkField('self_assignable', label('self_assignable'), role?.self_assignable ?? false)] : [],
    ...!keycloak || role?.invite_only ? [checkField('invite_only', label('invite_only'), role?.invite_only ?? false)] : [],
    pickField('inherits_from', label('inherits_from'), role?.inherits_from ?? '_none',
      role?.inherits_from && !choices.some(item => item.value === role.inherits_from) ?
        [...choices, { value: role.inherits_from, label: role.inherits_from }] : choices),
    numberField('position', label('position'), role?.position ?? 0, { min: 0, max: 2147483647, digits: 10, integer: true }),
  ]
  const detail = editableError(error)
  const flag = (value: boolean) => t(value ? 'authorization.yes' : 'authorization.no')
  return <SettingsSection title={t('authorization.tab_roles')}>
    <WriteNotice error={remove.error} message={editableError(remove.error) ? t('secure.fieldError', { message: editableError(remove.error) ?? '' }) : t('authorization.roleDeleteError')} saved={remove.isSuccess ? t('common.saved') : undefined}
      reload={() => remove.reset()} />
    {!!sorted.length && editable && <Row><Button variant="primary" onClick={() => setEditing('new')}>{t('authorization.newRole')}</Button></Row>}
    {sorted.length ? <>
      <Table label={t('authorization.tab_roles')} columns={columns.map(key => ({
        id: key, label: label(key), sort: sort === key ? descending ? 'descending' : 'ascending' : undefined,
        heading: sortable.some(value => value === key) ? <Button variant="ghost" onClick={() =>
          filter({ view: key + (sort === key && !descending ? '-desc' : '-asc') })}>{label(key)}</Button> : undefined,
      }))} rows={sorted.slice((page - 1) * pageSize, page * pageSize).map(item => ({
        id: item.id, cells: [item.name, item.label, flag(item.is_default), flag(item.self_assignable), flag(item.invite_only),
          item.inherits_from ?? t('authorization.none'), t('authorization.score', { score: item.position }), editable && <Row>
            <Button onClick={() => setEditing(item)} disabled={busy}>{t('authorization.edit')}</Button>
            <ConfirmDestructive trigger={<Button variant="danger" disabled={busy || remove.isPending}>{t('authorization.delete')}</Button>}
              title={t('authorization.deleteRole', { name: item.name })} description={t('authorization.deleteRoleHelp')}
              action={t('authorization.delete')} pending={remove.isPending} onConfirm={() => remove.mutateAsync(item.id)} />
          </Row>],
      }))} />
      {pages > 1 && <Pagination label={t('authorization.tab_roles')} page={page} pages={pages} onChange={setPage} />}
    </> : <EmptyState title={t('authorization.noRoles')} action={editable ?
      <Button onClick={() => setEditing('new')}>{t('authorization.newRole')}</Button> :
      <Button onClick={() => filter({ view: undefined })}>{t('authorization.tab_roles')}</Button>} />}
    {editing && <Dialog open title={t(role ? 'authorization.editRole' : 'authorization.newRole')} onOpenChange={open => { if (!open) setEditing(undefined) }}>
      <Form fields={fields} pending={busy} submitLabel={t('common.save')} serverErrors={fieldErrors(error)}
        formError={error && !Object.keys(fieldErrors(error)).length
          ? detail ? t('secure.fieldError', { message: detail }) : t('authorization.roleSaveError') : undefined}
        layout={controls => <Grid>{fields.map(field => controls[field.name])}</Grid>}
        onSubmit={data => {
          const inherits = readText(data, 'inherits_from')
          void submit({ kind: 'role', existing: role, values: {
            name: role?.name ?? readText(data, 'name'), label: readText(data, 'label'), position: readNumber(data, 'position'),
            is_default: data.has('is_default'), self_assignable: data.has('self_assignable'), invite_only: data.has('invite_only'),
            inherits_from: inherits === '_none' ? null : inherits,
          } }).then(accepted => { if (accepted) setEditing(undefined) })
        }} />
    </Dialog>}
  </SettingsSection>
}

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { AuthConfig, AuthCustomField, AuthCustomFieldCreate, AuthCustomFieldType } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, SettingsSection } from '../../patterns'
import { Alert, Button, Dialog, EmptyState, Field, Grid, Input, Pagination, Row, Select, Stack, Table } from '../../ui'
import { orderedNumber, signInEnumChoices, signInFieldName, signInLine, signInObject } from '../../validators'
import { fieldErrors, fieldPageSize, fieldsOptions, securityApi, useSecureMutation } from './api/security'
import { canEdit, checkField, LoadFailure, numberField, pickField, readLines, readNullable, readNumber, readOptionalNumber,
  readText, SecureLoading, textField, useSecureSearch, WriteNotice } from './SecureForm'
import type { SecureProps } from './SecureForm'

const fieldTypes: AuthCustomFieldType[] = ['string', 'text', 'integer', 'float', 'boolean', 'date', 'datetime', 'email', 'phone', 'url', 'enum']
const lengthTypes = new Set(['string', 'text', 'email', 'phone', 'url'])
const numericTypes = new Set(['integer', 'float'])
const reserved = ['id', 'email', 'phone', 'password', 'password_hash', 'roles', 'role_source', 'is_active', 'email_verified_at', 'phone_verified_at',
  'last_login_at', 'created_at', 'updated_at', 'deleted_at', 'tenant_id', 'tenant_name', 'invite_token']
const tokenReserved = ['sub', 'iss', 'aud', 'exp', 'iat', 'nbf', 'jti', 'typ', 'azp', 'sid', 'acr', 'scope',
  'email_verified', 'given_name', 'family_name', 'preferred_username', 'resource_access', 'realm_access', 'organization',
  'auth_time', 'session_state', 'allowed_origins']

function FieldEditor({ id, current, locked, close, saved }: { id: string; current?: AuthCustomField; locked: boolean; close: () => void; saved: () => void }) {
  const t = useT()
  const l = (key: string) => t('secure.fields.' + key)
  const [type, setType] = useState<AuthCustomFieldType>(current?.type ?? 'string')
  const len = lengthTypes.has(type)
  const num = numericTypes.has(type)
  const enumerated = type === 'enum'
  const write = useSecureMutation(id, (body: AuthCustomFieldCreate) => {
    if (!current) return securityApi.createField(id, body)
    const { label, required, unique, indexed, min_length, max_length, min_value, max_value, default_value, enum_values, extra, position } = body
    return securityApi.updateField(current.id, { label, required, unique, indexed, min_length, max_length, min_value, max_value,
      default_value, enum_values, extra, position })
  })
  const fields = [
    textField('name', l('name'), current?.name, { max: 100, required: !current, locked: Boolean(current),
      checks: [signInFieldName(locked ? [...reserved, ...tokenReserved] : reserved)] }),
    pickField('type', l('type'), type, fieldTypes.map(value => ({ value, label: l(value) })), {
      locked: Boolean(current), change: value => setType(value as AuthCustomFieldType),
    }),
    textField('label', l('label'), current?.label, { required: true, max: 100, checks: [signInLine] }),
    checkField('required', l('required'), current?.required ?? false),
    ...(!locked || current?.unique ? [checkField('unique', l('unique'), current?.unique ?? false)] : []),
    checkField('indexed', l('indexed'), current?.indexed ?? false),
    ...(len ? [
      numberField('min_length', l('min_length'), current?.min_length, { min: 0, max: 10000, integer: true }, false),
      numberField('max_length', l('max_length'), current?.max_length, { min: 1, max: 10000, integer: true }, false,
        (value, data) => orderedNumber(readText(data, 'min_length'), value)),
    ] : []),
    ...(num ? [
      numberField('min_value', l('min_value'), current?.min_value, {}, false),
      numberField('max_value', l('max_value'), current?.max_value, {}, false,
        (value, data) => orderedNumber(readText(data, 'min_value'), value)),
    ] : []),
    ...(enumerated ? [textField('enum_values', l('enum_values'), current?.enum_values?.join('\n'), { area: true,
      required: true, checks: [signInEnumChoices], hint: l('enumHelp') })] : []),
    textField('default_value', l('default_value'), current?.default_value, { max: 500 }),
    numberField('position', l('position'), current?.position ?? 0, { min: 0, max: 2147483647, integer: true, digits: 10 }),
    textField('extra', l('extra'), current?.extra && JSON.stringify(current.extra, null, 2), { area: true, checks: [signInObject] }),
  ]
  return <Dialog open onOpenChange={open => { if (!open && !write.isPending) close() }}
    title={l(current ? 'edit' : 'new')} description={l('dialogDescription')}>
    <Stack>
      <WriteNotice error={write.error} message={l('saveError')} reload={close} />
      <Form fields={fields} layout={controls => <Grid>{Object.values(controls)}</Grid>} pending={write.isPending}
        serverErrors={fieldErrors(write.error)} submitLabel={t('common.save')} actions={<Button onClick={close}
          disabled={write.isPending}>{t('common.cancel')}</Button>} onSubmit={data => {
          const extra = readNullable(data, 'extra')
          const body: AuthCustomFieldCreate = {
            name: current?.name ?? readText(data, 'name'), type, label: readText(data, 'label'),
            required: data.has('required'), unique: data.has('unique'), indexed: data.has('indexed'),
            min_length: len ? readOptionalNumber(data, 'min_length') : null, max_length: len ? readOptionalNumber(data, 'max_length') : null,
            min_value: num ? readOptionalNumber(data, 'min_value') : null, max_value: num ? readOptionalNumber(data, 'max_value') : null,
            default_value: readNullable(data, 'default_value'), enum_values: enumerated ? readLines(readText(data, 'enum_values')) : null,
            position: readNumber(data, 'position'), extra: extra ? JSON.parse(extra) as Record<string, unknown> : null,
          }
          write.mutate(body, { onSuccess: saved })
        }} />
    </Stack>
  </Dialog>
}

export default function AuthFields(props: SecureProps & { auth?: AuthConfig | null }) {
  const t = useT()
  const l = (key: string) => t('secure.fields.' + key)
  const { projectId, auth } = props
  const { search, page: setPage } = useSecureSearch()
  const page = search.page ?? 1
  const list = useQuery(fieldsOptions(projectId, page))
  const [editing, setEditing] = useState<AuthCustomField | 'new'>()
  const [added, setAdded] = useState(false)
  const remove = useSecureMutation(projectId, (id: string) => securityApi.deleteField(id), 'auth-fields')
  const editable = canEdit(props)
  if (list.isPending) return <SecureLoading label={l('loading')} />
  if (list.isError) return <LoadFailure error={list.error} message={l('loadError')} retry={() => void list.refetch()} />
  const total = list.data.total
  const pages = Math.max(1, Math.ceil(total / fieldPageSize))
  const rows = list.data.items
  const add = <Button variant="primary" disabled={total >= 30} onClick={() => { setAdded(false); setEditing('new') }}>{l('new')}</Button>
  const yesNo = (value: boolean) => l(value ? 'yes' : 'no')
  return <Stack>
    {added && <Alert tone="success">{l('saved')}</Alert>}
    <WriteNotice error={remove.error} saved={remove.isSuccess ? l('deleted') : undefined} message={l('deleteError')}
      reload={() => { remove.reset(); void list.refetch() }} />
    {editing && <FieldEditor id={projectId} current={editing === 'new' ? undefined : editing} locked={auth?.provider === 'keycloak'}
      close={() => setEditing(undefined)} saved={() => { setAdded(true); setEditing(undefined) }} />}
    {rows.length ? <SettingsSection title={l('title')}>
      <Row className="v2-spread"><span>{t('secure.fields.count', { count: total })}</span>{editable && add}</Row>
      <Table label={l('title')} columns={['name', 'label', 'type', 'required', 'unique', 'indexed', 'position', 'details', 'actions']
        .map(id => ({ id, label: l(id) }))} rows={rows.map(field => ({
        id: field.id, cells: [
          <code>{field.name}</code>, field.label, l(field.type), yesNo(field.required), yesNo(field.unique),
          yesNo(field.indexed), new Intl.NumberFormat().format(field.position),
          <Stack gap={1}>{[
            ['min_length', field.min_length], ['max_length', field.max_length], ['min_value', field.min_value], ['max_value', field.max_value],
            ['default_value', field.default_value], ['enum_values', field.enum_values?.join(', ')],
          ].filter(([, value]) => value != null).map(([key, value]) => <span key={key}>
            {t('secure.fields.detailValue', { field: l(String(key)), value: String(value) })}</span>)}</Stack>,
          editable ? <Row>
            <Button onClick={() => { setAdded(false); setEditing(field) }}>{l('edit')}</Button>
            <ConfirmDestructive trigger={<Button variant="danger" disabled={remove.isPending}>{l('delete')}</Button>}
              title={t('secure.fields.deleteTitle', { name: field.name })} description={l('deleteDescription')} action={l('delete')}
              onConfirm={async () => {
                await remove.mutateAsync(field.id)
                if (page > 1 && rows.length === 1) setPage(page - 1)
              }} />
          </Row> : l('readOnly'),
        ],
      }))} />
    </SettingsSection> : <EmptyState title={l('empty')} action={editable && add} />}
    {(pages > 1 || page > 1) && <Pagination label={l('title')} page={page} pages={pages} onChange={setPage} />}
    {!!rows.length && <SettingsSection title={l('preview')}>
      <Grid>{rows.map(field => {
        const type = ({ email: 'email', phone: 'tel', url: 'url', date: 'date', datetime: 'datetime-local',
          integer: 'number', float: 'number' })[field.type as string] ?? 'text'
        return <Field key={field.id} label={field.label} hint={field.required ? l('required') : undefined}>
          {attrs => field.type === 'enum' ? <Select disabled triggerProps={attrs} placeholder={l('previewChoice')}
            options={(field.enum_values ?? []).map(value => ({ value, label: value }))} />
            : <Input {...attrs} type={field.type === 'boolean' ? 'checkbox' : type} disabled
              defaultValue={field.type !== 'boolean' ? field.default_value ?? '' : undefined}
              defaultChecked={field.type === 'boolean' && field.default_value === 'true'} />}
        </Field>
      })}</Grid>
    </SettingsSection>}
    {!!rows.length && <SettingsSection title={l('userTable')} description={auth?.provider === 'keycloak' ? l('userAttributes') : l('userTableHelp')}>
      <Table label={l('userTable')} columns={['column', 'type'].map(key => ({ id: key, label: l(key) }))}
        rows={rows.map(field => ({ id: field.id, cells: [<code>{field.name}</code>, l(field.type)] }))} />
    </SettingsSection>}
  </Stack>
}

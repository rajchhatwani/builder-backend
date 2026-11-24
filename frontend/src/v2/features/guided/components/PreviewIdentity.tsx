import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { parseAccessToken } from '../../../../shell/preview/previewSession'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import { Alert, Button, Dialog, Input, Row, Stack } from '../../../ui'
import { validators } from '../../../validators'
import type { Preview } from '../api/delivery'
import { previewRequest } from '../api/preview'
import type { Credential } from '../state/preview'
import { usePreviewCredentials } from './PreviewCredentials'

export function PreviewIdentity({ preview, credential, allowRegister }: { preview: Preview; credential: Credential; allowRegister: boolean }) {
  const t = useT()
  const { dispatch } = usePreviewCredentials()
  const [mode, setMode] = useState<'login' | 'register'>()
  const [failure, setFailure] = useState<number>()
  const submitted = useRef<{ account: 'login' | 'register'; values: FormData } | undefined>(undefined)
  const auth = useMutation({
    mutationFn: async () => {
      const form = submitted.current
      submitted.current = undefined
      if (!form) return 0
      const { account, values } = form
      const body = { email: String(values.get('email')).trim(), password: String(values.get('password')) }
      const anonymous = { ...credential, bearer: undefined }
      const reply = await previewRequest(preview, anonymous, 'POST', '/auth/' + account, body)
      if (reply.status < 200 || reply.status >= 300) return reply.status
      const session = account === 'login' || parseAccessToken(reply.text) ? reply
        : await previewRequest(preview, anonymous, 'POST', '/auth/login', body)
      const bearer = parseAccessToken(session.text)
      if (!bearer) return session.status
      dispatch({ type: 'identity', id: preview.id, token: credential.token, bearer })
      return undefined
    },
    gcTime: 0,
  })
  function submit(values: FormData) {
    const account = mode
    if (!account) return
    submitted.current = { account, values }
    void auth.mutateAsync().then(result => {
      auth.reset()
      setFailure(result)
      if (result === undefined) setMode(undefined)
    }, () => { auth.reset(); setFailure(0) })
  }
  return <Row>
    {credential.bearer ? <Button onClick={() => dispatch({ type: 'identity', id: preview.id, token: credential.token })}>{t('preview.signOut')}</Button>
      : <>
        <Button onClick={() => { setFailure(undefined); setMode('login') }}>{t('preview.signIn')}</Button>
        {allowRegister && <Button onClick={() => { setFailure(undefined); setMode('register') }}>{t('preview.register')}</Button>}
      </>}
    <Dialog title={t(mode === 'register' ? 'preview.register' : 'preview.signIn')} open={Boolean(mode)} onOpenChange={open => { if (!open && !auth.isPending) setMode(undefined) }}>
      <Stack><p>{t('preview.identityHint')}</p>
      {failure !== undefined && <Alert tone="danger">{failure === 0 ? t('preview.network') : t('preview.responseError', { status: failure })}</Alert>}
      <Form submitLabel={t(mode === 'register' ? 'preview.register' : 'preview.signIn')} pending={auth.isPending} onSubmit={submit}
        fields={[
          { name: 'email', label: t('preview.email'), validate: [validators.required, validators.email], control: attrs => <Input {...attrs} type="email" autoComplete="off" /> },
          { name: 'password', label: t('preview.password'), validate: [validators.required], control: attrs => <Input {...attrs} type="password" autoComplete="off" /> },
        ]} /></Stack>
    </Dialog>
  </Row>
}

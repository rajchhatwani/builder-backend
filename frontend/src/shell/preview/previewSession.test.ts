import { describe, expect, it } from 'vitest'
import type { PreviewInstance } from '../../api/types'
import {
  appErrorMessage, buildPreviewBase, isPreviewTokenRefusal, joinPreviewUrl, parseAccessToken, pickLivePreview, waitingMessage,
} from './previewSession'

const pv = (id: string, state: string, created_at: string): PreviewInstance =>
  ({ id, state, created_at, project_id: 'p', workspace_id: null, spec_hash: 'h', url_path: `/previews/${id}/`, last_request_at: created_at, expires_at: created_at }) as PreviewInstance

describe('pickLivePreview', () => {
  it('returns null for an empty list', () => { expect(pickLivePreview([])).toBeNull() })
  it('ranks running over starting over sleeping', () => {
    const l = [pv('s', 'sleeping', '2026-01-03T00:00:00Z'), pv('t', 'starting', '2026-01-02T00:00:00Z'), pv('r', 'running', '2026-01-01T00:00:00Z')]
    expect(pickLivePreview(l)?.id).toBe('r')
    expect(pickLivePreview(l.slice(0, 2))?.id).toBe('t')
    expect(pickLivePreview(l.slice(0, 1))?.id).toBe('s')
  })
  it('takes the newest within a state', () => {
    const l = [pv('a', 'running', '2026-01-01T00:00:00Z'), pv('b', 'running', '2026-01-05T00:00:00Z'), pv('c', 'running', '2026-01-03T00:00:00Z')]
    expect(pickLivePreview(l)?.id).toBe('b')
  })
  it('never picks stopping, expired, failed or killed', () => {
    const l = ['stopping', 'expired', 'failed', 'killed', 'weird'].map((s, i) => pv(String(i), s, '2026-01-01T00:00:00Z'))
    expect(pickLivePreview(l)).toBeNull()
  })
})

describe('url helpers', () => {
  it('buildPreviewBase trims and joins slashes', () => {
    expect(buildPreviewBase('http://h:1/', '/previews/x/')).toBe('http://h:1/previews/x')
    expect(buildPreviewBase('http://h:1', 'previews/x')).toBe('http://h:1/previews/x')
    expect(buildPreviewBase('http://h:1///', '//previews/x//')).toBe('http://h:1/previews/x')
  })
  it('joinPreviewUrl always uses one slash', () => {
    expect(joinPreviewUrl('http://h/previews/x', '/a/b')).toBe('http://h/previews/x/a/b')
    expect(joinPreviewUrl('http://h/previews/x', 'a/b')).toBe('http://h/previews/x/a/b')
  })
})

describe('isPreviewTokenRefusal', () => {
  it('needs 401 and the words preview token', () => {
    expect(isPreviewTokenRefusal(401, 'Invalid Preview Token')).toBe(true)
    expect(isPreviewTokenRefusal(401, 'bad credentials')).toBe(false)
    expect(isPreviewTokenRefusal(403, 'preview token')).toBe(false)
  })
})

describe('parseAccessToken', () => {
  it('reads access_token', () => { expect(parseAccessToken('{"access_token":"abc"}')).toBe('abc') })
  it('returns null for bad json, missing, empty or non-string', () => {
    expect(parseAccessToken('nope')).toBeNull()
    expect(parseAccessToken('{}')).toBeNull()
    expect(parseAccessToken('{"access_token":""}')).toBeNull()
    expect(parseAccessToken('{"access_token":5}')).toBeNull()
  })
})

describe('appErrorMessage', () => {
  it('reads detail, message, error.message and array msg', () => {
    expect(appErrorMessage(400, '{"detail":"bad one"}')).toBe('bad one')
    expect(appErrorMessage(400, '{"message":"msg one"}')).toBe('msg one')
    expect(appErrorMessage(400, '{"error":{"message":"nested"},"message":"outer"}')).toBe('nested')
    expect(appErrorMessage(422, '{"detail":[{"msg":"field required"}]}')).toBe('field required')
  })
  it('falls back by status', () => {
    expect(appErrorMessage(429, '')).toMatch(/too many/i)
    expect(appErrorMessage(503, 'x')).toMatch(/waking up/)
    expect(appErrorMessage(504, '{}')).toMatch(/waking up/)
    expect(appErrorMessage(500, 'oops')).toBe('The preview app answered 500.')
    expect(appErrorMessage(418, '{"detail":[]}')).toBe('The preview app answered 418.')
  })
})

describe('waitingMessage', () => {
  it('describes loading, starting and sleeping', () => {
    expect(waitingMessage('loading', null)).toMatch(/Looking for a preview/)
    expect(waitingMessage('starting', 'starting')).toMatch(/starting/)
    expect(waitingMessage('needs-signin', 'sleeping')).toMatch(/asleep/)
  })
  it('is empty otherwise', () => {
    expect(waitingMessage('needs-signin', 'running')).toBe('')
    expect(waitingMessage('ready', 'running')).toBe('')
  })
})

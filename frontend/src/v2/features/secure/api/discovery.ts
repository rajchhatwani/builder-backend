import { secureAddress } from '../../../validators'
import { oidcFields, type OidcField } from '../state/providers'

export async function discoverOidc(address: string, signal: AbortSignal) {
  const url = secureAddress(address.trim())
  if (!url || url.search || address.includes('?')) throw new Error('discovery_address')
  if (!url.pathname.endsWith('/.well-known/openid-configuration')) {
    url.pathname = url.pathname.replace(/\/$/, '') + '/.well-known/openid-configuration'
  }
  const response = await fetch(url, { signal, credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer' })
  if (!response.ok) throw new Error('discovery_response')
  const metadata: unknown = await response.json()
  if (!metadata || typeof metadata !== 'object') throw new Error('discovery_metadata')
  const data = metadata as Record<string, unknown>
  const values = oidcFields.map(field => {
    const value = field === 'authorization_url' ? data.authorization_endpoint : field === 'token_url' ? data.token_endpoint
      : field === 'jwks_url' ? data.jwks_uri : field === 'userinfo_url' ? data.userinfo_endpoint : data.issuer
    return [field, typeof value === 'string' && value.length <= 2000 && secureAddress(value) ? value : null] as const
  })
  if (values.some(([field, value]) => field !== 'userinfo_url' && !value)) throw new Error('discovery_metadata')
  return Object.fromEntries(values) as Record<OidcField, string | null>
}

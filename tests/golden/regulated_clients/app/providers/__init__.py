"""Provider adapters and the per-tenant credential vault (generated).

  from app.providers.client import call_provider
  result = await call_provider(session, tenant_id, "email", EmailRequest(to=..., subject=..., body=...))

Adapters are registered in app/hooks/providers.py (yours). Credentials are written by a tenant admin
through /providers/credentials, encrypted with PROVIDER_VAULT_KEY, and decrypted only inside the call.
"""

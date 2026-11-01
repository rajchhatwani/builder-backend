"""Providers (generated from the spec: change it in the builder).

Plain data: provider NAMES and non-secret settings. Credentials are never here; each tenant
stores its own through /providers/credentials."""

ADMIN_ROLE = 'admin'
TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
BREAKER_FAILURES = 5
BREAKER_RESET_SECONDS = 30.0
MULTI_TENANT = True
PROVIDERS = ['acme_mail', 'acme_sms']
ADAPTERS = {'email': ['acme_mail'],
 'generic': [],
 'llm': [],
 'payments': [],
 'push': [],
 'sms': ['acme_sms'],
 'storage': []}
SETTINGS = {'email/acme_mail': {'from_name': 'Notify Desk', 'region': 'eu'}, 'sms/acme_sms': {}}

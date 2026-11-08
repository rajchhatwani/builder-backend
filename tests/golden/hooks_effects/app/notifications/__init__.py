"""Notifications over the provider adapters (generated).

    from app.notifications.service import Recipient, notify

    await notify(session, "order_shipped", Recipient(key=str(user_id), email="ann@example.com"),
                 {"order": "A-17"}, tenant_id=tenant_id)       # joins YOUR transaction

* Templates: the spec's defaults, overridable per tenant through /notifications/templates. Placeholders are
  `{{ name }}` of declared variables only; nothing is ever evaluated, and email HTML escapes every value.
* Preferences: a user may opt out per type and channel unless the type is `transactional`.
* Every message gets one row in the delivery log (status, provider message id, error code); the address
  and the variables live only until the message is sent (or finally fails), and the body is never stored.
* A dispatcher (inside the API, or `python -m app.notifications.dispatcher`) sends queued rows with
  retries and backoff through app.providers (the emulator in tests: nothing real is ever sent there).
"""

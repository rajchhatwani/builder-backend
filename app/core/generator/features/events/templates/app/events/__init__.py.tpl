"""Transactional outbox and typed event bus (generated).

A write and its events commit together (hooks.py adds the outbox rows in the write's transaction), a
relay (relay.py) delivers them at least once and in order per record, and subscribers in
app/hooks/subscribers.py receive them. See bus.py for the contract."""

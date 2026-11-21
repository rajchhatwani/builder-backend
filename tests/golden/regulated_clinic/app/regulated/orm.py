"""The write path of regulated mode (generated): one `before_flush` listener on every Session.

For each pending or changed instance of an entity with protected fields:
  searchable   -> `<field>_bidx` is set to the blind index of the new value (None for a null value)
  tokenise     -> the value is vaulted (app/regulated/tokens.py) and replaced by its token

Only fields whose value changed in this flush are touched, so a plain update of another field does not re-hash or
re-token. Importing this module registers the listener once."""

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.regulated import crypto, settings, tokens

_DONE = "regulated_tokenised"  # InstanceState.info key: {field: token} already swapped in this instance


def _before_flush(session: Session, _context: Any, _instances: Any) -> None:
    for obj in [*session.new, *session.dirty]:
        table = getattr(type(obj), "__table__", None)
        rules = settings.PROTECTED.get(getattr(table, "name", ""))
        if not rules:
            continue
        state = inspect(obj)
        pending = state.key is None
        for column, rule in rules.items():
            if not pending and not state.attrs[column].history.has_changes():
                continue
            value = getattr(obj, column)
            if rule["mode"] == "tokenise":
                done: dict[str, str] = state.info.setdefault(_DONE, {})
                if value is None or done.get(column) == value:
                    continue
                token = tokens.tokenise_sync(session, table.name, column, value)
                done[column] = token
                setattr(obj, column, token)
            elif rule["searchable"]:
                setattr(obj, column + "_bidx", None if value is None else crypto.blind_index(table.name, column, value))


if not event.contains(Session, "before_flush", _before_flush):
    event.listen(Session, "before_flush", _before_flush)

"""Model providers of the gateway (generated). Only the deterministic FAKE provider exists: no network, the same
input always gives the same output and the same token counts.

Token estimate: ceil(characters / 4), at least 1 per text. The gateway uses the same estimate for the worst case it
reserves, so the real cost of a fake call never exceeds the reservation. A future real provider MUST be capped by
`max_output_tokens` and its input estimate MUST be an upper bound.

Test switches (directives written in any message, honoured by the fake provider ONLY when config.FAKE_DIRECTIVES is True,
which is False in generated code; the text of a message is untrusted):
  [[fake:fail]]            every attempt fails (provider_error)
  [[fake:fail_primary]]    the primary model fails, the fallback model works
  [[fake:delay=300]]       the call takes 300 ms (0..5000)
  [[fake:out=40]]          the output is exactly 40 tokens (capped by max_output_tokens)
  [[fake:json={"a": 1}]]   with response_format json the output is exactly this JSON text (at most 1000 characters). The
                           scan is JSON-aware: nested arrays ([[1]]) and values containing "]]" work; a value that is
                           not a JSON document ends at the first "]]"

Document extraction (D34, fake only): with response_format json and no [[fake:json=...]] directive, a first message that
starts with "EXTRACT FIELDS: a,b" and messages "SEGMENT <offset>\\n<text>" make the fake find `name: value` / `name = value`
lines (underscores in a name match a space or _) and answer {"fields": {name: {value, confidence_bp, start, end, quote}}}
with offsets relative to the whole document. Confidence is 9500; a value ending in "?" gets 4000; a trailing
[[conf=NNNN]] on the line sets it (and is not part of the value). A name that is not found is omitted.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass

_OPEN = "[[fake:"
_MAX_DIRECTIVE = 1000  # characters between "[[fake:" and the closing "]]": bounded, so a hostile text costs linear time
_NAME = re.compile(r"([a-z_]{1,20})")
_JSON = json.JSONDecoder()
_SEGMENT = re.compile(r"SEGMENT (\d+)\n")
_CONF = re.compile(r"\[\[conf=(\d{1,5})\]\]$")
EXTRACT_PREFIX = "EXTRACT FIELDS: "


class ProviderError(Exception):
    """The provider call failed; nothing was consumed."""


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


def estimate_tokens(text: str) -> int:
    return max(1, -(-len(text) // 4))


def estimate_input_tokens(contents: list[str]) -> int:
    return sum(estimate_tokens(c) for c in contents)


def _directives(contents: list[str]) -> dict[str, str]:
    """`[[fake:name]]` or `[[fake:name=value]]`. JSON-aware: when the value starts a JSON document (json.raw_decode, so nested
    arrays such as [[1]] and values containing "]]" work) and "]]" follows it, that is the value. Otherwise (delay=300, plain
    text, malformed JSON) the value ends at the first "]]". At most _MAX_DIRECTIVE characters after the marker are looked at
    per occurrence and nothing backtracks, so a hostile text costs linear time."""
    found: dict[str, str] = {}
    for content in contents:
        pos = 0
        while True:
            start = content.find(_OPEN, pos)
            if start < 0:
                break
            body_start = start + len(_OPEN)
            limit = body_start + _MAX_DIRECTIVE + 2
            name = _NAME.match(content, body_start, limit)
            if name is None:
                pos = body_start
                continue
            after = name.end()
            if content.startswith("]]", after, limit):
                found[name.group(1)] = ""
                pos = after + 2
                continue
            if content[after : after + 1] != "=":
                pos = body_start
                continue
            window = content[after + 1 : limit]
            try:
                _, used = _JSON.raw_decode(window)
            except (ValueError, RecursionError):  # malformed, or hostile deep nesting inside the 1000-char window
                used = -1
            if used > 0 and window.startswith("]]", used):
                found[name.group(1)] = window[:used]
                pos = after + 1 + used + 2
                continue
            end = content.find("]]", after + 1, limit)
            if end < 0:
                pos = body_start
                continue
            found[name.group(1)] = content[after + 1 : end]
            pos = end + 2
    return found


_MAX_EXTRACT_NAMES = 200


def _label_index(text: str) -> dict[str, tuple[str, int]]:
    """First `label: value` / `label = value` line per label, parsed linearly (no backtracking pattern): label -> (value, offset of the value)."""
    index: dict[str, tuple[str, int]] = {}
    position = 0
    for line in text.split("\n"):
        sep = min((i for i in (line.find(":"), line.find("=")) if i >= 0), default=-1)
        if sep >= 0:
            label = line[:sep].strip(" \t").lower().replace(" ", "_")
            if label and label not in index:
                rest = line[sep + 1 :]
                lead = len(rest) - len(rest.lstrip(" \t"))
                index[label] = (rest.strip(" \t"), position + sep + 1 + lead)
        position += len(line) + 1
    return index


def _extract(contents: list[str], markers: bool) -> str | None:
    names: list[str] | None = None
    segments: list[tuple[int, str]] = []
    for content in contents:
        if content.startswith(EXTRACT_PREFIX):
            names = [n for n in content[len(EXTRACT_PREFIX) :].split("\n", 1)[0].split(",") if n]
        match = _SEGMENT.match(content)
        if match is not None:
            segments.append((int(match.group(1)), content[match.end() :]))
    if names is None:
        return None
    names = list(dict.fromkeys(names))[:_MAX_EXTRACT_NAMES]  # duplicates and absurd lists cost nothing
    indexed = [(offset, _label_index(text)) for offset, text in segments]
    fields: dict[str, dict[str, object]] = {}
    for name in names:
        wanted = name.strip().lower().replace(" ", "_")
        for offset, index in indexed:
            found = index.get(wanted)
            if found is None or not found[0]:
                continue
            raw, start = found[0], offset + found[1]
            hint = _CONF.search(raw) if markers else None
            value = raw[: hint.start()].rstrip() if hint else raw
            if not value:
                continue
            conf = int(hint.group(1)) if hint else (4000 if value.endswith("?") else 9500)
            fields[name] = {
                "value": value,
                "confidence_bp": min(conf, 10000),
                "start": start,
                "end": start + len(value),
                "quote": value,
            }
            break
    return json.dumps({"fields": fields}, separators=(",", ":"), sort_keys=True)


async def complete(
    kind: str,
    model: str,
    contents: list[str],
    max_output_tokens: int,
    json_mode: bool,
    is_fallback: bool,
    directives_enabled: bool = False,
) -> Completion:
    if kind != "fake":
        raise ProviderError(f"provider kind {kind!r} is not available")
    directives = _directives(contents) if directives_enabled else {}
    delay = directives.get("delay", "")
    if delay.isdigit():
        await asyncio.sleep(min(int(delay), 5000) / 1000)
    if "fail" in directives or ("fail_primary" in directives and not is_fallback):
        raise ProviderError("the fake provider was told to fail")
    digest = hashlib.sha256(json.dumps([model, contents], separators=(",", ":")).encode()).hexdigest()
    if json_mode:
        text = directives.get("json") or _extract(contents, directives_enabled) or json.dumps({"echo": digest[:16]}, separators=(",", ":"))
    else:
        wanted = directives.get("out", "")
        if wanted.isdigit() and int(wanted) >= 1:
            text = (digest * (4 * int(wanted) // len(digest) + 1))[: 4 * int(wanted)]
        else:
            text = f"fake:{digest[:16]}"
    text = text[: 4 * max_output_tokens]
    return Completion(
        text=text,
        input_tokens=estimate_input_tokens(contents),
        output_tokens=min(estimate_tokens(text), max_output_tokens),
    )

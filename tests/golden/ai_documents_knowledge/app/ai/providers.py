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
  [[fake:json={"a": 1}]]   with response_format json the output is exactly this JSON text

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

_DIRECTIVE = re.compile(r"\[\[fake:([a-z_]{1,20})(?:=([^\]]{0,200}))?\]\]")  # bounded: linear time on hostile text
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
    found: dict[str, str] = {}
    for content in contents:
        for name, value in _DIRECTIVE.findall(content):
            found[name] = value
    return found


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
    fields: dict[str, dict[str, object]] = {}
    for name in names:
        label = re.compile(r"(?im)^[ \t]*" + re.escape(name).replace("_", "[ _]") + r"[ \t]*[:=][ \t]*(.*?)[ \t]*$")
        for offset, text in segments:
            found = label.search(text)
            if found is None or not found.group(1):
                continue
            raw, start = found.group(1), offset + found.start(1)
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

"""DNS TXT lookups for SSO domain verification (§12.D.2). Tests replace `txt_records`."""

import dns.asyncresolver
import dns.exception
import dns.resolver


async def txt_records(name: str) -> list[str]:
    """The TXT strings at `name`; empty when there are none or DNS doesn't answer in time."""
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 5.0
    try:
        answer = await resolver.resolve(name, "TXT")
    except (dns.exception.DNSException, UnicodeError):
        # Timeouts, NXDOMAIN, SERVFAIL, malformed names or answers: none of them proves the record.
        return []
    # One TXT record may be split into several <=255-byte strings; they join without spaces.
    return [b"".join(rdata.strings).decode("utf-8", "replace") for rdata in answer]

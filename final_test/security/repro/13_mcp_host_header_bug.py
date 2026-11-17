"""Checkpoint: the /mcp endpoint rejects every Host header except 127.0.0.1/localhost/::1,
because app/api/mcp.py's build_mcp_app() never passes `host=` or `transport_security=` to
mcp.streamable_http_app() (which defaults host="127.0.0.1" and then auto-enables DNS-rebinding
protection allowlisting only localhost variants). Reproduces against the live local port
directly (no network topology involved -- it's purely the Host header value)."""
import httpx, asyncio

async def raw(host_header, base="http://127.0.0.1:8000"):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "Host": host_header}
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "sectest", "version": "1.0"}}}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(base + "/mcp/", headers=headers, json=body)
        print(f"Host={host_header!r} -> {r.status_code} {r.text[:150]}")

async def main():
    await raw("127.0.0.1:8000")                                    # works
    await raw("cinderous-overfamiliar-sanford.ngrok-free.dev")     # the real public API hostname -- 421
    await raw("api.example.com")                                    # any other real hostname -- 421

asyncio.run(main())

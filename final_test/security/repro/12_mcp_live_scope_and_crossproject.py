import sys, json, asyncio
import httpx
sys.path.insert(0, "/mnt/files/projects/builder-backend/final_test/harness")
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

TUNNEL = "https://cinderous-overfamiliar-sanford.ngrok-free.dev"
MCP_URL = "http://127.0.0.1:8000/mcp/"

with open("/tmp/claude-1000/-mnt-files-projects-builder-backend/93af46a5-8476-4fb5-9045-ae58628efbc7/scratchpad/mcp_tokens2.json") as f:
    T = json.load(f)
proj_a, proj_b = T["proj_a"], T["proj_b"]

RESULTS = {}


async def call(label, token, tool, args):
    headers = {"ngrok-skip-browser-warning": "1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30) as hc:
            async with streamable_http_client(MCP_URL, http_client=hc) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, args)
                    text = result.content[0].text if result.content else str(result)
                    is_error = getattr(result, "isError", False)
                    RESULTS[label] = {"ok": not is_error, "preview": text[:200]}
    except Exception as e:
        RESULTS[label] = {"exception": str(e)[:300]}


async def main():
    await call("1_no_auth", None, "list_projects", {})
    await call("2_read_a_list_projects", T["read_a"], "list_projects", {})
    await call("3_read_a_get_spec_A", T["read_a"], "get_project_spec", {"project_id": proj_a})
    await call("4_read_a_get_spec_B_escape_attempt", T["read_a"], "get_project_spec", {"project_id": proj_b})
    await call("5_read_only_write_attempt", T["read_a"], "create_entity", {"project_id": proj_a, "name": "Hacked"})
    await call("6_write_token_create_entity_A", T["write_a"], "create_entity", {"project_id": proj_a, "name": "LegitEntity"})
    await call("7_mcp_disabled_on_project", T["read_b_disabled"], "get_project_spec", {"project_id": proj_b})


asyncio.run(main())
print(json.dumps(RESULTS, indent=2, default=str))
with open("/mnt/files/projects/builder-backend/final_test/security/evidence/mcp_live_results.json", "w") as f:
    json.dump(RESULTS, f, indent=2, default=str)

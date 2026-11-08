"""Checkpoint: oversized body (over max_request_bytes) and deeply nested JSON, live."""
import sys, json, subprocess
sys.path.insert(0, "final_test/harness")
import bb
api = bb.Api()
tok = api.customer("owner")

# 12 MB body -- over the 10 MB cap (settings.max_request_bytes)
huge = "A" * (12 * 1024 * 1024)
with open("/tmp/huge_body.json", "w") as f:
    json.dump({"name": huge, "slug": "huge-test"}, f)
r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{time_total}",
                     "-X", "POST", api.base + "/orgs", "-H", "Content-Type: application/json",
                     "-H", f"Authorization: Bearer {tok}", "--data-binary", "@/tmp/huge_body.json"],
                    capture_output=True, text=True)
print("12MB body ->", r.stdout)

# 10,000-level-deep JSON array -- small in bytes, deep in nesting (parser-recursion DoS shape)
nested = "[" * 10000 + "]" * 10000
with open("/tmp/deep.json", "w") as f:
    f.write(nested)
r = subprocess.run(["curl", "-s", "-X", "POST", api.base + "/orgs", "-H", "Content-Type: application/json",
                     "-H", f"Authorization: Bearer {tok}", "--data-binary", "@/tmp/deep.json"],
                    capture_output=True, text=True)
print("deep nesting ->", r.stdout)

st, b, _ = api.call("GET", "/health", token=None)
print("API still healthy after both payloads:", st)

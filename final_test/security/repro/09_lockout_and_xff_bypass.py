"""Checkpoint 5: account lockout + X-Forwarded-For rate-limit bypass attempt, live."""
import sys, json, urllib.request, urllib.error
sys.path.insert(0, "final_test/harness")
import bb

api = bb.Api()

def lockout_test():
    email = "sectest-lockout-demo@dumbpotato.com"
    pw = api.password()
    api.call("POST", "/account/register", {"email": email, "password": pw, "name": "x"})
    for i in range(5):
        api.call("POST", "/account/login", {"email": email, "password": f"wrong{i}"})
    st, b, _ = api.call("POST", "/account/login", {"email": email, "password": pw})  # correct password
    print("6th attempt with CORRECT password after 5 failures:", st, b)

def xff_bypass_test():
    TUNNEL = "https://cinderous-overfamiliar-sanford.ngrok-free.dev"
    def login_with_xff(fake_ip, n):
        req = urllib.request.Request(
            TUNNEL + "/account/login",
            json.dumps({"email": f"nouser{n}@dumbpotato.com", "password": "whatever"}).encode(),
            {"Content-Type": "application/json", "ngrok-skip-browser-warning": "1", "X-Forwarded-For": fake_ip},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
    results = [login_with_xff(f"203.0.113.{i % 250}", 1000 + i) for i in range(35)]
    print(results)
    print("first 429 at request #", (results.index(429) + 1) if 429 in results else "never (bypass!)")

if __name__ == "__main__":
    lockout_test()
    xff_bypass_test()  # run against a freshly-restarted API for a clean rate-limit window

from lib import *
n = "Shared Name " + RUN
for _ in range(40):
    try: e1, t1 = user("sa"); e2, t2 = user("sb"); break
    except AssertionError: time.sleep(15)
c1, b1, _ = call(t1, "POST", "/projects", {"name": n}); c2, b2, _ = call(t2, "POST", "/projects", {"name": n})
rec("J3.slug_global", "two different tenants can each create a project with the same name", c1 == 201 and c2 == 201, f"first {c1}, second {c2} {b2.get('message')}")
c3, b3, _ = call(t1, "POST", "/projects", {"name": "日本語 " + RUN[:0]}); c4, b4, _ = call(t2, "POST", "/projects", {"name": "中文"})
rec("J3.slug_unicode", "non-ASCII project names get distinct slugs", c3 == 201 and c4 in (201,) , f"{c3} {b3.get('slug')} / {c4} {b4.get('slug') or b4.get('message')}")

"""Offline test of the api.py login discriminator against real responses."""
import re
import sys
import types

# Stub aiohttp (not needed for the login check logic)
aiohttp = types.ModuleType("aiohttp")
for name in ("ClientError", "ClientResponseError"):
    setattr(aiohttp, name, type(name, (Exception,), {}))
aiohttp.ClientSession = object
sys.modules["aiohttp"] = aiohttp

sys.path.insert(0, "/home/user/ha-icargps/custom_components")
pkg = types.ModuleType("icargps")
pkg.__path__ = ["/home/user/ha-icargps/custom_components/icargps"]
sys.modules["icargps"] = pkg
from icargps.api import _MONITOR_RE  # noqa: E402


def classify(html: str) -> str:
    """Mirror of async_login's post-submit logic."""
    monitor = _MONITOR_RE.search(html)
    if monitor is None:
        if re.search(r"(?<!function )loginFaild", html):
            return "auth_error"
        return "api_error"
    return "success:" + monitor.group(1)


good = open("/tmp/post.html", encoding="utf-8", errors="replace").read()
bad = open("/tmp/post_bad.html", encoding="utf-8", errors="replace").read()

r1 = classify(good)
r2 = classify(bad)
print("good response ->", r1)
print("bad response  ->", r2)

ok1 = r1.startswith("success:/Monitor.aspx")
ok2 = r2 == "auth_error"
print(("PASS" if ok1 else "FAIL"), "good login classified as success")
print(("PASS" if ok2 else "FAIL"), "bad login classified as auth_error")
if not (ok1 and ok2):
    sys.exit(1)
print("Login discriminator OK.")

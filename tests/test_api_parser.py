"""Offline test of api.py parsing against real/synthetic icargps.net payloads."""
import sys
import types

# Stub aiohttp (not needed for the pure parsing functions)
aiohttp = types.ModuleType("aiohttp")
for name in ("ClientError", "ClientResponseError"):
    setattr(aiohttp, name, type(name, (Exception,), {}))
aiohttp.ClientSession = object
sys.modules["aiohttp"] = aiohttp

sys.path.insert(0, "/home/user/ha-icargps/custom_components")
# Load icargps.api WITHOUT running the package __init__.py (needs homeassistant)
pkg = types.ModuleType("icargps")
pkg.__path__ = ["/home/user/ha-icargps/custom_components/icargps"]
sys.modules["icargps"] = pkg
from icargps.api import parse_d_payload, _q  # noqa: E402

failures = []


def check(name, got, expected):
    ok = got == expected
    print(("PASS" if ok else "FAIL"), name)
    if not ok:
        print("   got:     ", got)
        print("   expected:", expected)
        failures.append(name)


# 1) Real payload captured during the E2E session (empty alarm list)
real_ems = open("/tmp/ems.json").read().strip()
check("real ems.json", parse_d_payload(real_ems), {"ems": [], "lastCreated": ""})

# 2) Devices payload with the fields observed on the IK122T Pro (isFirst:true)
devices_raw = (
    '{"d":"{devices:[{deviceID:2257258,sn:\\"89067750317\\",model:504,'
    'modelName:\\"IK122T Pro\\",name:\\"IK122T Pro-50317\\",'
    'latitude:45.12345,longitude:9.6789,speed:0,course:0,status:\\"Stop\\",'
    'isStop:true,stopTimeMinute:57,'
    'serverUtcDate:\\"2026-11-10 08:15:23.123\\",'
    'deviceUtcDate:\\"2026-11-10 07:10:00.000\\",dataType:1,'
    'dataContext:\\"0-0-19-30\\",ofl:1,distance:0.0}]}"}'
)
parsed = parse_d_payload(devices_raw)
dev = (parsed or {}).get("devices", [{}])[0]
check("device latitude", dev.get("latitude"), 45.12345)
check("device longitude", dev.get("longitude"), 9.6789)
check("device status", dev.get("status"), "Stop")
check("device dataContext", dev.get("dataContext"), "0-0-19-30")
check("device ofl", dev.get("ofl"), 1)
check("device sn", dev.get("sn"), "89067750317")
check("device modelName", dev.get("modelName"), "IK122T Pro")

# 3) Alarm payload (structure from the E2E session: type 1 = geofence exit)
alarms_raw = (
    '{"d":"{ems:[{id:98765,deviceID:2257258,notificationType:1,'
    'note:\\"Casa\\",'
    'deviceDate:\\"2026-11-09 17:42:10\\",'
    'createDate:\\"2026-11-09 17:42:11\\"}],'
    'lastCreated:\\"2026-11-09 16:42:11.123\\"}"}'
)
parsed = parse_d_payload(alarms_raw)
em = (parsed or {}).get("ems", [{}])[0]
check("alarm type", em.get("notificationType"), 1)
check("alarm note", em.get("note"), "Casa")
check("alarm watermark", parsed.get("lastCreated"), "2026-11-09 16:42:11.123")

# 4) _q escapes single quotes / backslashes for pseudo-JSON fields
#    (quotes are added by the f-strings that build the request bodies)
check("_q string", _q("1:00"), "1:00")
check("_q escapes quote", _q("a'b"), "a\\'b")
check("_q escapes backslash", _q("a\\b"), "a\\\\b")
check("_q int", _q(2257258), "2257258")

# 5) Degenerate responses seen in the session
check("empty d", parse_d_payload('{"d":""}'), None)
check("plain d", parse_d_payload('{"d":1234}'), 1234)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("All parser tests passed.")

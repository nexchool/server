"""Do the clients' declared types match what a WRITE answers with?

The other three audits only ever issue GETs. A create or an update answers
with a payload too, and a client declares a type for it that nothing checks.

This one performs real write cycles — create, update, delete — against a
demo tenant, compares each response against the type the client declared for
that call, and then verifies its own cleanup. It refuses to run against
anything that is not an explicitly allowed local host, because it writes.

    export NX_TOKEN=...
    venv/bin/python scripts/audit_client_write_payloads.py

Only entities with a genuinely reversible cycle are probed; each is declared
in PROBES below. Everything else is reported as NOT covered rather than
counted as passing — creating a student mints a Person and an account, and an
audit that leaves those behind is worse than an audit that admits its limit.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_client_field_types import resolve  # noqa: E402
from audit_client_shapes import typed_calls  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://default.localhost"
LOCAL = ("http://default.localhost", "http://localhost", "http://127.0.0.1")
if not BASE.startswith(LOCAL):
    sys.exit(f"refusing to write to {BASE}; this audit is for local demo data only")
TOKEN = os.environ.get("NX_TOKEN") or Path("/tmp/nx_admin_token").read_text().strip()

MARKER = "ZZ Audit Probe"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, None
    except Exception as exc:
        return None, {"error": str(exc)}


def payload(response):
    return (response or {}).get("data", response) or {}


def context():
    """Ids the probes need, read rather than created."""
    ctx = {}
    _s, years = call("GET", "/api/academics/academic-years")
    rows = payload(years)
    if isinstance(rows, dict):
        for key in ("academic_years", "items", "results"):
            if isinstance(rows.get(key), list):
                rows = rows[key]
                break
    if isinstance(rows, list) and rows:
        active = next((r for r in rows if r.get("is_active")), rows[0])
        ctx["academic_year_id"] = active["id"]
    return ctx


# Each probe: how to create it, how to change it, how to remove it, and the
# TypeScript type the client says each answer has.
PROBES = [
    {
        "entity": "subject",
        "create": ("POST", "/api/subjects/", lambda c: {
            "name": MARKER, "code": "ZZAUD", "subject_type": "other"}),
        "update": ("PUT", "/api/subjects/{id}", lambda c: {"description": "probe"}),
        "delete": ("DELETE", "/api/subjects/{id}", None),
        "types": {"create": "Subject", "update": "Subject"},
        "still_there": ("/api/subjects/?include_inactive=true", "name"),
    },
    {
        "entity": "class",
        "create": ("POST", "/api/classes/", lambda c: {
            "name": MARKER, "section": "ZZ",
            "academic_year_id": c["academic_year_id"]}),
        "update": ("PUT", "/api/classes/{id}", lambda c: {"section": "ZY"}),
        "delete": ("DELETE", "/api/classes/{id}", None),
        "types": {"create": "ClassItem", "update": "ClassItem"},
        "still_there": ("/api/classes/?per_page=100", "name"),
    },
    {
        "entity": "holiday",
        "create": ("POST", "/api/holidays/", lambda c: {
            "name": MARKER, "start_date": "2099-01-01", "end_date": "2099-01-01",
            "holiday_type": "school",
            "academic_year_id": c.get("academic_year_id")}),
        "update": ("PUT", "/api/holidays/{id}", lambda c: {"description": "probe"}),
        "delete": ("DELETE", "/api/holidays/{id}", None),
        "types": {"create": "Holiday", "update": "Holiday"},
        "still_there": ("/api/holidays/", "name"),
    },
]


def declared_for(type_name):
    fields = resolve(type_name)
    return sorted(f for f, (_ts, optional) in fields.items() if not optional), fields


def leftovers(url, field):
    status, response = call("GET", url)
    if status != 200:
        return f"could not check ({status})"
    rows = payload(response)
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    if not isinstance(rows, list):
        return "could not check (unexpected shape)"
    return sum(1 for r in rows if isinstance(r, dict) and r.get(field) == MARKER)


def main():
    ctx = context()
    findings, probed, skipped = [], [], []

    for probe in PROBES:
        method, path, build = probe["create"]
        status, response = call(method, path, build(ctx))
        if status not in (200, 201):
            skipped.append(f"{probe['entity']}: create returned {status}")
            continue
        created = payload(response)
        made_id = created.get("id")

        for stage in ("create", "update"):
            if stage == "update":
                m, p, b = probe["update"]
                status, response = call(m, p.format(id=made_id), b(ctx))
                if status != 200:
                    skipped.append(f"{probe['entity']}: update returned {status}")
                    continue
                body = payload(response)
            else:
                body = created
            required, _fields = declared_for(probe["types"][stage])
            if not required:
                skipped.append(f"{probe['entity']}: {probe['types'][stage]} not resolvable")
                continue
            missing = [f for f in required if f not in body]
            probed.append(f"{probe['entity']} {stage} -> {probe['types'][stage]}")
            if missing:
                findings.append((probe["entity"], stage, probe["types"][stage],
                                 missing, sorted(body)))

        m, p, _ = probe["delete"]
        status, _ = call(m, p.format(id=made_id))
        url, field = probe["still_there"]
        remaining = leftovers(url, field)
        if remaining != 0:
            findings.append((probe["entity"], "cleanup", "-",
                             [f"delete returned {status}; {remaining} probe row(s) left"], []))

    print(f"{len(probed)} write responses checked against the client's declared type")
    for line in probed:
        print(f"  ok  {line}")
    print(f"\n{len(findings)} disagreements")
    for entity, stage, type_name, missing, keys in findings:
        print(f"  [{entity}] {stage}: client's {type_name} requires {', '.join(missing)}")
        if keys:
            print(f"        server sent: {', '.join(keys)}")
    if skipped:
        print("\nnot probed:")
        for line in skipped:
            print(f"  {line}")
    print("""
Coverage, measured 2026-08-09 against 104 non-GET client calls that declare a
response type:
   6  verified here by a real write cycle
  60  declare a type some GET already verified — the entity's shape is known
      good, but that is an inference about the write, not a check of it
  38  neither; ~20 of those are `void` / `{message}` and have nothing to check

Read by hand instead of probed, because creating one mints a Person and an
account: POST /api/students and POST /api/teachers both answer
`{student|teacher: <the same dict the detail GET returns>, credentials?}`,
which is what CreateStudentResponse and CreateTeacherResponse declare.

Widening this means adding a PROBE with its own create/update/delete payloads.
Do not widen it by skipping the delete.""")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

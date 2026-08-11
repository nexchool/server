"""Do the client's declared response types match what the server sends?

`audit_client_routes.py` proves a URL still answers. This proves the answer
still has the shape the caller expects — which a TypeScript type assertion
cannot check, because the type is a claim about the server that nothing
verifies.

    export NX_TOKEN=$(curl -s -X POST http://default.localhost/api/auth/login \
      -H 'Content-Type: application/json' \
      -d '{"email":"admin@...","password":"..."}' \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
    venv/bin/python scripts/audit_client_shapes.py [base-url]

It reports the mismatch that actually breaks a screen: the client declares a
bare `X[]` and the server answers with an object. A client declaring
`{items: X[]}`, or a union of both, is handling the envelope and is fine —
an earlier version flagged all of them together and the harmless five buried
the two real ones.

Only GETs are exercised, and only those whose path parameters can be filled
from the demo tenant; what could not be reached is listed at the end rather
than counted as passing. Coverage check: revert a known fix and confirm this
reports it.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://default.localhost"
def _token(env_name, fallback_file):
    value = os.environ.get(env_name)
    if value:
        return value.strip()
    path = Path(fallback_file)
    return path.read_text().strip() if path.exists() else None


# Tried in order. A screen belongs to whoever can open it: a teacher's register
# and a child's own timetable are 401 or 403 to an administrator, so auditing
# with one token silently skips them and reports a clean run.
TOKENS = [
    (role, _token(env, f"/tmp/nx_{role}_token"))
    for role, env in (("admin", "NX_TOKEN"), ("teacher", "NX_TEACHER_TOKEN"),
                      ("student", "NX_STUDENT_TOKEN"))
]
TOKENS = [(role, tok) for role, tok in TOKENS if tok]
if not TOKENS:
    sys.exit("no tokens: set NX_TOKEN (and ideally NX_TEACHER_TOKEN, NX_STUDENT_TOKEN)")

METHOD_OF = {"apiGet": "GET", "apiGetBlob": "GET", "apiPost": "POST",
             "apiPostForm": "POST", "apiPut": "PUT", "apiPatch": "PATCH",
             "apiDelete": "DELETE", "apiUpload": "POST"}
H = "|".join(METHOD_OF)
CALL = re.compile(r"\b(" + H + r")\s*<(?P<ty>[^(]*?)>\s*\(\s*([`\"\'])(/api/)")
ASSIGN = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*([`\"\'])(/api/)")
VIA = re.compile(r"\b(" + H + r")\s*<(?P<ty>[^(]*?)>\s*\(\s*(\w+)\s*[,)]")


def read_literal(text, qpos, quote):
    i, out = qpos + 1, []
    while i < len(text):
        c = text[i]
        if c == "\\":
            out.append(text[i:i + 2]); i += 2; continue
        if c == quote:
            return "".join(out)
        if quote != "`" and c == "\n":
            return "".join(out)
        out.append(c); i += 1
    return "".join(out)


def normalise(raw):
    """`${...}` -> * by scanning balanced braces, never by truncating."""
    out, i = [], 0
    while i < len(raw):
        if raw.startswith("${", i):
            depth, j = 1, i + 2
            while j < len(raw) and depth:
                if raw[j] == "{": depth += 1
                elif raw[j] == "}": depth -= 1
                j += 1
            out.append("*"); i = j
        else:
            out.append(raw[i]); i += 1
    return re.sub(r"//+", "/", "".join(out).split("?")[0])


def typed_calls():
    """Every api* call with the response type the caller declared."""
    rows = {}
    for label, base in (("expo", ROOT / "client"), ("panel", ROOT / "panel"),
                          ("admin-web", ROOT / "admin-web" / "src")):
        if not base.exists():
            sys.exit(f"client path missing: {base}")
        for f in sorted(base.rglob("*.ts*")):
            if {"node_modules", ".next", ".expo"} & set(f.parts):
                continue
            text = f.read_text(errors="ignore")
            by_var = {m.group(1): read_literal(text, m.start(2), m.group(2))
                      for m in ASSIGN.finditer(text)}
            found = [(METHOD_OF[m.group(1)], m.group("ty").strip(),
                      read_literal(text, m.start(3), m.group(3)))
                     for m in CALL.finditer(text)]
            found += [(METHOD_OF[m.group(1)], m.group("ty").strip(), by_var[m.group(3)])
                      for m in VIA.finditer(text) if m.group(3) in by_var]
            for method, ty, raw in found:
                path = normalise(raw)
                if path.startswith("/api/") and path != "/api/":
                    rows[(label, method, path, ty)] = {
                        "client": label, "method": method, "path": path,
                        "type": ty, "file": str(f.relative_to(ROOT)),
                    }
    return list(rows.values())


def _first(data):
    """First row of whatever envelope this endpoint happens to use."""
    if isinstance(data, dict):
        for key in ("items", "results", "data"):
            if isinstance(data.get(key), list) and data[key]:
                return data[key][0]
    return data[0] if isinstance(data, list) and data else {}


def demo_ids():
    """Real ids from the demo tenant, to fill path parameters."""
    ids = {}
    for segment, path, pick in (
        ("classes", "/api/classes/?per_page=1", lambda d: d["items"][0]["id"]),
        ("students", "/api/students/?per_page=1", lambda d: d["items"][0]["id"]),
        ("subjects", "/api/subjects/", lambda d: d[0]["id"]),
        ("teachers", "/api/teachers/?per_page=1",
         lambda d: (d["items"] if isinstance(d, dict) else d)[0]["id"]),
        ("announcements", "/api/announcements/", lambda d: _first(d)["id"]),
        ("holidays", "/api/holidays/", lambda d: _first(d)["id"]),
        ("bell-schedules", "/api/academics/bell-schedules", lambda d: _first(d)["id"]),
        ("routes", "/api/transport/routes", lambda d: _first(d)["id"]),
    ):
        status, payload, _role = fetch(path)
        if status == 200:
            try:
                ids[segment] = pick(payload["data"])
            except (KeyError, IndexError, TypeError):
                pass
    # The segment before a path parameter names it, but not always in the
    # plural the id was fetched under.
    for alias, source in (("class", "classes"), ("student", "students"),
                          ("teacher", "teachers"), ("subject", "subjects")):
        if source in ids:
            ids.setdefault(alias, ids[source])
    return ids


def fetch_as(path, token):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def fetch(path):
    """The first role that can actually open this, and what it got."""
    last = (None, None, None)
    for role, token in TOKENS:
        status, payload = fetch_as(path, token)
        if status == 200:
            return status, payload, role
        if last[0] is None or (status or 0) > (last[0] or 0):
            last = (status, payload, role)
    return last


def candidates(path, ids):
    """Every URL this call might really request, most likely first.

    A `*` glued onto a segment came from a `${qs(...)}` appended to the path —
    a query string, so it is dropped. A `*` that is a whole segment is usually
    an id, but a *trailing* one is ambiguous: `/api/holidays/${query}` and
    `/api/classes/${id}` normalise identically, and reading the first as an id
    hits the detail route and reports a list call as returning one object.
    So a trailing hole yields both readings and the caller tries each.
    """
    parts = path.split("/")
    for i, seg in enumerate(parts):
        if seg != "*" and seg.endswith("*"):
            parts[i] = seg[:-1]

    trailing_hole = parts and parts[-1] == "*"
    urls = []
    if trailing_hole:
        urls.append("/".join(parts[:-1]) + "/")   # the hole was a query string

    filled = list(parts)
    for i, seg in enumerate(filled):
        if seg == "*":
            owner = filled[i - 1] if i else ""
            if owner not in ids:
                return urls          # may be empty: genuinely unreachable
            filled[i] = ids[owner]
    urls.append("/".join(filled))
    return urls


def bare_array(ty):
    """Declared `X[]` and nothing else — no union, no {items}."""
    t = ty.strip()
    return t.endswith("[]") and "|" not in t and "{" not in t


def main():
    ids = demo_ids()
    calls = typed_calls()
    rows, unchecked = [], {}
    for c in calls:
        if c["method"] != "GET" or not (bare_array(c["type"]) or "items" in c["type"]):
            continue
        urls = candidates(c["path"], ids)
        if not urls:
            unchecked.setdefault("path-parameter-unknown", []).append(c["path"]); continue

        wants_array = bare_array(c["type"]) or "items" in c["type"]
        answered = None
        for url in urls:
            status, payload, role = fetch(url)
            if status != 200:
                answered = answered or ("status", status)
                continue
            body = payload.get("data", payload) if isinstance(payload, dict) else payload
            reading = {"body": body, "role": role, "url": url}
            # With two readings of an ambiguous path, believe the one that
            # answers in the shape the caller declared.
            if isinstance(body, list) == wants_array:
                answered = ("ok", reading)
                break
            answered = answered if (answered and answered[0] == "ok") else ("ok", reading)
        if not answered or answered[0] != "ok":
            code = answered[1] if answered else None
            unchecked.setdefault(f"http-{code}", []).append(c["path"]); continue

        reading = answered[1]
        body = reading["body"]
        rows.append({**c, "server_is_array": isinstance(body, list), "role": reading["role"],
                     "url": reading["url"],
                     "server_keys": sorted(body) if isinstance(body, dict) else None})

    broken = [r for r in rows if not r["server_is_array"] and bare_array(r["type"])]
    tolerant = [r for r in rows if not r["server_is_array"] and not bare_array(r["type"])]
    roles = ", ".join(role for role, _ in TOKENS)
    print(f"{len(rows)} collection GETs exercised against {BASE} as: {roles}")
    print(f"{len(broken)} where the client expects a bare array and gets an object")
    print(f"{len(tolerant)} where the client declares the envelope or a union (fine)\n")
    for r in sorted(broken, key=lambda x: (x["client"], x["path"])):
        print(f"[{r['client']}] GET {r['path']}")
        print(f"     client expects: {r['type']}")
        print(f"     server returns: object {{{', '.join(r['server_keys'])}}}")
        print(f"     answered to: {r['role']} at {r['url']}")
        print(f"     {r['file']}")
    print("\nnot exercised (verify by hand rather than assuming they pass):")
    for reason, paths in sorted(unchecked.items()):
        print(f"  {reason}: {len(paths)}")
        if os.environ.get("NX_VERBOSE"):
            for path in sorted(set(paths)):
                print(f"      {path}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())

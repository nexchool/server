"""Every API call Expo and the panel make, matched against the server's routes.

Run from the server directory:  venv/bin/python scripts/audit_client_routes.py
Pass a JSON route dump as argv[1] to audit against a different route table —
which is how the coverage check works: remove routes you know clients call,
and confirm this reports them. A clean audit means nothing until it has been
shown to fail on known-broken input.


Handles the three shapes that hid breaks from earlier versions of this script:
  - inline template literals that span lines:  apiGet(`/api/x${qs({ a: b })}`)
  - a URL built in a variable first:           const u = "/api/x"; apiGet(u)
  - `${...}` holes containing calls/objects, replaced by a balanced-brace scan
    rather than by truncating the path (truncation invented a shorter path that
    matched a real route and hid the break).
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def registered_routes():
    """Every rule the Flask app registers, as {rule, methods}."""
    sys.path.insert(0, str(ROOT / "server"))
    from app import create_app

    app = create_app()
    return [
        {"rule": r.rule, "methods": sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS"))}
        for r in app.url_map.iter_rules()
    ]


rules = (
    json.load(open(sys.argv[1])) if len(sys.argv) > 1 else registered_routes()
)

def rule_regex(rule):
    parts = re.split(r"<[^>]+>", rule)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in parts) + "$")

COMPILED = [(rule_regex(r["rule"]), r["rule"], set(r["methods"])) for r in rules]
METHOD_OF = {
    "apiGet": "GET", "apiGetBlob": "GET", "apiFetchRaw": "GET",
    "apiPost": "POST", "apiPostForm": "POST", "apiUpload": "POST",
    "apiPut": "PUT", "apiPatch": "PATCH", "apiDelete": "DELETE",
}
HELPERS = "|".join(METHOD_OF)
OPEN = re.compile(r"\b(" + HELPERS + r")\s*(?:<[^(]*?>)?\s*\(\s*([`\"'])(/api/)")
ASSIGN = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*([`\"'])(/api/)")
VIA_VAR = re.compile(r"\b(" + HELPERS + r")\s*(?:<[^(]*?>)?\s*\(\s*(\w+)\s*[,)]")

def read_literal(text, quote_pos, quote):
    """The literal's body, from just after the opening quote to its close."""
    i, out = quote_pos + 1, []
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
    """`${...}` → * with balanced braces, so a hole containing an object or a
    call collapses to one segment instead of swallowing the rest of the path."""
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
    path = "".join(out).split("?")[0]
    return re.sub(r"//+", "/", path)

def variants(path):
    """A trailing hole is usually a query string, so try it both ways. Nothing
    else is invented — no truncation."""
    out = {path}
    if path.endswith("*"):
        stem = path.rstrip("*")
        out |= {stem, stem.rstrip("/"), stem.rstrip("/") + "/"}
    out |= {path.rstrip("/"), path.rstrip("/") + "/"} if "*" not in path else set()
    return {v for v in out if v.startswith("/api/")}

def served(paths, method=None):
    wrong = []
    for path in paths:
        probe = path.replace("*", "x")
        for rx, rule, methods in COMPILED:
            if rx.match(probe):
                if method is None or method in methods:
                    return True, []
                wrong.append((rule, sorted(methods)))
    return False, wrong[:2]

findings, seen = [], set()
for label, base in (("expo", ROOT / "client"), ("panel", ROOT / "panel")):
    if not base.exists():
        sys.exit(f"path missing: {base}")
    for f in sorted(base.rglob("*.ts*")):
        if {"node_modules", ".next", ".expo"} & set(f.parts):
            continue
        text = f.read_text(errors="ignore")
        calls = []
        for m in OPEN.finditer(text):
            calls.append((METHOD_OF[m.group(1)], read_literal(text, m.start(2), m.group(2))))
        by_var = {}
        for m in ASSIGN.finditer(text):
            by_var[m.group(1)] = read_literal(text, m.start(2), m.group(2))
        for m in VIA_VAR.finditer(text):
            if m.group(2) in by_var:
                calls.append((METHOD_OF[m.group(1)], by_var[m.group(2)]))
        for method, raw in calls:
            path = normalise(raw)
            if not path.startswith("/api/") or path == "/api/":
                continue
            key = (label, method, path)
            if key in seen:
                continue
            seen.add(key)
            ok, wrong = served(variants(path), method)
            if not ok:
                findings.append((label, method, path, str(f.relative_to(ROOT)), wrong))

print(f"scanned {len(seen)} distinct method+path calls")
print(f"{len(findings)} that no registered route serves\n")
for label, method, path, file, wrong in sorted(findings):
    print(f"[{label}] {method:6} {path}")
    print(f"         {file}")
    for rule, methods in wrong:
        print(f"         !! path exists as {rule} for {','.join(methods)}")

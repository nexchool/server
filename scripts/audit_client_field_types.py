"""Do the fields inside the payload have the types the client declares?

`audit_client_routes.py` proves the URL answers. `audit_client_shapes.py`
proves the container is the right shape. This proves the contents are: a
`string` that became a number, or a field declared non-nullable that the
server sends as null, passes both of those and still breaks a screen.

    export NX_TOKEN=... NX_TEACHER_TOKEN=... NX_STUDENT_TOKEN=...
    venv/bin/python scripts/audit_client_field_types.py [base-url]

Every row of every collection is inspected, not just the first — a field that
is null for one child out of twenty-eight is exactly the one a screen crashes
on later.

What it deliberately does NOT report:
  - a field the client declares optional and the server omits (that is what
    optional means)
  - `any` / `unknown` / a type this script cannot resolve
  - fields the server sends and the client never declared (harmless)

Coverage check: change a client field's declared type and confirm this
reports it. `git stash` will not revert a committed change — use
`git checkout <commit>~1 -- <file>`.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_client_shapes import (  # noqa: E402
    ROOT, TOKENS, bare_array, candidates, demo_ids, fetch, typed_calls,
)

DECL = re.compile(
    r"\b(?:export\s+)?(?:interface|type)\s+(\w+)\s*(?:extends\s+([\w,\s]+?))?\s*=?\s*\{",
    re.M,
)
FIELD = re.compile(r"^\s*(?:readonly\s+)?([A-Za-z_]\w*)\s*(\?)?\s*:\s*([^;\n]+)")


def body_of(text, brace_pos):
    depth, i, out = 1, brace_pos + 1, []
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if not depth:
                break
        out.append(text[i])
        i += 1
    return "".join(out)


def declared_types():
    """{TypeName: {field: (declared_ts_type, is_optional)}} across both clients."""
    found = {}
    for base in (ROOT / "client", ROOT / "panel", ROOT / "admin-web" / "src"):
        for f in base.rglob("*.ts*"):
            if {"node_modules", ".next", ".expo"} & set(f.parts):
                continue
            text = f.read_text(errors="ignore")
            for m in DECL.finditer(text):
                fields, depth = {}, 0
                block = body_of(text, m.end() - 1)
                for line in block.splitlines():
                    if depth == 0:
                        fm = FIELD.match(line)
                        if fm:
                            declared = fm.group(3).strip().rstrip(",")
                            # An inline object type spans lines; reading only
                            # the first gives "{" and calls every array of
                            # objects a mismatch.
                            if declared.startswith("{") and declared.count("{") > declared.count("}"):
                                declared = "INLINE_OBJECT[]" if "[]" in block[block.index(line):][:400].split("\n")[0] else "INLINE_OBJECT"
                            fields[fm.group(1)] = (declared, bool(fm.group(2)))
                    depth += line.count("{") - line.count("}")
                found.setdefault(m.group(1), {"fields": fields,
                                              "extends": [e.strip() for e in
                                                          (m.group(2) or "").split(",")
                                                          if e.strip()]})
    return found


TYPES = declared_types()


def resolve(name, seen=None):
    seen = seen or set()
    if name in seen or name not in TYPES:
        return {}
    seen.add(name)
    out = dict(TYPES[name]["fields"])
    for parent in TYPES[name]["extends"]:
        out.update(resolve(parent, seen))
    return out


UNRESOLVED = {"any", "unknown", "object", "Record", "JSON", "INLINE_OBJECT"}


def allowed_kinds(ts):
    """The JSON kinds a declared TypeScript type accepts, or None if unknown."""
    parts = [p.strip() for p in ts.split("|")]
    kinds, nullable = set(), False
    for part in parts:
        if part in ("null", "undefined"):
            nullable = True
            continue
        if part.endswith("[]") or part.startswith("Array<"):
            kinds.add("list")
        elif part in ("string", "String"):
            kinds.add("str")
        elif part in ("number", "Number"):
            kinds.update({"int", "float"})
        elif part in ("boolean", "Boolean"):
            kinds.add("bool")
        elif part.startswith(("'", '"')):
            kinds.add("str")                      # string-literal union
        elif part.startswith("{") or part in TYPES:
            kinds.add("dict")
        elif any(part.startswith(u) for u in UNRESOLVED):
            return None, True
        else:
            return None, True                     # enum, alias, generic: skip
    return kinds, nullable


def kind_of(value):
    if value is None:
        return "null"
    return {bool: "bool", int: "int", float: "float", str: "str",
            list: "list", dict: "dict"}.get(type(value), "other")


def rows_of(body, ty):
    """Every object the declared element type describes."""
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        body = body["items"]
    if isinstance(body, list):
        return body[:200]
    return [body] if isinstance(body, dict) else []


def main():
    ids = demo_ids()
    findings, checked, skipped = [], 0, defaultdict(int)

    for c in typed_calls():
        if c["method"] != "GET":
            continue
        core = re.sub(r"\[\]$", "", c["type"].strip())
        m = re.match(r"^\{\s*items\s*:\s*(\w+)\[\]", core)
        if m:
            core = m.group(1)
        core = core.split("|")[0].strip().rstrip("[]")
        fields = resolve(core)
        if not fields:
            skipped["type-not-resolvable"] += 1
            continue

        answered = None
        for url in candidates(c["path"], ids):
            status, payload, role = fetch(url)
            if status == 200:
                answered = (payload, role, url)
                break
        if not answered:
            skipped["not-reachable"] += 1
            continue

        payload, role, url = answered
        body = payload.get("data", payload) if isinstance(payload, dict) else payload
        rows = rows_of(body, c["type"])
        if not rows:
            skipped["no-rows-to-inspect"] += 1
            continue
        checked += 1

        seen = defaultdict(set)
        for row in rows:
            if not isinstance(row, dict):
                continue
            for field in fields:
                if field in row:
                    seen[field].add(kind_of(row[field]))

        for field, (ts, optional) in sorted(fields.items()):
            observed = seen.get(field)
            if not observed:
                continue                       # absence is the shapes audit's job
            kinds, nullable = allowed_kinds(ts)
            if kinds is None:
                continue
            if "null" in observed and not nullable and not optional:
                findings.append((c, field, ts, "declared non-nullable; server sends null",
                                 role, url))
            wrong = observed - kinds - {"null"}
            if wrong:
                findings.append((c, field, ts,
                                 f"server sends {'/'.join(sorted(wrong))}", role, url))

    print(f"{checked} responses inspected field by field across {len(TOKENS)} roles")
    print(f"{len(findings)} field-level disagreements\n")
    for c, field, ts, why, role, url in sorted(
        findings, key=lambda x: (x[0]["client"], x[0]["path"], x[1])
    ):
        print(f"[{c['client']}] GET {c['path']}  ({c['type']})")
        print(f"     {field}: declared `{ts}` — {why}")
        print(f"     {c['file']}  [{role} at {url}]")
    print("\nnot inspected:")
    for reason, n in sorted(skipped.items()):
        print(f"  {reason}: {n}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

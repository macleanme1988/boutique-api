"""Execute the requests in http/*.http against a running server and check the status codes.

    python scripts/run_http_files.py [base_url] [output.md]

Understands the subset of the REST Client format used in this repo: `###` titles, `@var = value`,
`# @name x` request names, `{{var}}` / `{{name.response.body.$.field}}` substitution, headers and a JSON body.
A title containing "-> 201" is the expected status; otherwise any 2xx passes.
"""
import re
import sys
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/http-files-run.md"
FILES = ["categories", "products", "inventory", "orders", "search"]

variables = {"baseUrl": BASE}
named: dict[str, dict] = {}
rows = []


def substitute(text: str) -> str:
    def repl(match):
        key = match.group(1).strip()
        chained = re.fullmatch(r"(\w+)\.response\.body\.\$\.(\w+)", key)
        if chained:
            return str(named[chained.group(1)][chained.group(2)])
        return variables[key]

    return re.sub(r"\{\{(.+?)\}\}", repl, text)


client = httpx.Client(timeout=15)
for name in FILES:
    path = Path("http") / f"{name}.http"
    blocks = re.split(r"^###", path.read_text(), flags=re.M)
    for block in blocks[1:]:
        lines = block.splitlines()
        title = lines[0].strip()
        request_name, method, url, headers, body_lines, in_body = None, None, None, {}, [], False
        for line in lines[1:]:
            if method is None:
                if m := re.match(r"#\s*@name\s+(\w+)", line):
                    request_name = m.group(1)
                elif m := re.match(r"@(\w+)\s*=\s*(.+)", line):
                    if m.group(1) != "baseUrl":  # the command-line base URL wins over the file's default
                        variables[m.group(1)] = substitute(m.group(2).strip())
                elif m := re.match(r"(GET|POST|PUT|DELETE|PATCH)\s+(\S+)", line):
                    method, url = m.group(1), m.group(2)
                continue
            if not in_body:
                if line.strip() == "":
                    in_body = True
                elif ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip()] = v.strip()
            else:
                body_lines.append(line)
        if method is None:
            continue
        body = substitute("\n".join(body_lines).strip()) or None
        response = client.request(method, substitute(url), headers=headers, content=body)
        if request_name:
            named[request_name] = response.json()
        expected = re.search(r"->\s*(\d{3})", title)
        ok = response.status_code == int(expected.group(1)) if expected else 200 <= response.status_code < 300
        rows.append((f"{name}.http", title.split("  ->")[0][:70], f"{method} {substitute(url).replace(BASE, '')}",
                     expected.group(1) if expected else "2xx", response.status_code, ok))

passed = sum(r[5] for r in rows)
report = [f"# .http collection run against `{BASE}`\n", f"**{passed}/{len(rows)} requests returned the documented status**\n",
          "| File | Request | Call | Expected | Actual | Result |", "|---|---|---|---|---|---|"]
report += [f"| {f} | {t} | `{c}` | {e} | {a} | {'PASS' if ok else 'FAIL'} |" for f, t, c, e, a, ok in rows]
Path(OUT).write_text("\n".join(report) + "\n")
print(f"{passed}/{len(rows)} requests as documented -> {OUT}")
for f, t, c, e, a, ok in rows:
    if not ok:
        print(f"  FAIL {f}: {t} | {c} expected {e} got {a}")
sys.exit(0 if passed == len(rows) else 1)

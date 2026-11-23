#!/usr/bin/env python3
"""Read-only repository structure checker.

Never modifies, moves or deletes files. Secret-pattern hits report only the
pattern name and file:line, never the matched text.

Exit status: 0 clean, 1 integrity findings (or any finding with --strict),
2 usage/environment error (root is not a readable git repository).

Secret scan exclusions (all counted in an info 'secret_scan_skipped' finding):
  * tests/*  - fixtures there deliberately contain fake tokens; scanning them
    would be noise. A real secret committed under tests/ is NOT detected here.
  * binary / non-UTF-8 files
  * files over 2 MB
  * symlinks

CI parsing: every .github/workflows/*.yml|yaml is read as text (no YAML
dependency, since pyyaml is not guaranteed in CI). Backslash continuations
are joined and quotes honoured. Glob arguments are expanded with fnmatch
against tracked files; globs that match nothing and 'compileall' directories
are reported as info 'ci_unknown_coverage' rather than as integrity failures.
"""
import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

SIZE_LIMIT = 500 * 1024
SCAN_LIMIT = 2 * 1024 * 1024
WORKFLOW_DIR = ".github/workflows"

SECRET_PATTERNS = {
    "aws-access-key-id": r"\bAKIA[0-9A-Z]{16}\b",
    "github-token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "slack-token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "openai-style-key": r"\bsk-[A-Za-z0-9_-]{20,}",
    "private-key-block": r"-----BEGIN [A-Z ]*PRIVATE" + r" KEY-----",
    "generic-credential-assignment": (
        r"(?i)\b(?:api[_-]?key|secret|token|passwd|password|access[_-]?token)\b"
        r"\s*[:=]\s*['\"][A-Za-z0-9/+_=.-]{20,}['\"]"),
}
SECRET_RES = {name: re.compile(rx) for name, rx in SECRET_PATTERNS.items()}

IGNORE_SUFFIXES = (".sqlite", ".db", ".pem", ".key")
# Always-present notices; visible in output but never fail --strict.
ADVISORY = {"secret_scan_skipped"}
STOP = {"&&", "||", ";", "|", "&", ">", ">>", "2>&1"}
REF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")


class RootError(Exception):
    pass


def git_lines(root, *args):
    try:
        proc = subprocess.run(["git", "-C", str(root), *args, "-z"],
                              capture_output=True, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise RootError(f"cannot read git repository at {root}: "
                        f"{type(exc).__name__}") from exc
    return [p.decode("utf-8", "replace") for p in proc.stdout.split(b"\0") if p]


def finding(check, severity, path, detail, line=None):
    return {"check": check, "severity": severity, "path": path, "line": line, "detail": detail}


def is_glob(arg):
    return any(c in arg for c in "*?[")


def split_command(line):
    try:
        return shlex.split(line)
    except ValueError:
        return line.replace('"', " ").replace("'", " ").split()


def args_after(tokens, i, suffix):
    out = []
    for t in tokens[i + 1:]:
        if t in STOP or t.startswith((";", "#")):
            break
        if t.startswith("-"):
            continue
        t = t.rstrip(";")
        if t.endswith(suffix) or is_glob(t):
            out.append(t)
    return out


def parse_workflows(root):
    """Return kind -> set of path/glob arguments found in all workflows."""
    found = {"py": set(), "node_check": set(), "node_run": set(), "compileall": set()}
    wdir = Path(root, WORKFLOW_DIR)
    files = sorted(p for p in wdir.iterdir() if p.suffix in (".yml", ".yaml")) \
        if wdir.is_dir() else []
    for wf in files:
        text = wf.read_text(encoding="utf-8", errors="replace").replace("\\\n", " ")
        for line in text.splitlines():
            tokens = split_command(line)
            for i, t in enumerate(tokens):
                if t == "py_compile":
                    found["py"].update(args_after(tokens, i, ".py"))
                elif t == "compileall":
                    found["compileall"].update(
                        a for a in tokens[i + 1:] if not a.startswith("-") and a not in STOP)
                elif t == "node":
                    rest = tokens[i + 1:]
                    if rest and rest[0] == "--check":
                        found["node_check"].update(args_after(tokens, i + 1, ".js"))
                    elif rest and not rest[0].startswith("-") and rest[0].endswith(".js"):
                        found["node_run"].add(rest[0])
    return found


def resolve_args(args, tracked, out):
    """Expand CI arguments to tracked paths; unmatched globs are info only."""
    covered, literal = set(), set()
    for a in sorted(args):
        if is_glob(a):
            hits = [p for p in tracked if fnmatch.fnmatchcase(p, a)]
            covered.update(hits)
            if not hits:
                out.append(finding("ci_unknown_coverage", "info", a,
                                   "CI glob matches no tracked file; coverage unknown"))
        else:
            covered.add(a)
            literal.add(a)
    return covered, literal


def check_ci_coverage(root, tracked, out):
    ci = parse_workflows(root)
    py, py_literal = resolve_args(ci["py"], tracked, out)
    node_check, js_literal = resolve_args(ci["node_check"], tracked, out)
    node_run = set(ci["node_run"])
    for d in sorted(ci["compileall"]):
        stem = d.rstrip("/")
        prefix = "" if stem in (".", "") else stem + "/"
        hits = [p for p in tracked if p.endswith(".py") and p.startswith(prefix)]
        py.update(hits)
        out.append(finding("ci_unknown_coverage", "info", d,
                           f"compileall target covers {len(hits)} tracked .py file(s); "
                           "treated as covered"))
    modules = sorted(p for p in tracked if p.endswith(".py") and "/" not in p
                     and not Path(root, p).is_symlink())
    for mod in modules:
        if mod not in py:
            out.append(finding("py_not_compiled", "integrity", mod,
                               "top-level module not in any py_compile list under "
                               + WORKFLOW_DIR))
    for ref in sorted(py_literal | js_literal | node_run):
        if not Path(root, ref).is_file():
            out.append(finding("ci_missing_file", "integrity", ref,
                               "referenced by a workflow under " + WORKFLOW_DIR
                               + " but missing"))
    for js in sorted(p for p in tracked if re.fullmatch(r"web/[^/]+\.js", p)):
        if js not in node_check:
            out.append(finding("js_not_checked", "integrity", js,
                               "no 'node --check' entry in CI"))
    for js in sorted(p for p in tracked if re.fullmatch(r"tests/[^/]+\.test\.js", p)):
        if js not in node_run and js not in node_check:
            out.append(finding("js_test_not_run", "integrity", js,
                               "no node test step in CI"))
    return modules


def check_untested(root, tracked, modules, out):
    tests = [p for p in tracked if p.startswith("tests/") and p.endswith(".py")]
    bodies = [Path(root, t).read_text(encoding="utf-8", errors="replace") for t in tests]
    for mod in modules:
        name = mod[:-3]
        if f"tests/test_{name}.py" in tests:
            continue
        rx = re.compile(rf"^\s*(?:import|from)\s+{re.escape(name)}\b", re.M)
        if not any(rx.search(b) for b in bodies):
            out.append(finding("py_untested", "info", mod,
                               "no tests/test_<module>.py and no test imports it"))


def link_targets(line):
    """Yield targets of inline links (balanced parens, <...>) and reference defs."""
    line = re.sub(r"`[^`]*`", "", line)
    m = REF_RE.match(line)
    if m:
        yield m.group(1).strip("<>")
    for m in re.finditer(r"\]\(", line):
        i = m.end()
        while i < len(line) and line[i] == " ":
            i += 1
        if i < len(line) and line[i] == "<":
            j = line.find(">", i)
            if j > 0:
                yield line[i + 1:j]
            continue
        depth, j = 1, i
        while j < len(line) and depth:
            ch = line[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == " " and depth == 1:
                break
            j += 1
        if j > i:
            yield line[i:j]


def check_doc_links(root, tracked, out):
    for doc in sorted(p for p in tracked if re.fullmatch(r"docs/.*\.md", p)):
        full = Path(root, doc)
        if full.is_symlink() or not full.is_file():
            continue
        base = full.parent
        fence = None
        text = full.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            marker = line.lstrip()[:3]
            if marker in ("```", "~~~"):
                fence = None if fence == marker else (fence or marker)
                continue
            if fence:
                continue
            for target in link_targets(line):
                if re.match(r"(?i)(https?:|mailto:|#|[a-z][a-z0-9+.-]*:)", target):
                    continue
                rel = target.split("#", 1)[0].split("?", 1)[0]
                if rel.startswith("/"):
                    out.append(finding("absolute_link", "info", doc,
                                       "absolute link not resolved: " + rel, n))
                elif rel and not (base / unquote(rel)).exists():
                    out.append(finding("broken_link", "info", doc,
                                       f"broken relative link: {rel}", n))


def check_files(root, tracked, out):
    for p in tracked:
        full = Path(root, p)
        if full.is_file() and not full.is_symlink() and full.stat().st_size > SIZE_LIMIT:
            out.append(finding("large_file", "info", p,
                               f"{full.stat().st_size} bytes exceeds {SIZE_LIMIT}"))
        if full.is_symlink() and not full.exists():
            out.append(finding("dangling_symlink", "info", p, "tracked symlink target missing"))
    skipped = {"tests": 0, "binary": 0, "oversize": 0, "symlink": 0}
    for p in tracked:
        full = Path(root, p)
        if full.is_symlink():
            skipped["symlink"] += 1
            continue
        if not full.is_file():
            continue
        if p.startswith("tests/"):
            skipped["tests"] += 1
            continue
        if full.stat().st_size > SCAN_LIMIT:
            skipped["oversize"] += 1
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped["binary"] += 1
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in SECRET_RES.items():
                if rx.search(line):
                    out.append(finding("secret_pattern", "integrity", p,
                                       f"matches {name} (value withheld)", n))
    out.append(finding("secret_scan_skipped", "info", "(secret scan)",
                       "files not scanned: " + " ".join(f"{k}={v}" for k, v in skipped.items())))
    for p in tracked:
        name = p.rsplit("/", 1)[-1]
        bad = (name == ".env" or (name.startswith(".env.") and name != ".env.example")
               or name.endswith(IGNORE_SUFFIXES) or ".sqlite" in name
               or p.startswith("data/private/"))
        if bad:
            out.append(finding("tracked_should_be_ignored", "integrity", p,
                               "tracked path that should be ignored"))
    for p in git_lines(root, "ls-files", "--others", "--exclude-standard"):
        out.append(finding("untracked", "info", p, "untracked and not ignored"))


def run_checks(root):
    root = Path(root)
    if not root.is_dir():
        raise RootError(f"root is not a directory: {root}")
    tracked = [p for p in git_lines(root, "ls-files") if os.path.lexists(Path(root, p))]
    out = []
    modules = check_ci_coverage(root, tracked, out)
    check_untested(root, tracked, modules, out)
    check_doc_links(root, tracked, out)
    check_files(root, tracked, out)
    counts = {"integrity": 0, "info": 0}
    for f in out:
        counts[f["severity"]] += 1
    return {"root": str(root), "counts": counts, "findings": out}


def exit_code(report, strict=False):
    severities = {f["severity"] for f in report["findings"]
                  if f.get("check") not in ADVISORY}
    if "integrity" in severities or (strict and "info" in severities):
        return 1
    return 0


def render_text(report):
    c = report.get("counts", {})
    lines = ["# Structure check", "",
             f"integrity: {c.get('integrity', 0)}  info: {c.get('info', 0)}", ""]
    for sev in ("integrity", "info"):
        items = [f for f in report["findings"] if f["severity"] == sev]
        if not items:
            continue
        lines += [f"## {sev}", ""]
        for f in items:
            loc = f["path"] + (f":{f['line']}" if f["line"] else "")
            lines.append(f"- [{f['check']}] {loc} - {f['detail']}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Read-only repository structure checker.",
        epilog="Secret scan excludes tests/*, binary or non-UTF-8 files, files over 2 MB "
               "and symlinks; skipped counts are reported as an info finding. "
               "Exit: 0 ok, 1 integrity findings (or any with --strict), 2 bad root.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--strict", action="store_true", help="info findings also fail")
    args = ap.parse_args(argv)
    try:
        report = run_checks(args.root)
    except RootError as exc:
        print(f"structure_check: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return exit_code(report, args.strict)


if __name__ == "__main__":
    sys.exit(main())

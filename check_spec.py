"""Resolve a law's path from a .legalize.yml, per Legalize Format Spec v0.4.

Two modes:

  python3 check_spec.py
      Self-test: parses the 3 example manifests embedded in SPEC.md and checks
      resolve() against their worked examples. No repo needed. This is what CI runs.

  python3 check_spec.py <repo_dir> [<repo_dir> ...]
      Runs the self-test, then validates each given country repo's real
      `.legalize.yml` against a sample of its actual files: resolve() is fed
      each sampled file's own frontmatter and must reproduce that file's real
      path. This is the check that catches a manifest describing a shape the
      repo isn't actually in.
"""
import hashlib
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def resolve(manifest, directory, identifier, frontmatter=None):
    """Build the path a law resolves to under `manifest`.

    A placeholder is either a value this spec derives (directory, identifier,
    id_sha1_2) or a key of the law's own frontmatter, used verbatim — see
    SPEC.md, §Directory layout. Derived values win on a name collision.
    """
    entries = manifest["layout"]
    star = [e for e in entries if e["directories"] == ["*"]]
    assert len(star) <= 1, "at most one * entry"
    named = [e for e in entries if directory in e["directories"]]
    entry = (named or star or [None])[0]
    if entry is None:
        raise KeyError(f"no entry for directory {directory!r}")
    derived = {
        "directory": directory,
        "identifier": identifier,
        "id_sha1_2": hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:2],
    }
    values = {**(frontmatter or {}), **derived}
    return entry["path"].format(**values)


def _read_frontmatter(path: Path) -> dict:
    """The YAML block at the top of a law file. Read line by line — a law's
    body runs to hundreds of KB and none of it is needed here."""
    lines = []
    with path.open(encoding="utf-8") as handle:
        if handle.readline().rstrip("\n") != "---":
            return {}
        for line in handle:
            if line.rstrip("\n") == "---":
                break
            lines.append(line)
    parsed = yaml.safe_load("".join(lines))
    return parsed if isinstance(parsed, dict) else {}


def check_repo(repo_dir: str, sample_per_directory: int = 5) -> bool:
    """Validate a real repo's .legalize.yml against a sample of its own files."""
    root = Path(repo_dir)
    manifest_path = root / ".legalize.yml"
    if not manifest_path.exists():
        print(f"FAIL {repo_dir}: no .legalize.yml at repo root")
        return False
    manifest = yaml.safe_load(manifest_path.read_text())

    directories = sorted(
        p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    checked = 0
    ok = True
    for directory in directories:
        sample = sorted((root / directory).rglob("*.md"))[:sample_per_directory]
        for path in sample:
            front = _read_frontmatter(path)
            identifier = front.get("identifier")
            if not identifier:
                print(f"FAIL {repo_dir}: {path.relative_to(root)} has no identifier")
                ok = False
                continue
            try:
                expected = resolve(manifest, directory, identifier, front)
            except KeyError as exc:
                print(f"FAIL {repo_dir}: {path.relative_to(root)} — {exc}")
                ok = False
                continue
            actual = str(path.relative_to(root))
            checked += 1
            if expected != actual:
                print(
                    f"FAIL {repo_dir}: {actual} resolves to {expected!r} via its own "
                    f"manifest — they should be the same path"
                )
                ok = False
    status = "PASS" if ok else "FAIL"
    print(f"{status} {repo_dir}: {checked} files sampled against .legalize.yml")
    return ok


def self_test() -> None:
    spec = (ROOT / "SPEC.md").read_text()
    blocks = re.findall(r"```yaml\n(.*?)```", spec, re.S)
    mans = [yaml.safe_load(b) for b in blocks if "layout:" in b]
    fr, pt, fallback = mans[0], mans[1], mans[2]

    assert resolve(fr, "fr", "LEGITEXT000006069414") == "fr/LEGITEXT000006069414.md"
    assert resolve(pt, "pt", "DRE-DEC-13-1975") == "pt/b3/DRE-DEC-13-1975.md"
    assert resolve(pt, "pt-20", "DRE-DECLEGREG-18-2000-M") == "pt-20/DRE-DECLEGREG-18-2000-M.md"
    assert resolve(pt, "pt-99", "X") == "pt-99/X.md"          # * catches the rest
    assert resolve(fallback, "es", "BOE-A-1978-31229") == "es/BOE-A-1978-31229.md"

    # order must not matter
    flipped = {"layout": list(reversed(pt["layout"]))}
    assert resolve(flipped, "pt", "DRE-DEC-13-1975") == "pt/b3/DRE-DEC-13-1975.md"

    # a repo with no * and an unlisted directory must fail, not guess
    try:
        resolve({"layout": [{"directories": ["pt"], "path": "{directory}/{identifier}.md"}]}, "pt-20", "X")
        raise AssertionError("should have failed")
    except KeyError:
        pass

    # a placeholder that is neither derived nor in the law's own frontmatter
    # must fail, not guess
    try:
        resolve({"layout": [{"directories": ["*"], "path": "{directory}/{nonexistent}/{identifier}.md"}]}, "pt", "X")
        raise AssertionError("should have failed")
    except KeyError:
        pass

    # a frontmatter field IS a valid placeholder — {year} is the real shape
    # Portugal's own repo ships today (src/legalize/layout.py::LAYOUT["pt"]).
    # This is the case the placeholder vocabulary being wrongly closed used to
    # reject: see the git history of this file.
    year_sharded = {"layout": [{"directories": ["*"], "path": "{directory}/{year}/{identifier}.md"}]}
    resolved = resolve(year_sharded, "pt", "DRE-1998-315-239980", {"year": "1998"})
    assert resolved == "pt/1998/DRE-1998-315-239980.md", resolved

    # the spec's own test vectors
    for ident, bucket in [("BOE-A-1978-31229", "bb"), ("SFS-1962-700", "8a"), ("LEGITEXT000006069414", "0c")]:
        assert hashlib.sha1(ident.encode()).hexdigest()[:2] == bucket, ident
        assert f"| `{ident}`" in spec and f"`{bucket}`" in spec

    print("ok — 3 manifests parsed from SPEC.md, 12 assertions passed")


if __name__ == "__main__":
    self_test()
    all_ok = True
    for repo_dir in sys.argv[1:]:
        all_ok = check_repo(repo_dir) and all_ok
    if not all_ok:
        sys.exit(1)

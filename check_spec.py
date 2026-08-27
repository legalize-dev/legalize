"""Resolve a law's path from a .legalize.yml, per Legalize Format Spec v0.4.

Two modes:

  python3 check_spec.py
      Self-test: parses the 3 example manifests embedded in SPEC.md, checks
      resolve() against their worked examples, then runs check_repo() over a
      throwaway repo built in a temp dir. No country checkout needed. This is
      what CI runs.

  python3 check_spec.py <repo_dir> [<repo_dir> ...]
      Runs the self-test, then validates each given country repo against a
      sample of its actual files: resolve() is fed each sampled file's own
      frontmatter and must reproduce that file's real path. This is the check
      that catches a manifest describing a shape the repo isn't actually in.
      A repo with no `.legalize.yml` predates the manifest and is checked
      against the pre-spec default layout — SPEC.md, §Conformance.
"""
import contextlib
import hashlib
import io
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def _spec_manifests() -> list:
    """The example manifests embedded in SPEC.md, in document order: the flat
    one, pt's two-entry one, and the pre-spec fallback — which carries no
    `spec_version` because a repo predating the manifest declares nothing."""
    blocks = re.findall(r"```yaml\n(.*?)```", (ROOT / "SPEC.md").read_text(), re.S)
    return [yaml.safe_load(b) for b in blocks if "layout:" in b]


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
    """Validate a real repo against a sample of its own files, using its
    .legalize.yml or — when it has none — the pre-spec default layout."""
    root = Path(repo_dir)
    manifest_path = root / ".legalize.yml"
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text())
        against = ".legalize.yml"
    else:
        # SPEC.md, §Conformance: a repo with no manifest predates it, and a
        # consumer MUST read it with the flat default layout. Failing here
        # declared 31 of the 32 country repos broken when only `pt` had shipped
        # a manifest — that was the verifier being wrong, not the repos. A repo
        # that is not actually flat still fails below, on its own files.
        manifest = _spec_manifests()[2]
        against = "the pre-spec default layout (no .legalize.yml)"

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
                    f"FAIL {repo_dir}: {actual} resolves to {expected!r} via "
                    f"{against} — they should be the same path"
                )
                ok = False
    if checked == 0:
        # Without a manifest to miss, an empty directory would otherwise pass
        # green: a clone with no working tree, or a path that is not a repo.
        print(f"FAIL {repo_dir}: no law files sampled — is this a repo checkout?")
        ok = False
    status = "PASS" if ok else "FAIL"
    print(f"{status} {repo_dir}: {checked} files sampled against {against}")
    return ok


def self_test() -> None:
    spec = (ROOT / "SPEC.md").read_text()
    fr, pt, fallback = _spec_manifests()

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

    # check_repo's two modes, on a repo built here. A repo with no manifest is
    # read with the pre-spec default layout instead of being called broken, and
    # one whose files are not laid out that way still fails on its own files.
    log = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(log):
        law = '---\nidentifier: "{}"\ncountry: "uy"\n---\ntext\n'
        assert check_repo(tmp) is False, log.getvalue()  # an empty dir is no repo
        (Path(tmp) / "uy").mkdir()
        (Path(tmp) / "uy/UY-ley-1.md").write_text(law.format("UY-ley-1"), encoding="utf-8")
        assert check_repo(tmp) is True, log.getvalue()
        (Path(tmp) / "uy/1998").mkdir()
        (Path(tmp) / "uy/1998/UY-ley-2.md").write_text(law.format("UY-ley-2"), encoding="utf-8")
        assert check_repo(tmp) is False, log.getvalue()
    assert "pre-spec default layout" in log.getvalue(), log.getvalue()

    print("ok — 3 manifests parsed from SPEC.md, 16 assertions passed")


if __name__ == "__main__":
    self_test()
    all_ok = True
    for repo_dir in sys.argv[1:]:
        all_ok = check_repo(repo_dir) and all_ok
    if not all_ok:
        sys.exit(1)

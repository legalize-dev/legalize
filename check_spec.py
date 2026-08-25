"""Resolve a law's path from a .legalize.yml, per Legalize Format Spec v0.4."""
import hashlib, re, sys, yaml

def resolve(manifest, directory, identifier):
    entries = manifest["layout"]
    star = [e for e in entries if e["directories"] == ["*"]]
    assert len(star) <= 1, "at most one * entry"
    named = [e for e in entries if directory in e["directories"]]
    entry = (named or star or [None])[0]
    if entry is None:
        raise KeyError(f"no entry for directory {directory!r}")
    return entry["path"].format(
        directory=directory,
        identifier=identifier,
        id_sha1_2=hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:2],
    )

spec = open("hub/SPEC.md").read()
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

# an unknown placeholder must fail, not guess
try:
    resolve({"layout": [{"directories": ["*"], "path": "{directory}/{year}/{identifier}.md"}]}, "pt", "X")
    raise AssertionError("should have failed")
except KeyError:
    pass

# the spec's own test vectors
for ident, bucket in [("BOE-A-1978-31229","bb"), ("SFS-1962-700","8a"), ("LEGITEXT000006069414","0c")]:
    assert hashlib.sha1(ident.encode()).hexdigest()[:2] == bucket, ident
    assert f"| `{ident}`" in spec and f"`{bucket}`" in spec

print("ok — 3 manifests parsed from SPEC.md, 10 assertions passed")

#!/usr/bin/env python3
"""Check a country repo against the Legalize Format Spec.

Two layers, and the split between them is the whole design.

**The vocabulary is read from SPEC.md itself.** The field names and which of
them are mandatory, the ``status`` values, the commit types, the trailer keys,
the ``text_state`` values and the notices that go with them, the derived
placeholders, the pipeline's git identity, the epoch floor, the worked
manifests and the test vectors — none of it is written down a second time here.
A spec edit that adds a ``status`` value, a commit type or a placeholder is
picked up by this file with no code change at all.

**The rules are code**, one function per section, each tagged with the section
it implements. A spec edit that adds a *rule* still needs a function — prose
cannot be executed and pretending otherwise is how a checker ends up agreeing
with a spec it no longer implements. What this file does instead is notice:
every section of SPEC.md is either claimed by a rule or listed in ``UNCHECKED``
with the reason, and a section that is neither fails the run. A v0.5 that adds
a section therefore breaks this file loudly on the first run rather than
passing green while checking nothing.

To add a rule: write the function, then append an entry to ``RULES`` — the
fields are documented above the array, and ``--list`` is how the set is read.
A clause with nothing executable behind it goes in ``UNCHECKED`` with its
reason, which is a claim someone can argue with rather than a silent omission.

The same trick guards the parsing. Every value pulled out of the prose is
asserted to look like itself — five-odd status values, three-odd trailer keys —
so a reworded sentence raises here instead of silently yielding an empty list
that every repo then conforms to.

**Which SPEC.md?** The one the repo says it conforms to. ``.legalize.yml``
declares ``spec_version``, and SPEC.md carries its own version in its H1, so
the revision to read is found by walking the document's git history. There are
no tags to keep and nothing to remember to bump. That is what lets one script
check a v0.4 repo and a v0.5 repo on the same afternoon: each is read against
the vocabulary it claims.

Usage::

    python3 check_spec.py                       self-test only — what CI runs
    python3 check_spec.py ../countries/es        check a repo, spec auto-resolved
    python3 check_spec.py --spec HEAD~3 <repo>   pin the spec to a git revision
    python3 check_spec.py --files-only <repo>    skip the git-history rules
    python3 check_spec.py --sample 5 <repo>      N files per directory, not all

Exits non-zero on any violation.
"""
import argparse
import contextlib
import hashlib
import io
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — the spec, read from SPEC.md
# ─────────────────────────────────────────────────────────────────────────────


class SpecError(Exception):
    """SPEC.md does not say what this file needs to read out of it.

    Raised rather than returning an empty vocabulary, because an empty
    vocabulary is a checker that passes everything.
    """


def _flat(text: str) -> str:
    """Prose with its hard wrapping removed, so a regex can span a line break.

    Applied per region and never to the whole document: it would run the rows
    of every table into one line.
    """
    return re.sub(r"\s*\n\s*", " ", text)


def _section(text: str, title: str) -> str:
    """One section of SPEC.md, up to the next heading of the same level or higher."""
    head = re.search(rf"^(#{{2,4}}) {re.escape(title)}\s*$", text, re.M)
    if head is None:
        raise SpecError(f"SPEC.md has no section titled {title!r}")
    rest = text[head.end() :]
    nxt = re.search(rf"^#{{1,{len(head.group(1))}}} ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _cells(row: str) -> list[str]:
    """The cells of one markdown table row."""
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _at_least(value, n: int, what: str):
    """A vocabulary that came back too small means the prose moved under us."""
    if len(value) < n:
        raise SpecError(
            f"read only {len(value)} {what} out of SPEC.md, expected at least {n} — "
            f"the wording this file parses has changed; fix the parser, do not lower the floor"
        )
    return value


def load_spec(text: str) -> dict:
    """The machine-readable half of one version of SPEC.md."""
    spec: dict = {}

    version = re.search(r"^# Legalize Format Spec v([\d.]+)", text, re.M)
    if version is None:
        raise SpecError("SPEC.md has no '# Legalize Format Spec vX.Y' heading")
    spec["version"] = version.group(1)

    # Every section, so a rule set that has fallen behind the document can say so.
    spec["sections"] = re.findall(r"^#{2,4} (.+?)\s*$", text, re.M)

    # The worked manifests, in document order: the flat one, pt's two-entry one,
    # and the pre-spec fallback — which carries no `spec_version` because a repo
    # predating the manifest declares nothing.
    spec["manifests"] = _at_least(
        [yaml.safe_load(b) for b in re.findall(r"```yaml\n(.*?)```", text, re.S) if "layout:" in b],
        3,
        "worked manifests",
    )

    # ── §YAML frontmatter ──
    fm = _section(text, "YAML frontmatter")
    rows = [_cells(r) for r in re.findall(r"^\|.*\|\s*$", fm, re.M)]
    rows = [r for r in rows if len(r) == 3 and r[0].startswith("`")]
    spec["fields"] = _at_least([r[0].strip("`") for r in rows], 8, "frontmatter fields")
    # A date field is one the table types as an ISO 8601 date — asked of the
    # document rather than hardcoded, so a fourth one arrives here on its own.
    spec["date_fields"] = _at_least(
        [r[0].strip("`") for r in rows if "ISO 8601 date" in r[2]], 2, "date fields"
    )
    # "Six of them — `title`, ... — are always present"
    always = re.search(r"— ((?:`\w+`[,\s]+(?:and\s+)?)+)— are always present", _flat(fm))
    if always is None:
        raise SpecError("§YAML frontmatter no longer names the always-present fields")
    spec["mandatory"] = _at_least(re.findall(r"`(\w+)`", always.group(1)), 5, "mandatory fields")
    status_row = next(r for r in rows if r[0] == "`status`")
    spec["status_values"] = _at_least(re.findall(r"`(\w+)`", status_row[2]), 4, "status values")
    # The prohibited placeholders, from the sentence that forbids them. "Today"
    # is named there too and is deliberately not collected: a law legitimately
    # amended today carries today's date, so the two are indistinguishable from
    # the outside. The epoch is added because the spec names it in words.
    spec["date_sentinels"] = _at_least(
        re.findall(r"`(\d{4}-\d{2}-\d{2})`", _flat(fm)) + ["1970-01-01"], 2, "date sentinels"
    )

    # ── §Directory layout ──
    layout = _section(text, "Directory layout")
    spec["derived"] = _at_least(
        re.findall(r"^\| `\{(\w+)\}`\s*\|", layout, re.M), 3, "derived placeholders"
    )
    spec["vectors"] = dict(
        _at_least(
            re.findall(r"^\| `([\w-]+)`\s*\| `([0-9a-f]{2})`\s*\|", layout, re.M), 3, "test vectors"
        )
    )

    # ── §Text state ──
    ts = _section(text, "Text state")
    spec["text_states"] = _at_least(
        re.findall(r"^\| `(\w+)`\s*\|", ts, re.M), 3, "text_state values"
    )
    # Absent means this one, and the sentence that says so is the source.
    default = re.search(r"If `text_state` is absent, the file is `(\w+)`", _flat(ts))
    if default is None:
        raise SpecError("§Text state no longer names the default for an absent text_state")
    spec["text_state_default"] = default.group(1)
    # The notices are byte-identical in every file by design, so they are
    # compared byte for byte and therefore read byte for byte.
    spec["notices"] = {
        value: notice.strip()
        for value, notice in re.findall(r"For `(\w+)`:\n\n```markdown\n(.*?)```", ts, re.S)
    }
    _at_least(spec["notices"], 2, "text_state notices")

    # ── §Commit format ──
    commit = _section(text, "Commit format")
    block = re.search(r"```\n(.*?)```", commit, re.S)
    if block is None:
        raise SpecError("§Commit format has no worked commit block")
    spec["trailers"] = _at_least(
        re.findall(r"^([A-Z][\w-]*):", block.group(1), re.M), 3, "trailer keys"
    )
    types = re.search(r"^Types: (.+)$", commit, re.M)
    if types is None:
        raise SpecError("§Commit format no longer lists the commit types")
    spec["commit_types"] = _at_least(
        re.findall(r"`\[([\w-]+)\]`", types.group(1)), 5, "commit types"
    )

    # ── §Dates ──
    dates = _flat(_section(text, "Dates"))
    floor = re.search(r"clamped to `?(\d{4}-\d{2}-\d{2})`?", dates)
    if floor is None:
        raise SpecError("§Dates no longer states the epoch floor")
    spec["epoch_floor"] = floor.group(1)

    # ── §Git identity ──
    identity = re.search(r"`(\w[\w ]*<[^>]+>)`", _flat(_section(text, "Git identity")))
    if identity is None:
        raise SpecError("§Git identity no longer names the pipeline identity")
    spec["identity"] = identity.group(1)

    return spec


def spec_text_for(version: str | None, ref: str | None) -> tuple[str, str]:
    """The SPEC.md to check against, and a human-readable note on where it came from.

    An explicit ``ref`` wins. Otherwise the working copy is used when it already
    is the version the repo claims, and failing that the document's own git
    history is walked for the revision whose H1 carries that version. No tags,
    no registry: the version lives in the document, so the document is the index.
    """

    def show(rev: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{rev}:SPEC.md"],
            capture_output=True,
            text=True,
        )
        if out.returncode != 0:
            raise SpecError(f"cannot read SPEC.md at {rev}: {out.stderr.strip()}")
        return out.stdout

    if ref:
        # A path when there is a file there, a git revision otherwise. The path
        # form is what lets a draft of the next version be run against a real
        # corpus before it is committed to anything.
        if Path(ref).is_file():
            return Path(ref).read_text(encoding="utf-8"), ref
        return show(ref), f"SPEC.md at {ref}"

    working = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    if version is None or load_spec(working)["version"] == version:
        return working, f"SPEC.md v{load_spec(working)['version']} (working copy)"

    log = subprocess.run(
        ["git", "-C", str(ROOT), "log", "--format=%H", "--", "SPEC.md"],
        capture_output=True,
        text=True,
    )
    for sha in log.stdout.split():
        try:
            candidate = show(sha)
            if re.search(rf"^# Legalize Format Spec v{re.escape(version)}\b", candidate, re.M):
                return candidate, f"SPEC.md v{version} (at {sha[:10]})"
        except SpecError:
            continue
    raise SpecError(
        f"the repo declares spec_version {version!r} and no revision of SPEC.md carries it — "
        f"the working copy is v{load_spec(working)['version']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The repo under test
# ─────────────────────────────────────────────────────────────────────────────

# Separators git is asked to emit (`%x00`, `%x01` in the format string) and
# then finds in the output. Written as escapes rather than as the bytes
# themselves: a real NUL cannot travel through argv.
_NUL = "\x00"
_REC = "\x01"


class Repo:
    """One country checkout, read once and handed to every rule."""

    def __init__(self, path: str, sample: int | None = None):
        self.root = Path(path)
        self.name = path
        manifest_path = self.root / ".legalize.yml"
        self.has_manifest = manifest_path.exists()
        self.manifest = (
            yaml.safe_load(manifest_path.read_text(encoding="utf-8")) if self.has_manifest else None
        )
        # A repo with no manifest predates it, and §Conformance says a consumer
        # MUST read it with the flat default. Failing here instead declared 31
        # of 32 conforming repos broken when only pt had shipped one.
        self.laws: list[tuple[str, str, dict]] = []  # (relpath, directory, frontmatter)
        for directory in sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")
        ):
            found = sorted((self.root / directory).rglob("*.md"))
            for path in found[:sample] if sample else found:
                self.laws.append(
                    (
                        path.relative_to(self.root).as_posix(),
                        directory,
                        _read_head(path)[0],
                    )
                )
        self._commits: list[dict] | None = None

    def head(self, relpath: str) -> tuple[dict, list[str]]:
        return _read_head(self.root / relpath)

    @property
    def commits(self) -> list[dict]:
        """Every commit, with its trailers parsed — and no tree ever touched.

        ``--name-only`` would say which file each commit changed and costs a
        tree diff per commit: 74 minutes on a real corpus where walking the
        commits alone takes seconds. It is not needed. Each commit on a law
        carries ``Norm-Id``, so the law a commit belongs to is in the message.
        """
        if self._commits is None:
            fmt = "%x01" + "%x00".join(["%H", "%an <%ae>", "%cn <%ce>", "%aI", "%s", "%b"])
            out = subprocess.run(
                ["git", "-C", str(self.root), "log", f"--format={fmt}"],
                capture_output=True,
                text=True,
            )
            self._commits = []
            for record in out.stdout.split(_REC):
                if not record.strip():
                    continue
                parts = record.split(_NUL)
                if len(parts) < 6:
                    continue
                sha, author, committer, adate, subject, body = parts[:6]
                trailers = dict(re.findall(r"^([A-Z][\w-]*): *(.+?)\s*$", body, re.M))
                self._commits.append(
                    {
                        "sha": sha.strip(),
                        "author": author,
                        "committer": committer,
                        "author_date": adate[:10],
                        "subject": subject,
                        "trailers": trailers,
                    }
                )
            self._commits.reverse()  # oldest first, which is the order rules read in
        return self._commits


def _read_head(path: Path, body_lines: int = 12) -> tuple[dict, list[str]]:
    """A law's frontmatter and the opening of its body.

    Read line by line and stopped early: a law's body runs to hundreds of
    kilobytes and only its first few lines are ever needed here.
    """
    front: list[str] = []
    body: list[str] = []
    try:
        with path.open(encoding="utf-8") as handle:
            if handle.readline().rstrip("\n") != "---":
                return {}, []
            for line in handle:
                if line.rstrip("\n") == "---":
                    break
                front.append(line)
            else:
                return {}, []
            for line in handle:
                body.append(line.rstrip("\n"))
                if len(body) >= body_lines:
                    break
    except OSError:
        return {}, []
    try:
        parsed = yaml.safe_load("".join(front))
    except yaml.YAMLError as exc:
        return {"__unparseable__": str(exc).splitlines()[0]}, body
    return (parsed if isinstance(parsed, dict) else {}), body


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


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — the rules, one per section of SPEC.md
# ─────────────────────────────────────────────────────────────────────────────
#
# Each yields a message per violation. Nothing yielded is a pass. A rule reads
# its vocabulary out of `spec` and never hardcodes it, so the sections below
# stay put while the document moves.

# Sections that carry no executable rule, and why. A section in neither this
# set nor RULES fails the run — that is what makes a v0.5 loud.
UNCHECKED = {
    "Conformance": "covered by manifest_declared and paths_resolve",
    "Mandatory (all countries)": "a container for the sections below it",
    "Directories": "covered by paths_resolve, which resolves {directory} per file",
    "Sharding": "RECOMMENDED, not required — a conforming repo may be flat",
    "Choosing a shard key": "guidance for choosing a template, not a constraint on a repo",
    "Repository": "the repo's own name and remote are outside a checkout's contents",
    "Flexible (per country)": "explicitly what this spec does not constrain",
    "Versioning": "governs the document, not a repo",
    "Changelog": "prose",
}


def manifest_declared(spec, repo):
    if not repo.has_manifest:
        yield (
            "no .legalize.yml — the repo predates the manifest and is being read with "
            "the pre-spec default layout"
        )
        return
    declared = str(repo.manifest.get("spec_version") or "")
    if not declared:
        yield ".legalize.yml declares no spec_version"
    elif _newer(declared, spec["version"]):
        # §Conformance: a consumer MUST refuse a repo newer than what it implements.
        yield f"repo declares spec_version {declared}, newer than the spec loaded (v{spec['version']})"
    country = repo.manifest.get("country")
    if not country:
        yield ".legalize.yml declares no country"
    else:
        wrong = {f.get("country") for _, _, f in repo.laws if f.get("country") != country}
        for value in sorted(x for x in wrong if x is not None):
            yield f"manifest says country {country!r} but a law says {value!r}"
    star = [e for e in repo.manifest.get("layout", []) if e.get("directories") == ["*"]]
    if len(star) > 1:
        yield f"{len(star)} layout entries use ['*']; at most one may"


def paths_resolve(spec, repo):
    manifest = repo.manifest if repo.has_manifest else spec["manifests"][2]
    for relpath, directory, front in repo.laws:
        identifier = front.get("identifier")
        if not identifier:
            yield f"{relpath} has no identifier"
            continue
        try:
            want = resolve(manifest, directory, identifier, front)
        except KeyError as exc:
            yield f"{relpath} — {exc}"
            continue
        if want != relpath:
            yield f"{relpath} resolves to {want!r} — they should be the same path"


def frontmatter_complete(spec, repo):
    sentinels = set(spec["date_sentinels"])
    for relpath, directory, front in repo.laws:
        if "__unparseable__" in front:
            yield f"{relpath} — frontmatter is not valid YAML: {front['__unparseable__']}"
            continue
        if not front:
            yield f"{relpath} has no frontmatter"
            continue
        for field in spec["mandatory"]:
            if not str(front.get(field) or "").strip():
                yield f"{relpath} — mandatory field {field!r} is missing or empty"
        status = front.get("status")
        if status is not None and status not in spec["status_values"]:
            yield f"{relpath} — status {status!r} is not one of {spec['status_values']}"
        for field in spec["date_fields"]:
            raw = front.get(field)
            if raw is None:
                continue  # conditional: required only where the source states it
            if _as_date(raw) is None:
                yield f"{relpath} — {field} {raw!r} is not an ISO 8601 date"
            elif str(raw)[:10] in sentinels:
                yield f"{relpath} — {field} is the placeholder {raw!r}; omit the field instead"
        # §Directories: a file's directory is its jurisdiction where it has one.
        jurisdiction = front.get("jurisdiction")
        if jurisdiction is not None and str(jurisdiction) != directory:
            yield f"{relpath} — jurisdiction {jurisdiction!r} is not its directory {directory!r}"


def identifiers_unique(spec, repo):
    seen: dict[str, str] = {}
    for relpath, _, front in repo.laws:
        identifier = front.get("identifier")
        if not identifier:
            continue
        stem = relpath.rsplit("/", 1)[-1][: -len(".md")]
        if stem != str(identifier):
            yield f"{relpath} — file is named {stem!r} but its identifier is {identifier!r}"
        if identifier in seen:
            yield f"identifier {identifier!r} is claimed by {seen[identifier]} and {relpath}"
        else:
            seen[str(identifier)] = relpath


def text_state_declared(spec, repo):
    for relpath, _, front in repo.laws:
        state = front.get("text_state") or spec["text_state_default"]
        if state not in spec["text_states"]:
            yield f"{relpath} — text_state {state!r} is not one of {spec['text_states']}"
            continue
        notice = spec["notices"].get(state)
        if notice is None:
            continue  # the default state carries no notice
        _, body = repo.head(relpath)
        # §Text state puts the notice "immediately after the H1 title", so the
        # H1 is stepped over before comparing. Comparing against the first line
        # of the body instead accused all 8,896 files of a Swedish corpus that
        # carries the notice on every one of them.
        lines = [line for line in body if line.strip()]
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        if not lines or not lines[0].startswith(notice.split("\n")[0]):
            yield (
                f"{relpath} — text_state is {state!r} and the body does not open with "
                f"the notice §Text state requires"
            )


def commit_format(spec, repo):
    types = set(spec["commit_types"])
    required = set(spec["trailers"])
    bad_type: dict[str, str] = {}
    missing: dict[str, int] = defaultdict(int)
    for commit in repo.commits:
        prefix = re.match(r"\[([\w-]+)\]", commit["subject"])
        if prefix is not None and prefix.group(1) not in types:
            bad_type.setdefault(prefix.group(1), commit["sha"][:10])
        # Which commits are legislative records? The spec answers it itself, in
        # §Conformance: repo metadata "carries no Source-Date trailer, so
        # history sync ignores it". Using the same test here is what keeps a
        # meta commit — `[fix-pipeline] Update repository metadata`, which does
        # carry a type — from being asked for trailers it is right not to have.
        # An undated change (§Dates) also carries none and is skipped with it.
        if not commit["trailers"].get("Source-Date"):
            continue
        if prefix is None:
            yield f"{commit['sha'][:10]} carries Source-Date but no [type]: {commit['subject'][:60]}"
        for key in required - set(commit["trailers"]) - {"Source-Date"}:
            missing[key] += 1
    for kind, sha in sorted(bad_type.items()):
        yield f"commit type [{kind}] is not one of {sorted(types)} (e.g. {sha})"
    for key, count in sorted(missing.items()):
        yield f"{count} law commit(s) carry no {key} trailer"


def dates_mirror_source_date(spec, repo):
    """§Dates: a commit's author date MUST be its Source-Date."""
    mismatched = []
    for commit in repo.commits:
        source_date = commit["trailers"].get("Source-Date")
        if not source_date:
            continue
        if source_date[:10] != commit["author_date"]:
            # At or below the epoch git cannot represent the date and the spec
            # clamps it. The comparison is against the floor and not against
            # the epoch itself: a Source-Date of 1970-01-01 is already at the
            # boundary git will not carry, and 283 Swedish commits sit exactly
            # there — reporting them would be this rule misreading its own clause.
            if commit["author_date"] == spec["epoch_floor"] and source_date[:10] <= spec["epoch_floor"]:
                continue
            mismatched.append((commit["sha"][:10], source_date[:10], commit["author_date"]))
    for sha, said, dated in mismatched[:10]:
        yield f"{sha} — Source-Date {said} but author date {dated}"
    if len(mismatched) > 10:
        yield f"…and {len(mismatched) - 10} more commit(s) whose author date is not their Source-Date"


def history_is_per_law(spec, repo):
    """§History: `git log -- {path}` MUST return a law's versions oldest first.

    Read from the ``Norm-Id`` trailer rather than from a tree diff — the
    trailer names the law, so grouping the log by it reconstructs each law's
    sequence without git ever opening a tree.
    """
    by_law: dict[str, list[str]] = defaultdict(list)
    for commit in repo.commits:  # already oldest first
        norm = commit["trailers"].get("Norm-Id")
        source_date = commit["trailers"].get("Source-Date")
        if norm and source_date:
            by_law[norm].append(source_date[:10])
    out_of_order = [
        norm for norm, seq in by_law.items() if any(b < a for a, b in zip(seq, seq[1:]))
    ]
    for norm in sorted(out_of_order)[:10]:
        yield f"{norm} — its commits are not in Source-Date order oldest first"
    if len(out_of_order) > 10:
        yield f"…and {len(out_of_order) - 10} more law(s) whose commits are out of order"

    # "A repo whose history is a single import does not conform." A law the
    # source says was amended, with one commit, is that repo in miniature.
    #
    # Only where the body is the law in force, though. §Text state gives
    # `last_updated` a different meaning in the other two: on `current` and
    # `as_enacted` it is "the date of the most recent amendment recorded", and
    # an as_enacted act's amendments are separate files by design. Reading a
    # later `last_updated` as "this file should have more versions" is true of
    # point_in_time alone — applied to Sweden's `current` corpus it accused
    # 2,071 conforming laws.
    single = [
        relpath
        for relpath, _, front in repo.laws
        if (front.get("text_state") or spec["text_state_default"]) == spec["text_state_default"]
        and (pub := _as_date(front.get("publication_date")))
        and (upd := _as_date(front.get("last_updated")))
        and upd > pub
        and len(by_law.get(str(front.get("identifier")), [])) < 2
    ]
    if single:
        yield (
            f"{len(single)} law(s) whose frontmatter says they were amended have fewer than "
            f"two commits (e.g. {', '.join(single[:3])})"
        )


def git_identity(spec, repo):
    wrong: dict[str, str] = {}
    for commit in repo.commits:
        for who in (commit["author"], commit["committer"]):
            if who != spec["identity"]:
                wrong.setdefault(who, commit["sha"][:10])
    for who, sha in sorted(wrong.items()):
        yield f"{who!r} authored or committed (e.g. {sha}); §Git identity requires {spec['identity']!r}"


def amends_resolves(spec, repo):
    """§Amending acts: `amends` is a list of identifiers as this repo names them."""
    known = {str(f.get("identifier")) for _, _, f in repo.laws if f.get("identifier")}
    dangling = 0
    example = ""
    for relpath, _, front in repo.laws:
        amends = front.get("amends")
        if amends is None:
            continue
        if not isinstance(amends, list):
            yield f"{relpath} — amends is {type(amends).__name__}, not a YAML list"
            continue
        for identifier in amends:
            if str(identifier) not in known:
                dangling += 1
                example = example or f"{relpath} names {identifier!r}"
    if dangling:
        yield f"{dangling} amends entry/entries name no law in this repo ({example})"


# The rule set, as data. One entry per clause this file knows how to execute,
# read top to bottom like a checklist — which is the point: a rule you cannot
# find is a rule nobody maintains.
#
#   section  the part of SPEC.md it implements. Cross-checked against the
#            document's own headings, so a renamed section fails the run.
#   since    the spec version the clause came in at. A repo declaring an older
#            version is not judged by a rule that did not exist for it.
#   needs    "files" reads the working tree; "git" reads the history alone and
#            never opens a tree — which is why the git half stays cheap.
#   checks   what it asserts, in words.
#   probe    the same question asked by hand, for when you want the raw
#            evidence rather than a verdict. Printed by --list.
RULES: list[dict] = [
    {
        "id": "manifest_declared",
        "section": "Conformance",
        "since": "0.4",
        "needs": "files",
        "checks": "The repo declares itself in .legalize.yml, with a spec_version this "
        "checker implements, a country every law agrees with, and at most one ['*'] entry.",
        "probe": "cat {repo}/.legalize.yml",
        "fn": manifest_declared,
    },
    {
        "id": "paths_resolve",
        "section": "Directory layout",
        "since": "0.4",
        "needs": "files",
        "checks": "Every law is where the manifest's path template puts it, filling "
        "placeholders from the spec's derived values and the law's own frontmatter.",
        "probe": "find {repo} -mindepth 2 -type d -not -path '*/.git/*' | head",
        "fn": paths_resolve,
    },
    {
        "id": "frontmatter_complete",
        "section": "YAML frontmatter",
        "since": "0.1",
        "needs": "files",
        "checks": "Every law parses as YAML and carries the mandatory fields, a status the "
        "spec defines, ISO dates that are not placeholders, and a jurisdiction equal to its directory.",
        "probe": "grep -rh '^status:' {repo}/*/*.md | sort | uniq -c",
        "fn": frontmatter_complete,
    },
    {
        "id": "identifiers_unique",
        "section": "Identifiers",
        "since": "0.4",
        "needs": "files",
        "checks": "No identifier is claimed by two laws anywhere in the repo, and every "
        "file is named after the identifier it carries.",
        "probe": "find {repo} -name '*.md' -not -path '*/.git/*' | sed 's|.*/||' | sort | uniq -d | head",
        "fn": identifiers_unique,
    },
    {
        "id": "text_state_declared",
        "section": "Text state",
        "since": "0.3",
        "needs": "files",
        "checks": "text_state is one the spec defines, and a body that is not the default "
        "opens with the static notice, byte for byte.",
        "probe": "grep -rh '^text_state:' {repo}/*/*.md | sort | uniq -c",
        "fn": text_state_declared,
    },
    {
        "id": "amends_resolves",
        "section": "Amending acts",
        "since": "0.3",
        "needs": "files",
        "checks": "Where amends is present it is a YAML list of identifiers this repo "
        "actually names — never the source's own citation strings.",
        "probe": "grep -rl '^amends:' {repo}/*/*.md | head",
        "fn": amends_resolves,
    },
    {
        "id": "commit_format",
        "section": "Commit format",
        "since": "0.2",
        "needs": "git",
        "checks": "Every law commit's [type] is one the spec lists and carries the "
        "trailers; a commit with no [type] carries no Source-Date either.",
        "probe": "git -C {repo} log --format=%s | grep -o '^\\[[a-z-]*\\]' | sort | uniq -c",
        "fn": commit_format,
    },
    {
        "id": "dates_mirror_source_date",
        "section": "Dates",
        "since": "0.4",
        "needs": "git",
        "checks": "A commit's author date is its Source-Date, except below the epoch "
        "where git cannot represent it and the spec clamps.",
        "probe": "git -C {repo} log --format='%ad|%(trailers:key=Source-Date,valueonly)' "
        "--date=short | awk -F'|' '$2 != \"\" && $1 != $2' | head",
        "fn": dates_mirror_source_date,
    },
    {
        "id": "history_is_per_law",
        "section": "History",
        "since": "0.4",
        "needs": "git",
        "checks": "Each law's commits run oldest first by Source-Date, and a law the "
        "frontmatter says was amended has more than the one import commit.",
        "probe": "git -C {repo} log --format='%(trailers:key=Norm-Id,valueonly)' "
        "| sort | uniq -c | sort -rn | head",
        "fn": history_is_per_law,
    },
    {
        "id": "git_identity",
        "section": "Git identity",
        "since": "0.4",
        "needs": "git",
        "checks": "Author and committer are both the pipeline's own identity on every "
        "commit — never the person who happened to run it.",
        "probe": "git -C {repo} log --format='%an <%ae> | %cn <%ce>' | sort | uniq -c",
        "fn": git_identity,
    },
]

NEEDS_GIT = {r["id"] for r in RULES if r["needs"] == "git"}


def applicable(rules: list[dict], spec: dict) -> list[dict]:
    """The rules that exist in this version of the spec.

    A repo conforming to v0.3 is not judged by a clause v0.4 introduced — which
    is the other half of checking two versions with one file.
    """
    return [r for r in rules if not _newer(r["since"], spec["version"])]


def print_rules(spec: dict) -> None:
    print(f"SPEC.md v{spec['version']} — {len(applicable(RULES, spec))} rule(s)\n")
    for r in applicable(RULES, spec):
        print(f"  §{r['section']}  [{r['id']}]  since v{r['since']}, reads {r['needs']}")
        print(f"    {r['checks']}")
        print(f"    $ {r['probe']}\n")
    if UNCHECKED:
        print("  Sections with no executable rule:")
        for section, why in sorted(UNCHECKED.items()):
            print(f"    §{section} — {why}")


def _newer(a: str, b: str) -> bool:
    def parts(v):
        return tuple(int(x) for x in re.findall(r"\d+", v))

    return parts(a) > parts(b)


def rules_cover(spec) -> list[str]:
    """Every section of SPEC.md is claimed by a rule or listed as unchecked."""
    claimed = {r["section"] for r in RULES} | set(UNCHECKED)
    return [s for s in spec["sections"] if s not in claimed]


# ─────────────────────────────────────────────────────────────────────────────
# Running them
# ─────────────────────────────────────────────────────────────────────────────


def check_repo(
    repo_dir: str,
    spec: dict | None = None,
    note: str = "",
    sample: int | None = None,
    files_only: bool = False,
    git_only: bool = False,
) -> bool:
    root = Path(repo_dir)
    declared = None
    manifest_path = root / ".legalize.yml"
    if manifest_path.exists():
        with contextlib.suppress(yaml.YAMLError, OSError):
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            declared = str(loaded.get("spec_version") or "") or None
    if spec is None:
        text, note = spec_text_for(declared, None)
        spec = load_spec(text)

    drift = rules_cover(spec)
    if drift:
        print(
            f"FAIL {repo_dir}: SPEC.md v{spec['version']} has section(s) no rule claims and "
            f"UNCHECKED does not excuse: {', '.join(drift)}"
        )
        return False

    repo = Repo(repo_dir, sample=sample)
    if not repo.laws:
        print(f"FAIL {repo_dir}: no law files found — is this a repo checkout?")
        return False

    print(f"  {repo_dir}: {len(repo.laws)} law file(s) against {note}")
    failures = 0
    for entry in applicable(RULES, spec):
        if files_only and entry["needs"] == "git":
            continue
        if git_only and entry["needs"] != "git":
            continue
        messages = list(entry["fn"](spec, repo))
        for message in messages[:20]:
            print(f"  FAIL §{entry['section']}: {message}")
        if len(messages) > 20:
            print(f"  FAIL §{entry['section']}: …and {len(messages) - 20} more")
        failures += len(messages)

    status = "PASS" if failures == 0 else "FAIL"
    print(f"{status} {repo_dir}: {failures} violation(s)\n")
    return failures == 0


def self_test() -> None:
    """Everything that needs no country checkout. This is what CI runs."""
    text = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    spec = load_spec(text)
    fr, pt, fallback = spec["manifests"]

    assert resolve(fr, "fr", "LEGITEXT000006069414") == "fr/LEGITEXT000006069414.md"
    assert resolve(pt, "pt", "DRE-DEC-13-1975") == "pt/b3/DRE-DEC-13-1975.md"
    assert resolve(pt, "pt-20", "DRE-DECLEGREG-18-2000-M") == "pt-20/DRE-DECLEGREG-18-2000-M.md"
    assert resolve(pt, "pt-99", "X") == "pt-99/X.md"  # * catches the rest
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
    year_sharded = {"layout": [{"directories": ["*"], "path": "{directory}/{year}/{identifier}.md"}]}
    resolved = resolve(year_sharded, "pt", "DRE-1998-315-239980", {"year": "1998"})
    assert resolved == "pt/1998/DRE-1998-315-239980.md", resolved

    # ── the vocabulary this file reads out of SPEC.md ──
    # Asserted against what the document says today, so a spec edit that moves a
    # value shows up as a failing assertion here rather than as a rule that
    # quietly stops checking anything.
    for ident, bucket in spec["vectors"].items():
        assert hashlib.sha1(ident.encode()).hexdigest()[:2] == bucket, ident
    assert len(spec["vectors"]) >= 3, spec["vectors"]
    assert set(spec["derived"]) == {"directory", "identifier", "id_sha1_2"}, spec["derived"]
    assert set(spec["mandatory"]) == {
        "title", "identifier", "country", "rank", "status", "source",
    }, spec["mandatory"]
    assert set(spec["date_fields"]) == {"publication_date", "last_updated"}, spec["date_fields"]
    assert "in_force" in spec["status_values"] and len(spec["status_values"]) == 5, spec["status_values"]
    assert set(spec["trailers"]) == {"Source-Id", "Source-Date", "Norm-Id"}, spec["trailers"]
    assert "bootstrap" in spec["commit_types"] and len(spec["commit_types"]) == 6, spec["commit_types"]
    assert set(spec["text_states"]) == {"point_in_time", "current", "as_enacted"}, spec["text_states"]
    assert spec["text_state_default"] == "point_in_time", spec["text_state_default"]
    assert set(spec["notices"]) == {"as_enacted", "current"}, list(spec["notices"])
    assert spec["identity"] == "Legalize <legalize@legalize.dev>", spec["identity"]
    assert spec["epoch_floor"] == "1970-01-02", spec["epoch_floor"]
    assert "1900-01-01" in spec["date_sentinels"], spec["date_sentinels"]

    # every section of the document is claimed by a rule or excused by name
    assert not rules_cover(spec), rules_cover(spec)

    # a reworded spec must break the parser loudly, never yield an empty vocabulary
    for broken in ("^Types: .+$", r"— `title`, `identifier`, `country`, `rank`, `status` and `source` —"):
        try:
            load_spec(re.sub(broken, "gone", text, flags=re.M))
            raise AssertionError(f"a spec missing {broken!r} should not have parsed")
        except SpecError:
            pass

    # ── the rules, on a repo built here ──
    log = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(log):
        law = (
            '---\ntitle: "T"\nidentifier: "{0}"\ncountry: "uy"\nrank: "ley"\n'
            'publication_date: "2020-01-01"\nlast_updated: "2020-01-01"\n'
            'status: "in_force"\nsource: "https://example.org/{0}"\n---\ntext\n'
        )
        root = Path(tmp)
        assert check_repo(tmp, spec, "test", files_only=True) is False  # an empty dir is no repo
        (root / ".legalize.yml").write_text(
            f'spec_version: "{spec["version"]}"\ncountry: "uy"\n'
            'layout:\n  - directories: ["*"]\n    path: "{directory}/{identifier}.md"\n',
            encoding="utf-8",
        )
        (root / "uy").mkdir()
        (root / "uy/UY-ley-1.md").write_text(law.format("UY-ley-1"), encoding="utf-8")
        assert check_repo(tmp, spec, "test", files_only=True) is True, log.getvalue()

        # a law that is not where the flat default puts it
        (root / "uy/1998").mkdir()
        (root / "uy/1998/UY-ley-2.md").write_text(law.format("UY-ley-2"), encoding="utf-8")
        assert check_repo(tmp, spec, "test", files_only=True) is False, log.getvalue()
        (root / "uy/1998/UY-ley-2.md").unlink()
        (root / "uy/1998").rmdir()

        # a status the spec does not define
        bad = law.format("UY-ley-3").replace('status: "in_force"', 'status: "vigente"')
        (root / "uy/UY-ley-3.md").write_text(bad, encoding="utf-8")
        assert check_repo(tmp, spec, "test", files_only=True) is False, log.getvalue()
        assert "status 'vigente'" in log.getvalue(), log.getvalue()
        (root / "uy/UY-ley-3.md").unlink()

        # a date placeholder in a mandatory-shaped field
        sentinel = law.format("UY-ley-4").replace('"2020-01-01"', '"1900-01-01"', 1)
        (root / "uy/UY-ley-4.md").write_text(sentinel, encoding="utf-8")
        assert check_repo(tmp, spec, "test", files_only=True) is False, log.getvalue()
        assert "placeholder" in log.getvalue(), log.getvalue()
        (root / "uy/UY-ley-4.md").unlink()

        # a file whose name is not its identifier
        (root / "uy/UY-ley-9.md").write_text(law.format("UY-ley-5"), encoding="utf-8")
        assert check_repo(tmp, spec, "test", files_only=True) is False, log.getvalue()
        assert "but its identifier is" in log.getvalue(), log.getvalue()

    print(
        f"ok — SPEC.md v{spec['version']} parsed: "
        f"{len(spec['mandatory'])} mandatory fields, {len(spec['status_values'])} status values, "
        f"{len(spec['commit_types'])} commit types, {len(spec['trailers'])} trailers, "
        f"{len(spec['text_states'])} text states, {len(spec['vectors'])} test vectors; "
        f"{len(RULES)} rules covering {len(spec['sections']) - len(UNCHECKED)} section(s)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("repos", nargs="*", help="country repo checkouts to check")
    parser.add_argument("--spec", metavar="REF", help="git revision of SPEC.md to check against")
    parser.add_argument("--sample", type=int, metavar="N", help="N files per directory, not all")
    parser.add_argument("--files-only", action="store_true", help="skip the git-history rules")
    parser.add_argument("--git-only", action="store_true", help="only the git-history rules")
    parser.add_argument("--list", action="store_true", help="print the rule set and exit")
    args = parser.parse_args()

    if args.list:
        text, _ = spec_text_for(None, args.spec)
        print_rules(load_spec(text))
        return 0

    self_test()
    if not args.repos:
        return 0

    all_ok = True
    for repo_dir in args.repos:
        declared = None
        manifest_path = Path(repo_dir) / ".legalize.yml"
        if manifest_path.exists():
            with contextlib.suppress(yaml.YAMLError, OSError):
                declared = str(
                    (yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}).get(
                        "spec_version"
                    )
                    or ""
                ) or None
        try:
            text, note = spec_text_for(declared, args.spec)
            spec = load_spec(text)
        except SpecError as exc:
            print(f"FAIL {repo_dir}: {exc}")
            all_ok = False
            continue
        ok = check_repo(
            repo_dir,
            spec,
            note,
            sample=args.sample,
            files_only=args.files_only,
            git_only=args.git_only,
        )
        all_ok = ok and all_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

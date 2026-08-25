# Legalize Format Spec v0.4

Minimal contract for all country repos. Each country's legal system is different — this spec defines what MUST be consistent, and what each country decides for itself.

Key words `MUST`, `MUST NOT`, `SHOULD` and `MAY` are used as in RFC 2119.

## Conformance

A conforming repo declares itself in `.legalize.yml` at the repo root:

```yaml
spec_version: "0.4"
country: "fr"
layout:
  - directories: ["*"]
    path: "{directory}/{identifier}.md"
```

| Key            | Description                                                        |
| :------------- | :----------------------------------------------------------------- |
| `spec_version` | The version of this spec the repo conforms to.                      |
| `country`      | ISO 3166-1 alpha-2 code, matching the `country` in every file.      |
| `layout`       | One entry per group of directories that share a shape.              |
| `directories`  | The directories this entry covers, by name, or `["*"]` for the rest. |
| `path`         | How a file's path is built. See [Directory layout](#directory-layout). |

A repo whose directories do not all have the same shape names the ones that differ and
leaves the rest to `*`:

```yaml
spec_version: "0.4"
country: "pt"
layout:
  - directories: ["pt"]
    path: "{directory}/{id_sha1_2}/{identifier}.md"
  - directories: ["*"]
    path: "{directory}/{identifier}.md"
```

Matching has no ordering rules, so an entry cannot be shadowed by where it sits in the
file:

- **A directory named literally wins over `*`**, wherever the two entries appear.
- **At most one entry may use `*`,** and `*` is the entry's whole list — never mixed with
  names.
- **A directory matching no entry is an error.** A consumer MUST fail rather than fall
  back to a shape it guessed.

A repo that lists only `*` says nothing about which directories it has, and that is fine:
every file names its own directory in the frontmatter, so no consumer needs the manifest
to enumerate them.

**A repo with no `.legalize.yml` predates this version.** A consumer meeting one MUST read
it as if it declared exactly this, and MUST NOT assume anything else this document
requires. A repo whose files are not laid out this way therefore does not conform until it
adds a manifest — the fallback cannot detect that it is wrong, it can only return paths
that are:

```yaml
layout:
  - directories: ["*"]
    path: "{directory}/{identifier}.md"
```

**A consumer MUST refuse a repo whose `spec_version` is newer than the version it
implements.** Reading a newer manifest with older rules yields paths that are wrong
rather than absent, and a 404 for a law that exists is the failure this spec is least
able to make visible. This is what lets a later version add a key: an unknown placeholder
already fails loudly, but an unknown key would otherwise be ignored in silence.

The manifest exists so that a consumer can compute the path to any law after fetching
one file. It is repo metadata, not a legislative record: it carries no `Source-Date`
trailer, so history sync ignores it.

## Mandatory (all countries)

### YAML frontmatter

Every law file carries these 8 fields, plus `jurisdiction` where the country partitions
by one:

```yaml
---
title: "Full official title of the law"
identifier: "OFFICIAL-ID-123"
country: "xx"
rank: "law_type"
publication_date: "YYYY-MM-DD"
last_updated: "YYYY-MM-DD"
status: "in_force"
source: "https://official-source-url"
---
```

| Field              | Description                       | Format                                                                     |
| :----------------- | :-------------------------------- | :------------------------------------------------------------------------- |
| `title`            | Full official title               | String                                                                     |
| `identifier`       | Official ID from the source       | String, unique — see [Identifiers](#identifiers)                           |
| `country`          | ISO 3166-1 alpha-2 country code   | `es`, `fr`, `se`, `kr`, `de`, `uk`, ...                                    |
| `rank`             | Type of legal text                | Free-form string, country-specific                                         |
| `publication_date` | Original publication date         | ISO 8601 date                                                              |
| `last_updated`     | Date of the latest reform included | ISO 8601 date                                                              |
| `status`           | Legal status                      | `in_force`, `repealed`, `partially_repealed`, `annulled`, or `expired`     |
| `source`           | URL to the official source        | Valid URL                                                                  |
| `jurisdiction`     | Sub-national jurisdiction, when the country has them | String, and the file's directory — see [Directories](#directories) |

Six of them — `title`, `identifier`, `country`, `rank`, `status` and `source` — are
always present, and so is `jurisdiction` where the country has one. **The two date fields
are required whenever the source states the date, and omitted when it does not.**

Additional fields are welcome. Korea adds law sub-types, the UK adds `type_code` and `document_main_type`, France may add code structure metadata. These are country-specific extensions.

**A date field carries a date the source states.** A placeholder standing in for an
unknown date — `1900-01-01`, the Unix epoch, today — MUST NOT be written into one, and a
consumer MUST treat an absent date field as unknown rather than substituting one of its
own. A norm whose date the source does not give is published without that field.

An omitted date is rare and it is not a defect: three files of a real 171,734-file corpus
carried `last_updated: "1900-01-01"` before this rule, all of them corrections whose
source states no version date. Three wrong dates are harder to find than three absent
ones, which is the whole argument. See [Dates](#dates).

### Identifiers

The `identifier` is both a law's public name and its file name. A second act resolving to
the same string does not merely collide in an index: it replaces the first law's file,
and the first law leaves the corpus with nothing in git to show it was ever there. One
country published 6,862 such pairs before this section existed, and in about 8 % of them
the surviving file held the wrong act under the right name.

1. **`(directory, identifier)` is the key.** An identifier MUST be unique within the
   directory that holds it. Where a country partitions by jurisdiction, the pair is what
   must be unique, and it is what a consumer stores and looks up.

2. **The country's rule supplies the discriminant.** Where a source reuses one number for
   unrelated acts, whatever the source uses to tell them apart MUST be part of the
   identifier — a gazette series, a chamber, an issuing body. The discriminant belongs in
   the identifier and never in the path: the path is derived *from* the identifier, so it
   can never disambiguate it.

3. **A residual collision is an error, and the second act is still published.** When two
   acts collide despite the rule, a publisher MUST NOT overwrite the first. It MUST write
   the second under a derived identifier:

   ```
   {identifier}-{publication_date:YYYYMMDD}      first choice, stable across runs
   {identifier}-{sha1(source_url)[:8]}           when the publication dates match too
   ```

   and it MUST then report the run as failed, after publishing everything publishable. An
   ugly name is visible and fixable; a missing law is neither. The red run is what gets
   the country's identifier rule fixed.

4. **A derived identifier says so.** A file named under (3) SHOULD carry the identifier it
   collided with:

   ```yaml
   ambiguous_identifier: "OFFICIAL-ID-123"
   ```

   That is what makes the set findable — by a maintainer fixing the rule, and by a
   consumer that would rather offer a disambiguation page than a 404.

5. **Identifiers are readable, and stable within a major version.** They are meant to be
   cited and typed, which is why they carry the source's own type, number and year rather
   than an opaque key — and it is that readability that forces (2) to name a discriminant
   instead of hashing one in. Changing a country's identifier rule breaks every URL a
   consumer has published, so it is a major version change for that country and its
   README MUST record it. Consumers are expected to redirect, not to guess.

### Directory layout

A file's path is a template, and the repo states it in `.legalize.yml`. A consumer fills
the template in and gets the path — no listing, no guessing, no rule hardcoded per repo:

```python
path = entry["path"].format(
    directory=directory,
    identifier=identifier,
    id_sha1_2=hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:2],
)
```

The vocabulary is **closed**. These are the only placeholders, and a template using any
other one is not conforming:

| Placeholder    | What it is                                                             |
| :------------- | :--------------------------------------------------------------------- |
| `{directory}`  | The directory holding the file — see [Directories](#directories).       |
| `{identifier}` | The law's `identifier`, verbatim.                                       |
| `{id_sha1_2}`  | The first two hexadecimal characters, lowercase, of the SHA-1 of the identifier's UTF-8 bytes. 256 buckets. |

- **A consumer meeting an unknown placeholder MUST fail, not guess.** Reach for a
  substitution that raises on a key it was not given — Python's `str.format` does — rather
  than one that leaves the unknown part in place or drops it. A wrong path returns a 404
  for a law that exists, which is the failure this rule exists to make loud.
- **Every placeholder MUST be computable from the identifier alone**, which is the reason
  the vocabulary is closed rather than open. A URL carries an identifier and nothing else,
  so a placeholder needing a date, a rank or a lookup cannot be resolved by the consumer
  that needs it most. Adding one is a minor version of this spec, not a country's decision.
- **One level of subdirectory, no deeper.** `{id_sha1_2}` gives 256 buckets, which holds
  a corpus of any size this project has met.

The two shapes in use today:

```
{directory}/{identifier}.md                fr/LEGITEXT000006069414.md
{directory}/{id_sha1_2}/{identifier}.md    es/bb/BOE-A-1978-31229.md
```

Test vectors, which every implementation MUST reproduce:

| identifier             | `{id_sha1_2}` |
| :--------------------- | :------------ |
| `BOE-A-1978-31229`     | `bb`          |
| `SFS-1962-700`         | `8a`          |
| `LEGITEXT000006069414` | `0c`          |

#### Directories

A file's `{directory}` is its `jurisdiction` when the frontmatter carries one, and its
`country` otherwise. It is stated in the file and never inferred from the file's own
path, so a consumer holding a law's metadata computes the whole path without listing the
repo — which is also why the manifest need not enumerate every directory.

#### Sharding

**Sharding — `{id_sha1_2}` — is RECOMMENDED for every directory.** Git rewrites a
directory's whole tree on every commit that touches it, so a flat directory costs
`commits × entries` in stored trees, paid at bootstrap, on every push, and by every
consumer that walks the history. Sharding does not reduce that cost; it removes the
dependency on corpus size. Measured on a synthetic 20,000-commit history at delta depth
50, one file touched per commit:

| files in the directory | flat | sharded | sharded is |
| ---------------------: | :--- | :------ | :--------- |
|                    100 | 1.3 s · 0.008 GiB | 1.2 s · 0.009 GiB | a wash |
|                    250 | 2.2 s · 0.009 GiB | 1.6 s · 0.009 GiB | 1.4× faster |
|                    500 | 3.9 s · 0.011 GiB | 1.9 s · 0.010 GiB | 2× faster |
|                  1,000 | 7.4 s · 0.016 GiB | 2.2 s · 0.010 GiB | 3× faster |
|                  2,000 | 14.9 s · 0.024 GiB | 2.3 s · 0.010 GiB | 6× faster |
|                  5,000 | 37.4 s · 0.048 GiB | 2.4 s · 0.011 GiB | 16× faster |
|                 10,000 | 77.8 s · 0.079 GiB | 3.1 s · 0.011 GiB | 25× faster |
|                 20,000 | 166.5 s · 0.112 GiB | 2.8 s · 0.011 GiB | 59× faster |
|                 50,000 | 401.3 s · 0.144 GiB | 4.1 s · 0.011 GiB | 98× faster |
|                157,504 | 1508.5 s · 0.257 GiB | 7.9 s · 0.012 GiB | 191× faster |

The sharded column is flat and the other one is not, so there is no size at which
sharding starts to pay: it is 2× faster at 500 files and 191× at 157,504, and the pack it
produces stops growing at all. **There is also no size at which it costs more.** Below
about 250 files it stops gaining — 100 files is 1.2 s against 1.3 s — but it never turns
into a penalty, which is why a repo may shard every directory it has without measuring
the small ones first.

Raising git's delta depth is not a substitute. Measured on the same 157,504-file case,
`--depth=500` took the flat pack from 0.257 GiB to 0.036 GiB but left the time at
1416.4 s: it compresses what a flat directory produces without producing less of it.
Sharding is still 179× faster than that and 3× smaller.

At the top end it stops being about speed. Measured on a real corpus of 171,735 files in
one directory: an 8 MB tree per commit, a 3 h 22 min commit phase, ~27 minutes of
enumeration per push, and a pack above GitHub's 2 GiB ceiling — the repo could not be
pushed at all. The same corpus sharded is a ~47 KB tree per commit and one push.

Sharding is a recommendation and not a requirement because the layout is not part of the
published data: no public URL contains it, and a consumer reads it from the manifest. But
changing a directory's template rewrites every path under it, so a country adopts it on a
full rebuild, not in place. That a repo may declare a different template per group of
directories is what lets it rebuild the directory that needs it and leave the rest alone.
#### Why the bucket comes from a hash and not from the year or the type

A shard key has to exist for every file, never change, and be computable by a consumer
that holds only an identifier — that is all a URL carries. Only the hash meets all three,
which is why `{id_sha1_2}` is in the vocabulary and a year or a rank is not.

| Key | Always present? | Immutable? | From the identifier alone? | Even? |
| :--- | :--- | :--- | :--- | :--- |
| `sha1(identifier)[:2]` | yes | yes — it inherits the identifier's own guarantee | yes | yes: on a real 21,517-law corpus the busiest bucket is 1.28× the mean |
| Year of `publication_date` | no — sources leave dates out | no — a corrected date moves the file | no | no — publication is heavily skewed to recent decades |
| `rank` / type of law | yes | no — free-form and routinely corrected between rebuilds | no | no — one or two values hold most of a corpus |
| A prefix of the identifier | yes | yes | yes | no — identifiers of a country share their prefix by construction |

Year and type are navigation, not storage: a reader looking for the laws of 2018 wants a
page that lists them, which the identifier's own metadata already supports. Spending the
directory layout on it would buy a browsable tree and give up the property that makes the
layout usable at all.

### Text state

A law file's body is not always the law as it stands today. Three cases exist across
these repos, and every file settles which one it is — two of them by saying so, and the
third by saying nothing.

```yaml
text_state: "as_enacted"
last_amendment: "2243011"
```

| Value | The body is | `last_updated` means |
| :--- | :--- | :--- |
| `point_in_time` | the law as in force on `last_updated` | the date this version took effect |
| `current` | the latest consolidated text published by the source, whatever the commit's date | the date of the most recent amendment recorded |
| `as_enacted` | the act as originally published; amendments are **not** incorporated | the date of the most recent amendment recorded |

Rules:

- **If `text_state` is absent, the file is `point_in_time`.** The field is only emitted
  when there is something to warn about, so files that already state the law correctly
  never change.
- `text_state` is a core field, not a country extension. It must reach every consumer of
  the data, including the free tier of any API built on these repos.
- `last_amendment` is the official identifier of the most recent amending act. It is
  required on an `as_enacted` file **that has been amended**, and omitted on one that has
  not — an act nobody has touched has no most recent amendment, and that is the ordinary
  case, not the corner: 70 % of a real 171,734-file `as_enacted` corpus is in it. Where a
  publisher omits the field, `last_updated` equals `publication_date`, and the two
  together say "never amended" without inventing an identifier to say it with.
- `last_amendment` is also what makes two amendments published on the same date produce
  two commits instead of one.
- When `text_state` is `current` or `as_enacted`, the body must open with the notice
  below, in English, immediately after the H1 title.

The notice is **static**: byte-identical in every file and every commit of a country. It
carries no dates, counts or names — those live in the frontmatter, where they can change
without rewriting the text.

For `as_enacted`:

```markdown
> **This is the law as enacted. Amendments are not incorporated below — each one is
> a separate file in this repository and a commit in this file's history.**
```

For `current`:

```markdown
> **This file always contains the latest consolidated text published by the source.
> It is not the text as it stood on the date of any given commit.**
```

### Amending acts

Where a source publishes acts and never a consolidated text (`as_enacted`), each amending
act is its own file, with its own `identifier`. The act is published once and never copied
into, or split across, the laws it touches.

**The commit trailers are the record of what amended what**, and they always exist. Each
(act, law) pair produces one commit on the amended law, carrying `Source-Id` of the act
and `Norm-Id` of the law. Grouping commits by `Source-Id` reconstructs which laws an act
changed; grouping by `Norm-Id` reconstructs a law's amendment history.

An act MAY also carry the same relation forwards in its frontmatter, as a convenience for
a consumer that has the file but not the history:

```yaml
amends: ["2000123", "2000456"]
```

- **`amends` is OPTIONAL.** The largest `as_enacted` corpus here publishes 171,734 files
  and none of them carry it; the trailers carry the relation instead, and nothing is lost.
- **It is a YAML list of `identifier` values as this repo names them** — never the source's
  own citation strings, and never one string with separators inside it. A consumer resolves
  each entry to a file in this repo, which it cannot do with `lei:123/2020`.
- **It MUST be complete, or absent.** A list capped at a length, or at a count, cannot be
  told apart by a consumer from a short one, so it reports an act as amending three laws
  when it amended four hundred. A publisher that cannot emit the whole list omits the
  field, and the trailers still answer the question correctly.

### Commit format

```
[type] Title — articles affected

Source-Id: REFORM-ID
Source-Date: YYYY-MM-DD
Norm-Id: LAW-ID
```

Types: `[bootstrap]`, `[reform]`, `[new]`, `[repeal]`, `[correction]`, `[fix-pipeline]`

### History

**A repo's git history is the corpus's version history.** Each law's file carries one
commit per version its source publishes, and a repo whose history is a single import does
not conform. Such a repo has the text of every law and no record of when it said what,
which is the one thing it offers over a folder of files.

This is not a shortcut that can be taken back later. Two corpora here were published
without history and both had to be rebuilt from nothing rather than amended: one of 86,000
laws, and one that reached production with 109,944 laws and a single reform between them.
A rebuild changes every commit hash, and it changes identifiers whenever the rule that
generates them is corrected in the same pass — so every URL a consumer has published
breaks at once. Building the history before the first push costs an order of magnitude
less than adding it after.

**Order is per file, not per repo.** `git log -- {path}` MUST return that law's versions
oldest first. The repository-level sequence carries no meaning at all: a publisher writes
laws in whatever order is convenient — parallelised, batched, alphabetical — so two laws'
commits interleave freely. A consumer MUST NOT read repo-wide commit order as
chronological. `Source-Date` dates a change; position does not.

### Dates

**`Source-Date` is the legal date. A commit's git author date mirrors it and is not
authoritative.**

- `Source-Date` is the date the **source** attaches to the change the commit records:
  the date that act was published officially. It is not the date the commit was created,
  and it is not the date the text enters into force — that is a property of the norm and
  belongs in the frontmatter if a country tracks it.
- A commit's author date MUST be its `Source-Date`. Where git cannot represent that date
  it is clamped to `1970-01-02`, and `Source-Date` remains the authority. Norms older
  than the Unix epoch are ordinary in every corpus here, so a consumer that reads git
  author dates as legal dates will be wrong about them, silently and without a 404 to
  show for it.
- **A change with no date carries no `Source-Date` trailer.** When the source states no
  date, the trailer is omitted rather than filled with a floor value, and the commit's
  author date is the norm's `publication_date`. An undated change is not a dated reform,
  and a consumer keyed on `Source-Date` is right to skip it.
- **`Source-Date` MAY be in the future**, and such commits are valid: a norm entering
  into force years from now is published today carrying that date. Bootstrap writes norms
  in their own chronological order, so a freshly built repo opens with a run of
  future-dated commits at its tip — dozens in a row is normal.
- **A consumer computing corpus freshness MUST take the most recent `Source-Date` that is
  not in the future.** Taking the maximum outright makes a repo look permanently up to
  date and stops its own daily updates; seven countries were frozen for months by exactly
  this.

### Git identity

**Author and committer are both the pipeline's own identity** — `Legalize
<legalize@legalize.dev>`, or whatever a fork configures — and never the person who
happened to run it.

These commits are generated, and they get regenerated: a corpus is rebuilt when a parser
improves or an identifier rule is corrected. A rebuild has to be able to produce the same
history, and an author taken from whoever ran it makes every commit hash depend on which
machine did the run. The identity is metadata about the pipeline, not authorship of the
law: the author of a law is the legislature, and that is recorded in the file, not in
git.

### Repository

One repo per country: `legalize-{code}` (e.g., `legalize-es`, `legalize-kr`, `legalize-de`).

Community contributions may live under the contributor's GitHub account (e.g., `9bow/legalize-kr`) and be listed in the hub.

## Flexible (per country)

Each country decides and documents in its own README:

- **What is a "law"?** Each legal system defines its own unit. Spain: individual law (BOE ID). France: consolidated code. Korea: act + decree + ordinance grouped. Sweden: individual statute (SFS number).
- **Rank values.** Free-form string. Spain: `ley`, `constitucion`, `real_decreto`. France: `code`, `loi`, `ordonnance`. Sweden: `lag`, `balk`, `forordning`. Korea: `법률`, `대통령령`, `부령`. UK: `public-general-act`, `statutory-instrument`.
- **How many directories and what they mean.** One per country is the common case; a
  country that partitions by jurisdiction has one per jurisdiction (`es`, `es-pv`, …), and
  the UK has one per legal jurisdiction. Each file names its own, and the manifest names
  any whose shape differs from the rest. What is no longer free is the shape *inside* a
  directory — see [Directory layout](#directory-layout).
- **Additional frontmatter fields.** Add whatever is useful for your legal system.
- **Language.** Each country's content is in its original language. Code, commit types, and trailer keys are in English.

## Versioning

This spec follows semantic versioning, and a repo states the version it conforms to in
`.legalize.yml`.

- **Major** — anything that changes where a file lives or what it is called: a
  directory's path template, a country's identifier rule, a removed or renamed frontmatter field. Every
  consumer's URLs break, so a major version is announced in the hub repo before it lands
  and the country repo carries redirect notes in its README.
- **Minor** — new optional fields, a new placeholder in the path vocabulary, new `status`
  or commit types, new normative text that no existing conforming repo violates.
- **Patch** — wording.

v1.0 is reached when at least one repo conforms to this document end to end: manifest
written, path template implemented in publisher and consumer alike, and the dates clause
holding. Until then the `early-stage` notice in each country repo is the honest one.

### Changelog

- **v0.4** — What v0.3 left unsaid, and what it said that the corpora do not bear out. Adds
  `.legalize.yml` and `spec_version`, so a consumer discovers a repo's structure instead
  of assuming one. Makes the identifier unique per directory, names who supplies the
  discriminant, and forbids one act overwriting another. Replaces free-form directory
  structure with a path template drawn from a closed vocabulary, declarable per group of
  directories, and recommends sharding. Defines what a file's directory is. States that
  `Source-Date` is the authority, that future dates are valid, and that freshness must
  ignore them. Corrects four claims v0.3 made that the corpora do not bear out:
  `last_amendment` is required only where an amendment exists, both git identities are the
  pipeline's, the two date fields are conditional on the source stating them, and `amends`
  is optional but must be complete rather than capped. Adds §History: a repo's git
  history is its version history and a single import does not conform, and repo-wide
  commit order carries no meaning — both learned the expensive way and until now written
  down only in the pipeline's onboarding playbook.
- **v0.3** — Added `text_state`, `last_amendment` and `amends`, so a file states whether its
  body is the law in force, the latest available text, or the act as enacted. Absent
  `text_state` means `point_in_time`, so no existing file changes meaning. See
  [legalize-pipeline#87](https://github.com/legalize-dev/legalize-pipeline/issues/87).
- **v0.2** — Frontmatter keys, status values, and commit types switched from Spanish to English to match the pipeline (see [legalize-pipeline#52](https://github.com/legalize-dev/legalize-pipeline/pull/52)). Added `annulled`, `expired` status values and `[fix-pipeline]` commit type. Existing commits in country repos retain their original labels (immutable git history).
- **v0.1** — Initial spec.

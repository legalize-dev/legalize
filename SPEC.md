# Legalize Format Spec v0.3

Minimal contract for all country repos. Each country's legal system is different — this spec defines what MUST be consistent, and what each country decides for itself.

## Mandatory (all countries)

### YAML frontmatter

Every law file must have these 8 fields:

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
| `identifier`       | Official ID from the source       | String (unique per country)                                                |
| `country`          | ISO 3166-1 alpha-2 country code   | `es`, `fr`, `se`, `kr`, `de`, `uk`, ...                                    |
| `rank`             | Type of legal text                | Free-form string, country-specific                                         |
| `publication_date` | Original publication date         | ISO 8601 date                                                              |
| `last_updated`     | Date of the latest reform included | ISO 8601 date                                                              |
| `status`           | Legal status                      | `in_force`, `repealed`, `partially_repealed`, `annulled`, or `expired`     |
| `source`           | URL to the official source        | Valid URL                                                                  |

Additional fields are welcome. Korea adds law sub-types, Spain adds `jurisdiction` for autonomous communities, the UK adds `type_code` and `document_main_type`, France may add code structure metadata. These are country-specific extensions.

### Text state

A law file's body is not always the law as it stands today. Three cases exist across
these repos, and every file must say which one it is.

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
- `last_amendment` is the official identifier of the most recent amending act. Required
  with `as_enacted`, optional otherwise. It is also what makes two amendments published
  on the same date produce two commits instead of one.
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
act is its own file, with its own `identifier`, and declares what it amends:

```yaml
amends: ["2000123", "2000456"]
```

`amends` is a list because one act commonly amends several laws. The act is published
once and never copied into, or split across, the laws it touches.

Each (act, law) pair produces one commit on the amended law, carrying `Source-Id` of the
act and `Norm-Id` of the law. Grouping commits by `Source-Id` reconstructs which laws an
act changed; grouping by `Norm-Id` reconstructs a law's amendment history.

### Commit format

```
[type] Title — articles affected

Source-Id: REFORM-ID
Source-Date: YYYY-MM-DD
Norm-Id: LAW-ID
```

Types: `[bootstrap]`, `[reform]`, `[new]`, `[repeal]`, `[correction]`, `[fix-pipeline]`

The commit's author date must be the real publication date of the reform, not the date the commit was created.

### Git identity

- **Author:** whoever runs the pipeline (from `git config user.name` / `user.email`)
- **Committer:** `Legalize <legalize@legalize.dev>` (or the pipeline's configured identity)

### Repository

One repo per country: `legalize-{code}` (e.g., `legalize-es`, `legalize-kr`, `legalize-de`).

Community contributions may live under the contributor's GitHub account (e.g., `9bow/legalize-kr`) and be listed in the hub.

## Flexible (per country)

Each country decides and documents in its own README:

- **Directory structure.** Spain uses flat `es/{id}.md`. Korea groups related laws `kr/{name}/`. France has one file per code `fr/{id}.md`. All valid.
- **What is a "law"?** Each legal system defines its own unit. Spain: individual law (BOE ID). France: consolidated code. Korea: act + decree + ordinance grouped. Sweden: individual statute (SFS number).
- **Rank values.** Free-form string. Spain: `ley`, `constitucion`, `real_decreto`. France: `code`, `loi`, `ordonnance`. Sweden: `lag`, `balk`, `forordning`. Korea: `법률`, `대통령령`, `부령`. UK: `public-general-act`, `statutory-instrument`.
- **Additional frontmatter fields.** Add whatever is useful for your legal system.
- **Language.** Each country's content is in its original language. Code, commit types, and trailer keys are in English.

## Versioning

This spec is v0.3. It will evolve as more countries join. Breaking changes will be announced in the hub repo. The `early-stage` notice in each country repo reflects this.

### Changelog

- **v0.3** — Added `text_state`, `last_amendment` and `amends`, so a file states whether its
  body is the law in force, the latest available text, or the act as enacted. Absent
  `text_state` means `point_in_time`, so no existing file changes meaning. See
  [legalize-pipeline#87](https://github.com/legalize-dev/legalize-pipeline/issues/87).
- **v0.2** — Frontmatter keys, status values, and commit types switched from Spanish to English to match the pipeline (see [legalize-pipeline#52](https://github.com/legalize-dev/legalize-pipeline/pull/52)). Added `annulled`, `expired` status values and `[fix-pipeline]` commit type. Existing commits in country repos retain their original labels (immutable git history).
- **v0.1** — Initial spec.

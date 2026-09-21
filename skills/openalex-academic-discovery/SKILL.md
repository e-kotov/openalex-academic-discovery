---
name: openalex-academic-discovery
description: Scout research groups and host institutions, find and profile scholars, and verify papers or DOIs with OpenAlex. Use for lab, PI or fellowship-host discovery, researcher vetting, and paper checks.
license: MIT
metadata:
  author: Egor Kotov
  homepage: https://github.com/e-kotov/openalex-academic-discovery
  version: "0.1.0"
compatibility: Requires Python 3.8+ (standard library only) and outbound HTTPS access to api.openalex.org. Without code execution or network access, use references/api.md with a web-fetch tool.
---

# OpenAlex Academic Discovery & Lab Scouting

Workflows for querying the OpenAlex bibliographic database (250M+ works, 100M+ authors, global institution records) to scout academic groups, verify claims, and advise researchers and applicants on strategic fit.

## Running the CLI

The bundled CLI is `scripts/openalex_cli.py`, **relative to the directory containing this SKILL.md**, not to the user's working directory. Resolve this skill's absolute directory first and call the script through it:

```bash
python3 "<skill-dir>/scripts/openalex_cli.py" <command> [options]
```

- Python 3.8+, standard library only. Nothing to install.
- Add `--json` to any command for machine-readable output. Prefer it when you will post-process results.
- Exit status: `0` success, `1` nothing found, `2` bad arguments, `3` network unreachable, `4` API key rejected or daily budget spent.
- **Exit 3 means the sandbox blocked the network, not that the record is missing.** Ask for network approval for `api.openalex.org` and rerun. If that is impossible, or you cannot execute code at all, read `references/api.md` and fetch the same URLs with a web-fetch tool.

| Command | Question it answers |
| --- | --- |
| `suggest-topics` | Which OpenAlex topic IDs describe this niche? (from a prose description) |
| `rank-institutions` | Which institutions lead or specialise in this topic? (census over all matching works) |
| `find-people` | Who is publishing on it right now, in these countries or at this institution? |
| `find-groups` | Quick look with sample papers and names, from the top search hits |
| `who-cites` | Who builds on this paper, dataset, or tool? |
| `collaborators` | Who does this researcher publish with, and at which institutions? |
| `funding` | Which funders back this researcher, institution, or niche? |
| `author-profile` | Who is this researcher, where are they now, what have they done lately? |
| `h-index-at` | What was their h-index at the end of a past year? |
| `verify-work` | Does this paper exist, and are its date, venue, and authors as claimed? Takes one DOI, a list, or a title. |

Run any command with `-h` for all options.

### Quoting queries

OpenAlex search supports quoted phrases and `AND` / `OR` / `NOT`. Wrap the whole query in **single quotes** so the inner double quotes survive the shell:

```bash
--query '"method phrase" ("domain term a" OR "domain term b")'
```

Country codes are ISO 3166-1 alpha-2: `GB`, not `UK`.

### API key (recommended)

OpenAlex meters usage as a daily budget that resets at midnight UTC. Without a key the budget is about $0.10 a day, roughly 100 searches; a **free** key raises it tenfold, so treat the key as expected for anything beyond a quick check. The CLI prints a note when no key is set, reports each run's cost and the budget left (on stderr, and under `api_usage` in `--json`), and exits `4` when the budget is spent.

On first use, or on exit `4`, tell the user to:
1. Create a free account at <https://openalex.org> and copy the key from <https://openalex.org/settings/api>.
2. Store it as `OPENALEX_API_KEY` in their shell profile, in a `.env` file, or in the macOS Keychain item `openalex_api_key`.

Never ask the user to paste the key into the chat, and never print, log, or commit it. The CLI sends it as an `Authorization` header, not in the URL. The old `mailto` "polite pool" is retired and ignored. Searches cost ten times more than filtered lists, so prefer `--topics` or ID filters once you know them.

## When to Activate This Skill

1. **Academic mentorship and talent triage**: advising prospective PhD or postdoc candidates on where active groups exist for their niche or complementary skill set.
2. **Fellowship and grant host discovery**: identifying host institutions and faculty sponsors in specific countries or regions for individual fellowships and career grants.
3. **Interdisciplinary niche mapping**: finding PIs and labs at the intersection of a methodology and an applied problem domain.
4. **Author due diligence and disambiguation**: checking a researcher's current affiliation, publication velocity, h-index, and recent contributions before outreach or collaboration.
5. **Preprint and claim verification**: validating that a claimed paper, preprint, or working paper exists, and checking its date, venue, and full author list.

## Core Workflows

### A. Scouting prospective labs and hosts

1. **Identify the two axes.** Ask the user for (or infer) the *methodological approach* and the *domain problem*, then combine them: `'"<method>" ("<domain a>" OR "<domain b>")'`. When the user describes the niche in prose, or keywords return noise, derive topic IDs instead and pass them as `--topics` to the commands below (topic filters are also ten times cheaper than searches):
   ```bash
   python3 "<skill-dir>/scripts/openalex_cli.py" suggest-topics --text "one or two sentences describing the research niche"
   ```
   Check the listed closest works look right, and keep only the topics that fit; broad topics pull in unrelated work.
2. **Rank institutions** over all matching works:
   ```bash
   python3 "<skill-dir>/scripts/openalex_cli.py" rank-institutions \
     --query '"machine learning" ("protein folding" OR "drug discovery")' \
     --countries US,CA,JP --from-year 2022 --top-n 15
   ```
   The default sort is **LQ** (location quotient): the institution's share of the niche divided by its share of all output. It surfaces small specialist institutes that a raw count buries under the largest universities. National umbrella bodies and companies can crowd the list; `--types education,facility,healthcare` keeps the kinds of host the user can actually join. Also run `--sort works` (volume) and `--sort cites` (impact) and present institutions that appear on more than one list. Use `--min-works` to drop one-paper flukes.
3. **Find the people** at a shortlisted institution, or across the countries:
   ```bash
   python3 "<skill-dir>/scripts/openalex_cli.py" find-people \
     --query '"machine learning" "drug discovery"' --institution-id I4210127509 --from-year 2022
   ```
   This groups *recent works*, so affiliations are as published. Keep `--from-year` within the last three or four years.
4. **Add a citation-based view** when the user can name a key paper, dataset, or tool in the niche:
   ```bash
   python3 "<skill-dir>/scripts/openalex_cli.py" who-cites --works 10.1038/nature14539 --by institution --countries JP --from-year 2023
   ```
   Citing a specific tool paper is a stronger signal of fit than matching free-text keywords.
5. **Screen for domain fit yourself.** Bibliometrics cannot tell apart two fields that share vocabulary. Read each candidate's listed topics and recent titles and label them *match*, *complementary*, *off-domain*, or *uncertain* before presenting. Treat *uncertain* as "needs a manual look", never as a match.
6. **Check the host context** for shortlisted people, which matters for fellowship applications:
   ```bash
   python3 "<skill-dir>/scripts/openalex_cli.py" collaborators --id A5070580886 --from-year 2020
   python3 "<skill-dir>/scripts/openalex_cli.py" funding --author-id A5070580886 --from-year 2019
   ```
   Co-authors show the size and reach of the group (`--by institution` shows partner institutions). Funders show whether the group wins grants from the scheme or country the user is targeting. Funder counts come from acknowledgements on papers, so treat them as a lower bound.
7. **Report actionable findings**: institutions with works, citations per work and LQ; named researchers with ORCID and topics; two recent representative papers each with DOI links (`find-groups` supplies sample papers quickly; add `--semantic` to match a prose description by meaning, limited to 50 works).
8. **Widen when results are thin.** Try `find-groups --semantic` with a prose description to catch work that uses different vocabulary. Rerun with adjacent domains or a broader method term, and advise the applicant to position their methodological skills as a complementary asset to established teams rather than waiting for an exact topic match.

### B. Researcher due diligence

```bash
python3 "<skill-dir>/scripts/openalex_cli.py" author-profile --name "Full Name" --institution "Institution keyword"
```

A bare name is only a best guess. The output lists other same-name profiles with their institutions and topics. Apply these rules:

- **ORCID decides.** If the user has the ORCID, use `--orcid`. A different ORCID means a different person, whatever else matches. One ORCID can sit on several split OpenAlex records; the CLI picks the fullest and lists the rest, so say when metrics may be partial.
- **Otherwise require agreement** between institution (current or past) and research topics before accepting a profile. If no evidence can be evaluated, do not guess: ask for a known paper.
- **Resolve by output when the name is common.** Run `verify-work` on a paper the person is known to have written, take the author's OpenAlex ID from the `--json` output, and rerun `author-profile --id A...`.
- **Abort on incoherent profiles.** If one profile mixes unrelated fields and institutions, OpenAlex has merged two people. Report that the metrics are unreliable instead of quoting them.

For career-stage questions ("what was their record when they were appointed?"):

```bash
python3 "<skill-dir>/scripts/openalex_cli.py" h-index-at --id A5070580886 --year 2019
```

OpenAlex citation counts run lower than Google Scholar's. Never compare an OpenAlex h-index with a Scholar h-index.

### C. Publication and preprint verification

```bash
python3 "<skill-dir>/scripts/openalex_cli.py" verify-work --doi "10.1038/nature14539"
python3 "<skill-dir>/scripts/openalex_cli.py" verify-work --title "distinctive words from the title"
# A whole publication list or bibliography in one request, checking the claimant is on every byline:
python3 "<skill-dir>/scripts/openalex_cli.py" verify-work --doi "10.1038/nature14539,10.1038/nature16961" --expect-author "Full Name"
python3 "<skill-dir>/scripts/openalex_cli.py" verify-work --doi-file dois.txt --expect-author "Full Name"
```

`--expect-author` matches on surname only, so it catches a real paper attributed to someone who is not an author, but it cannot tell namesakes apart.

A DOI lookup is an exact match; a title lookup returns the best search hit, so confirm the title. Check every claimed element against the output: author order, the claimant's presence in the byline, publication date, venue, work type (preprint vs article), and the retraction flag.

"Not found" is not proof of fabrication: very recent preprints and some working-paper series are indexed late or not at all. Say so, and suggest checking the DOI resolver or the repository directly.

## Best Practices

- **Privacy**: query only public scholarly outputs, institutional affiliations, and published work. Never look up personal contact details or private information.
- **Links**: report canonical DOIs (`https://doi.org/...`), ORCIDs, and OpenAlex IDs so the user can check every claim.
- **Coverage**: OpenAlex affiliations lag behind job moves, and author records are occasionally merged or split incorrectly. Flag uncertainty instead of guessing.
- **Limits of the rankings**: `group_by` returns at most 200 groups and cannot be paged, and a country filter keeps whole works, so the CLI re-checks each institution's or person's own country after the fact. State the year window and filters with any ranking you present.
- **Going further**: `references/api.md` covers topics, funders, server-side aggregation, paging, and known API traps.

# OpenAlex API patterns

Use these when the CLI cannot run (no code execution, or a sandbox without outbound network) but a web-fetch or browsing tool is available, or when a task needs something the CLI does not cover. All endpoints are `GET` and return JSON.

- Base URL: `https://api.openalex.org`
- Official docs: <https://help.openalex.org> (machine-readable index: <https://help.openalex.org/llms.txt>). The older `docs.openalex.org` and `developers.openalex.org` addresses redirect there.
- URL-encode all values. `|` inside a filter value means OR (at most 100 values); `,` between filters means AND.

## Authentication and budget

- Free key: create an account at <https://openalex.org>, copy the key from <https://openalex.org/settings/api>.
- Send it as the header `Authorization: Bearer <key>` (preferred, keeps the key out of URLs and logs) or as `?api_key=<key>`.
- Usage is a dollar-denominated daily budget, reset at midnight UTC: about $0.10 a day without a key, $1 a day with a free key. Single-record lookups are free, filtered lists cost about $0.10 per 1,000 calls, and `search=` calls about $1 per 1,000.
- HTTP 429 means the budget is spent or the rate exceeded 100 requests a second. Every response reports its cost in `meta.cost_usd`, and the headers `X-RateLimit-Remaining-USD` and `X-RateLimit-Reset` (seconds) give what is left today. `GET /rate-limit` with the key returns the same.
- The `mailto=` "polite pool" is retired; the parameter is ignored.

## What the CLI does

### find-groups

```
/works?search=<query>&filter=from_publication_date:<YYYY>-01-01&per_page=100&select=id,doi,title,publication_year,cited_by_count,authorships
```

Walk `authorships[].institutions[]`, count by `display_name` + `country_code`, keep wanted countries, and collect `authorships[].author.display_name` plus each work's title, year, DOI, and citations.

### suggest-topics

```
/works?search.semantic=<prose description>&per_page=50&select=id,title,topics
```

Tally `topics[].id` across the results. Semantic search matches meaning, returns at most 50 works, costs the same as a keyword search, **cannot be combined with `group_by`**, and accepts only a few filters (among them `publication_year`, `type`, `institutions.id`, `author.id`, `funders.id`, `is_oa`; not `from_publication_date` or country). Use it to find topic IDs or sample works, then rank with topic filters.

### rank-institutions

```
/works?search=<query>&filter=from_publication_date:<YYYY>-01-01,institutions.country_code:US|CA&group_by=authorships.institutions.id&per_page=200
   ... same, plus &sort=cited_by_count.sum:desc
```

Each group has `key` (institution ID), `key_display_name`, and `count`. With the `.sum` sort each group also carries `sum_cited_by_count`, so citations per work = sum / count. Merge both pages, since each is capped at 200 groups.

Location quotient, which normalises for institution size:

```
LQ = (institution niche works / all niche works) / (institution total works / all works)
```

- all niche works: `meta.count` of the niche query
- institution total works: sum of `counts_by_year[].works_count` for the same years, from `/institutions?filter=openalex_id:I1|I2|...&select=id,country_code,counts_by_year`
- all works: `meta.count` of `/works?filter=from_publication_date:...,institutions.country_code:...&per_page=1`

### find-people

```
/works?search=<query>&filter=from_publication_date:<recent year>-01-01,institutions.country_code:CA&group_by=authorships.author.id&per_page=200
/authors?filter=openalex_id:A1|A2|...&select=id,display_name,orcid,summary_stats,last_known_institutions,topics
```

Add `authorships.institutions.id:<I...>` to restrict to one institution. Drop hydrated authors whose `last_known_institutions` are outside the wanted countries.

### who-cites

```
/works/https://doi.org/<doi>?select=id                      # DOI -> work ID
/works?filter=cites:W1|W2,from_publication_date:<YYYY>-01-01&group_by=authorships.institutions.id&per_page=200
```

Use `group_by=authorships.author.id` for people. `filter=cited_by:<W...>` goes the other way (the work's reference list).

### collaborators

```
/works?filter=author.id:<A...>,from_publication_date:<YYYY>-01-01&group_by=authorships.author.id&per_page=200
```

Drop the author's own ID from the groups. `group_by=authorships.institutions.id` gives partner institutions.

### funding

```
/works?filter=author.id:<A...>,from_publication_date:<YYYY>-01-01&group_by=funders.id&per_page=200
/funders?filter=openalex_id:F1|F2|...&select=id,display_name,country_code,homepage_url
```

Swap the first filter for `authorships.institutions.id:<I...>`, `topics.id:<T...>`, or add `search=`. Counts come from funding acknowledgements, which many works lack.

### author-profile

```
/authors?search=<name>&per_page=10
/authors?filter=orcid:<orcid>            # may return several split records; take the fullest
/authors/<A...>
/works?filter=author.id:<A...>&sort=publication_date:desc&per_page=5
```

Useful fields: `id`, `orcid`, `works_count`, `cited_by_count`, `summary_stats.h_index`, `last_known_institutions`, `affiliations[].years` (timeline), `topics`.

### h-index-at

Page through `/works?filter=author.id:<A...>&select=id,publication_year,cited_by_count,counts_by_year&per_page=100&cursor=*`. For target year T, keep works published by T and compute `cited_by_count - sum(counts_by_year[year > T].cited_by_count)`, then take the h-index of those values. `counts_by_year` reaches back only about a decade, so earlier years cannot be reconstructed.

### verify-work

```
/works?filter=doi:<doi>
/works?filter=doi:<doi 1>|<doi 2>|...&per_page=50        # many at once; match results back case-insensitively
/works?search=<title words>&per_page=3
```

Useful fields: `title`, `doi`, `publication_date`, `type`, `is_retracted`, `primary_location.source.display_name`, `open_access.oa_url`, `authorships[].author_position`, `authorships[].is_corresponding`, `authorships[].author.{display_name,orcid}`, `authorships[].institutions[].display_name`.

## Beyond the CLI

**Topic IDs instead of free text.** Filters are ten times cheaper than searches and more precise.

```
/topics?search=<phrase>&select=id,display_name,subfield,field
/works?filter=topics.id:T123|T456,...
```

`POST /text/topics` with a JSON body `{"title": "...", "abstract": "..."}` returns scored topic IDs for a paragraph of text, such as a research statement. Rerun a ranking with derived and with hand-picked topics; a stable top of the list is a cheap robustness check. `/concepts` is deprecated in favour of `/topics`.

**Funders.** Filter works, not grants: `/works?filter=funders.id:<F...>,topics.id:<T...>&group_by=authorships.institutions.id`. Find the funder ID with `/funders?search=<name>`. The `/awards` endpoint exists, but metadata completeness varies widely between funders.

**Paging.** `per_page` maximum is 100 for result lists (200 is still accepted but deprecated). Beyond 10,000 results, start with `&cursor=*` and pass `meta.next_cursor` until it is null.

**Direct lookups** (free of charge): `/works/https://doi.org/<doi>`, `/authors/https://orcid.org/<orcid>`, `/institutions/ror:<ror id>`, `/institutions?search=<name>`.

## Known traps

- Country codes are ISO 3166-1 alpha-2: `GB`, never `UK`.
- Institution `type` is one of education, facility, healthcare, company, government, nonprofit, funder, archive, other. National research organisations top raw rankings because every member lab rolls up to them; filter on the institution's own type after hydration. `authorships.institutions.lineage:<I...>` matches an institution together with its children.
- `/authors?filter=affiliations.institution.country_code:..` means *ever* affiliated. To find who is somewhere now, group recent works by author (see find-people).
- Country and continent filters are work-level: a work with one matching institution is kept whole, so co-author institutions elsewhere appear in the groups. Re-check each institution's or person's own country after hydration.
- `group_by` returns at most 200 groups and they cannot be re-sorted across pages. `sort=cited_by_count:desc` with `group_by` is rejected (HTTP 400); `cited_by_count.sum:desc` works at the time of writing but is not in the official docs, so fall back to the plain count ranking if it starts failing.
- Add `type:article` to citation-sorted work lists, or journal-level "paratext" records crowd the top.
- Free-text search sorted by citations drifts off-topic quickly. Anchor on topic IDs or on `cites:` a specific paper.
- Relevance-ranked samples favour highly cited work. Use `group_by` for ranking questions.
- OpenAlex citation counts run below Google Scholar's. Do not mix the two in one comparison.
- When one author profile shows unrelated fields and institutions, two people have been merged. No query repairs that; report the metrics as unreliable.

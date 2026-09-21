#!/usr/bin/env python3
"""
OpenAlex Academic Discovery CLI
A lightweight tool for querying OpenAlex API to map research groups,
scout host institutions, profile researchers, and verify publications.

Python 3.8+, standard library only.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

API_BASE = "https://api.openalex.org"
MAX_PER_PAGE = 100   # documented ceiling for result lists (200 is deprecated)
MAX_GROUPS = 200     # group_by returns at most 200 groups per request
SEMANTIC_MAX = 50    # semantic search returns at most 50 works
KEY_URL = "https://openalex.org/settings/api"
INSTITUTION_TYPES = ["education", "facility", "healthcare", "company", "government",
                     "nonprofit", "funder", "archive", "other"]
ID_CHUNK = 50        # values per OR-filter when hydrating entities in bulk

_warned_no_key = False
_usage = {"requests": 0, "cost_usd": 0.0, "remaining_usd": None, "resets_in_seconds": None}


def _track_usage(data, headers=None):
    """Record what a call cost and what is left of today's budget."""
    _usage["requests"] += 1
    if isinstance(data, dict):
        _usage["cost_usd"] = round(_usage["cost_usd"] + ((data.get("meta") or {}).get("cost_usd") or 0), 6)
    if headers:
        try:
            _usage["remaining_usd"] = float(headers.get("X-RateLimit-Remaining-USD"))
            _usage["resets_in_seconds"] = int(headers.get("X-RateLimit-Reset"))
        except (TypeError, ValueError):
            pass


def get_api_key():
    """Retrieve API key from environment, .env file, or macOS Keychain."""
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        return key

    # Check local .env
    for candidate in [".env", os.path.expanduser("~/.env")]:
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("OPENALEX_API_KEY="):
                            val = line.split("=", 1)[1].strip()
                            return val.strip("'\" ")
            except Exception:
                pass

    # Check macOS Keychain
    if sys.platform == "darwin":
        try:
            user = os.environ.get("USER", "")
            cmd = ["security", "find-generic-password", "-s", "openalex_api_key", "-w"]
            if user:
                cmd = ["security", "find-generic-password", "-a", user, "-s", "openalex_api_key", "-w"]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
            if out:
                return out
        except Exception:
            pass

    return None


def query_openalex(endpoint, params=None):
    """
    Query the OpenAlex REST API. Returns parsed JSON, or None on failure.

    The API key is sent as an Authorization header, never in the URL, so it
    cannot leak through logged URLs, error messages, or the process list.
    """
    global _warned_no_key
    params = dict(params or {})
    key = get_api_key()
    headers = {"User-Agent": "openalex-academic-discovery/0.1"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    elif not _warned_no_key:
        _warned_no_key = True
        sys.stderr.write("note: no OPENALEX_API_KEY set; using the small keyless daily budget. "
                         f"A free key gives 10x more: {KEY_URL}\n")

    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)

    # Attempt 1: standard urllib
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            _track_usage(data, resp.headers)
            return data
    except urllib.error.HTTPError as e:
        # The server answered; curl would get the same answer.
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("message", "")
        except Exception:
            detail = ""
        sys.stderr.write(f"OpenAlex request to /{endpoint} failed: HTTP {e.code} {e.reason}. {detail}\n")
        if e.code in (401, 403, 429):
            sys.stderr.write(
                "DAILY BUDGET OR AUTH PROBLEM, not a missing record. "
                + ("The key was rejected or its daily budget is spent (resets at midnight UTC)."
                   if key else
                   f"No API key is set. Create a free OpenAlex account, copy the key from {KEY_URL}, "
                   "and set OPENALEX_API_KEY.") + "\n")
            sys.exit(4)
        return None
    except Exception as e:
        urllib_error = type(e).__name__

    # Attempt 2: curl fallback (handles HTTP/2 and platform TLS negotiation seamlessly).
    # Headers go through a config on stdin so the key never shows up in `ps`.
    try:
        config = f'url = "{url}"\n' + "".join(f'header = "{k}: {v}"\n' for k, v in headers.items())
        proc = subprocess.run(
            ["curl", "-s", "-L", "--fail", "--max-time", "60", "-K", "-"],
            input=config, capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"curl exit {proc.returncode}")
        data = json.loads(proc.stdout)
        _track_usage(data)
        return data
    except Exception as e:
        sys.stderr.write(
            f"OpenAlex request to /{endpoint} failed: urllib: {urllib_error}; curl: {e}\n"
            "NETWORK UNREACHABLE: this says nothing about whether the record exists. If you are "
            "running inside an agent sandbox, allow outbound network access to api.openalex.org "
            "(or rerun with network approval), or fetch the URL patterns in references/api.md "
            "with a web-fetch tool instead.\n"
        )
        sys.exit(3)


def short_id(openalex_url):
    """https://openalex.org/W123 -> W123"""
    return (openalex_url or "").rsplit("/", 1)[-1]


def join_filters(*parts):
    return ",".join(p for p in parts if p)


def country_filter(countries):
    """'us, ca' -> 'institutions.country_code:US|CA' (ISO 3166-1 alpha-2; GB, not UK)."""
    if not countries:
        return ""
    codes = [c.strip().upper() for c in countries.split(",") if c.strip()]
    if "UK" in codes:
        sys.stderr.write("note: OpenAlex uses ISO code GB, not UK; substituting.\n")
        codes = ["GB" if c == "UK" else c for c in codes]
    return "institutions.country_code:" + "|".join(codes)


def country_set(countries):
    if not countries:
        return None
    return {("GB" if c.strip().upper() == "UK" else c.strip().upper()) for c in countries.split(",") if c.strip()}


def grouped(filter_str, group_by, search=None, sort=None):
    """
    Server-side aggregation over /works. Returns (groups, total_matching_works).
    At most 200 groups come back and they cannot be paged.
    """
    params = {"group_by": group_by, "per_page": MAX_GROUPS}
    if filter_str:
        params["filter"] = filter_str
    if search:
        params["search"] = search
    if sort:
        params["sort"] = sort
    data = query_openalex("works", params)
    if not data:
        return None, 0
    groups = [g for g in data.get("group_by", []) if g.get("key_display_name") not in ("unknown", "", None)]
    return groups, data.get("meta", {}).get("count", 0)


def hydrate(entity, ids, select):
    """Fetch many entities by OpenAlex ID in bulk. Returns {short_id: record}."""
    out = {}
    ids = [short_id(i) for i in ids]
    for start in range(0, len(ids), ID_CHUNK):
        chunk = ids[start:start + ID_CHUNK]
        data = query_openalex(entity, {
            "filter": "openalex_id:" + "|".join(chunk),
            "select": select,
            "per_page": len(chunk),
        })
        for rec in (data or {}).get("results", []):
            out[short_id(rec.get("id"))] = rec
        time.sleep(0.05)
    return out


def resolve_work_ids(refs):
    """Accept OpenAlex work IDs (W...) or DOIs; return a list of W IDs."""
    out = []
    for ref in [r.strip() for r in refs.split(",") if r.strip()]:
        tail = short_id(ref)
        if tail.upper().startswith("W") and tail[1:].isdigit():
            out.append(tail.upper())
            continue
        doi = clean_doi(ref)
        data = query_openalex(f"works/https://doi.org/{doi}", {"select": "id,title"})
        if data and data.get("id"):
            out.append(short_id(data["id"]))
        else:
            sys.stderr.write(f"warning: could not resolve '{ref}' to an OpenAlex work; skipping.\n")
    return out


def clean_doi(doi):
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def emit(args, payload, render):
    """Print payload as JSON when --json is set, otherwise as human-readable text."""
    if args.json:
        print(json.dumps({**payload, "api_usage": _usage}, indent=2, ensure_ascii=False))
    else:
        render(payload)
        sys.stdout.flush()
        left = "" if _usage["remaining_usd"] is None else f"; ${_usage['remaining_usd']:.3f} of today's budget left"
        sys.stderr.write(f"[OpenAlex: {_usage['requests']} requests, ${_usage['cost_usd']:.4f}{left}]\n")


# --------------------------------------------------------------------------- find-groups
def cmd_find_groups(args):
    """
    Search works matching a research query, aggregate institutions and authors
    from a relevance-ranked sample, and show representative papers.
    """
    # Semantic search matches meaning rather than keywords, returns at most 50 works,
    # and cannot be combined with group_by or paging.
    search_param = "search.semantic" if args.semantic else "search"
    sample_size = min(args.sample_size, SEMANTIC_MAX if args.semantic else 2 * MAX_PER_PAGE)
    params = {
        search_param: args.query,
        "per_page": min(sample_size, MAX_PER_PAGE),
        "select": "id,doi,title,publication_year,cited_by_count,authorships",
    }
    if args.from_year:
        # Semantic search accepts publication_year but not from_publication_date.
        params["filter"] = (f"publication_year:>{args.from_year - 1}" if args.semantic
                            else f"from_publication_date:{args.from_year}-01-01")

    data = query_openalex("works", params)
    if not data or "results" not in data:
        print("No results returned.", file=sys.stderr)
        return 1

    total_count = data.get("meta", {}).get("count", 0)
    results = data.get("results", [])
    if sample_size > MAX_PER_PAGE and len(results) == MAX_PER_PAGE:
        more = query_openalex("works", {**params, "page": 2})
        results += (more or {}).get("results", [])[:sample_size - MAX_PER_PAGE]
    target_countries = country_set(args.countries)

    inst_stats = defaultdict(lambda: {"count": 0, "authors": [], "papers": []})

    for work in results:
        title = work.get("title") or "Untitled"
        year = work.get("publication_year")
        doi = work.get("doi") or ""
        cited = work.get("cited_by_count", 0)

        for authorship in work.get("authorships", []):
            author_name = (authorship.get("author") or {}).get("display_name")
            for inst in authorship.get("institutions", []):
                inst_name = inst.get("display_name")
                country = inst.get("country_code") or ""
                if not inst_name:
                    continue
                if target_countries and country not in target_countries:
                    continue

                stats = inst_stats[(inst_name, country)]
                stats["count"] += 1
                if author_name and author_name not in stats["authors"]:
                    stats["authors"].append(author_name)
                if not any(p["title"] == title for p in stats["papers"]):
                    stats["papers"].append({
                        "title": title,
                        "year": year,
                        "doi": doi,
                        "cited": cited,
                        "lead_author": author_name
                    })

    ranked = sorted(inst_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    payload = {
        "query": args.query,
        "total_matching_works": total_count,
        "sampled_works": len(results),
        "institutions": [
            {"institution": inst_name, "country": country, **stats}
            for (inst_name, country), stats in ranked[:args.top_n]
        ],
    }

    def render(p):
        print(f"Total matching works in OpenAlex: {p['total_matching_works']} (sampled {p['sampled_works']})\n")
        if not p["institutions"]:
            print("No matching institutions found within the specified country/filter criteria.")
            return
        print(f"Top {len(p['institutions'])} Active Institutions / Research Centers:")
        print("=" * 70)
        for idx, inst in enumerate(p["institutions"], start=1):
            country_str = f"[{inst['country']}]" if inst["country"] else ""
            authors_preview = ", ".join(inst["authors"][:4])
            print(f"\n{idx}. {inst['institution']} {country_str} (Occurrences in sample: {inst['count']})")
            print(f"   Key PIs / Researchers: {authors_preview}")
            print("   Recent / Representative Works:")
            for paper in inst["papers"][:2]:
                doi_str = f" | DOI: {paper['doi']}" if paper["doi"] else ""
                title = paper["title"] if len(paper["title"]) <= 85 else paper["title"][:85] + "..."
                print(f"     - ({paper['year']}) {title}{doi_str}")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- rank-institutions
def cmd_rank_institutions(args):
    """
    Census-style ranking over ALL matching works (server-side group_by):
    volume, total citations, citations per work, and a location quotient (LQ)
    that normalises for institution size so small specialist units are visible.
    """
    niche_filter = join_filters(
        f"from_publication_date:{args.from_year}-01-01",
        country_filter(args.countries),
        f"topics.id:{args.topics}" if args.topics else "",
        "type:article" if args.articles_only else "",
    )
    if not args.query and not args.topics:
        print("Provide --query and/or --topics.", file=sys.stderr)
        return 2

    # cited_by_count.sum is the only impact sort group_by accepts; it returns the
    # count AND the citation sum per group. A second, count-sorted page catches
    # volume leaders that the sum sort may have pushed past the 200-group ceiling.
    by_sum, total_niche = grouped(niche_filter, "authorships.institutions.id", args.query, "cited_by_count.sum:desc")
    by_cnt, _ = grouped(niche_filter, "authorships.institutions.id", args.query)
    if by_sum is None and by_cnt is None:
        return 1

    merged = {}
    for g in (by_cnt or []) + (by_sum or []):
        row = merged.setdefault(g["key"], {"name": g["key_display_name"], "works": g["count"]})
        if "sum_cited_by_count" in g:
            row["cites"] = g["sum_cited_by_count"]
    merged = {k: v for k, v in merged.items() if v["works"] >= args.min_works}
    if not merged:
        print("No institutions meet the criteria; lower --min-works or widen the query.", file=sys.stderr)
        return 1

    # Hydrate for country (the country filter is work-level, so foreign co-author
    # institutions leak into the groups) and for per-year output (LQ baseline).
    candidates = sorted(merged, key=lambda k: merged[k]["works"], reverse=True)[:150]
    info = hydrate("institutions", candidates, "id,display_name,country_code,ror,type,counts_by_year")

    baseline = query_openalex("works", {
        "filter": join_filters(f"from_publication_date:{args.from_year}-01-01", country_filter(args.countries)),
        "per_page": 1, "select": "id",
    })
    total_all = (baseline or {}).get("meta", {}).get("count", 0)

    wanted = country_set(args.countries)
    wanted_types = {t.strip().lower() for t in args.types.split(",") if t.strip()} if args.types else None
    rows = []
    for key in candidates:
        m, rec = merged[key], info.get(short_id(key), {})
        country = rec.get("country_code")
        if wanted and country not in wanted:
            continue
        if wanted_types and rec.get("type") not in wanted_types:
            continue
        inst_all = sum(c.get("works_count", 0) for c in rec.get("counts_by_year") or []
                       if c.get("year", 0) >= args.from_year)
        lq = None
        if inst_all and total_all and total_niche:
            lq = round((m["works"] / total_niche) / (inst_all / total_all), 2)
        cites = m.get("cites")
        rows.append({
            "id": short_id(key),
            "institution": m["name"],
            "country": country,
            "type": rec.get("type"),
            "ror": rec.get("ror"),
            "works": m["works"],
            "cites": cites,
            "cites_per_work": round(cites / m["works"], 1) if cites is not None else None,
            "lq": lq,
        })

    sort_key = {"lq": lambda r: r["lq"] or 0, "works": lambda r: r["works"],
                "cites": lambda r: r["cites"] or 0, "cpw": lambda r: r["cites_per_work"] or 0}[args.sort]
    rows.sort(key=sort_key, reverse=True)
    rows = rows[:args.top_n]

    # Institutions outside the 200 most-cited groups have no citation sum yet;
    # fetch it for the rows actually shown.
    for r in rows:
        if r["cites"] is not None:
            continue
        one, _ = grouped(join_filters(niche_filter, f"authorships.institutions.id:{r['id']}"),
                         "authorships.institutions.id", args.query, "cited_by_count.sum:desc")
        for g in one or []:
            if short_id(g["key"]) == r["id"] and "sum_cited_by_count" in g:
                r["cites"] = g["sum_cited_by_count"]
                r["cites_per_work"] = round(r["cites"] / r["works"], 1)
                break
    for r in rows:
        if r["cites"] is not None:
            r["cites"] = int(r["cites"])

    payload = {
        "query": args.query, "topics": args.topics, "from_year": args.from_year,
        "total_matching_works": total_niche, "sorted_by": args.sort,
        "institutions": rows,
    }

    def render(p):
        print(f"Matching works since {p['from_year']}: {p['total_matching_works']} | sorted by {p['sorted_by']}")
        print(f"{'#':>3} {'Institution':<46} {'CC':<3} {'Type':<10} {'Works':>6} {'Cites':>8} {'C/W':>6} {'LQ':>7}  ID")
        print("-" * 107)
        for i, r in enumerate(p["institutions"], start=1):
            fmt = lambda v: "-" if v is None else v
            print(f"{i:>3} {r['institution'][:46]:<46} {r['country'] or '':<3} {(r['type'] or '')[:10]:<10} {r['works']:>6} "
                  f"{fmt(r['cites']):>8} {fmt(r['cites_per_work']):>6} {fmt(r['lq']):>7}  {r['id']}")
        print("\nLQ > 1: the institution publishes more on this niche than its overall size predicts.")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- find-people
def cmd_find_people(args):
    """
    Candidate researchers, grouped from WORKS so the affiliation is as-published.

    Filtering /authors by country means "ever affiliated" and returns people who
    left years ago. A work carries the affiliation held at publication time, so
    recent works + country filter + group by author finds people who are there now.
    """
    if not (args.query or args.topics or args.institution_id):
        print("Provide --query, --topics, and/or --institution-id.", file=sys.stderr)
        return 2

    filt = join_filters(
        f"from_publication_date:{args.from_year}-01-01",
        country_filter(args.countries),
        f"topics.id:{args.topics}" if args.topics else "",
        f"authorships.institutions.id:{args.institution_id}" if args.institution_id else "",
    )
    groups, total = grouped(filt, "authorships.author.id", args.query)
    if groups is None:
        return 1

    # Over-fetch: co-authors based elsewhere leak in and are dropped after hydration.
    groups = groups[:args.limit * 3]
    info = hydrate("authors", [g["key"] for g in groups],
                   "id,display_name,orcid,works_count,cited_by_count,summary_stats,last_known_institutions,topics")

    wanted = country_set(args.countries)
    want_inst = short_id(args.institution_id).upper() if args.institution_id else None
    people = []
    for g in groups:
        a = info.get(short_id(g["key"]), {})
        insts = a.get("last_known_institutions") or []
        if wanted and not any(i.get("country_code") in wanted for i in insts):
            continue
        if want_inst and not any(short_id(i.get("id")).upper() == want_inst for i in insts):
            continue
        people.append({
            "id": short_id(g["key"]),
            "name": g["key_display_name"],
            "niche_works": g["count"],
            "orcid": a.get("orcid"),
            "h_index": (a.get("summary_stats") or {}).get("h_index"),
            "works_count": a.get("works_count"),
            "institutions": [i.get("display_name") for i in insts],
            "countries": sorted({i.get("country_code") for i in insts if i.get("country_code")}),
            "topics": [t.get("display_name") for t in (a.get("topics") or [])[:5]],
        })
        if len(people) >= args.limit:
            break

    payload = {"query": args.query, "topics": args.topics, "from_year": args.from_year,
               "total_matching_works": total, "people": people}

    def render(p):
        print(f"Matching works since {p['from_year']}: {p['total_matching_works']}\n")
        if not p["people"]:
            print("No researchers found; widen the query, years, or countries.")
            return
        for i, r in enumerate(p["people"], start=1):
            print(f"{i}. {r['name']} ({r['id']}) | niche works: {r['niche_works']} | h-index: {r['h_index']}")
            print(f"   {', '.join(r['institutions']) or 'Affiliation unknown'} {r['countries']}")
            if r["orcid"]:
                print(f"   ORCID: {r['orcid']}")
            if r["topics"]:
                print(f"   Topics: {'; '.join(r['topics'])}")
        print("\nCheck that each person's topics fit the domain: counts alone cannot tell "
              "a namesake field apart.")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- who-cites
def cmd_who_cites(args):
    """Who builds on a given work or canon? Group citing works by institution or author."""
    work_ids = resolve_work_ids(args.works)
    if not work_ids:
        print("No resolvable works given.", file=sys.stderr)
        return 1

    group_field = {"institution": "authorships.institutions.id", "author": "authorships.author.id"}[args.by]
    filt = join_filters(
        "cites:" + "|".join(work_ids),
        f"from_publication_date:{args.from_year}-01-01" if args.from_year else "",
        country_filter(args.countries),
    )
    groups, total = grouped(filt, group_field)
    if groups is None:
        return 1

    wanted = country_set(args.countries)
    rows = []
    if wanted:
        # Drop co-author institutions/people outside the requested countries.
        groups = groups[:args.top_n * 3]
        if args.by == "institution":
            info = hydrate("institutions", [g["key"] for g in groups], "id,country_code")
            groups = [g for g in groups if info.get(short_id(g["key"]), {}).get("country_code") in wanted]
        else:
            info = hydrate("authors", [g["key"] for g in groups], "id,last_known_institutions")
            groups = [g for g in groups if any(
                i.get("country_code") in wanted
                for i in info.get(short_id(g["key"]), {}).get("last_known_institutions") or [])]
    for g in groups[:args.top_n]:
        rows.append({"id": short_id(g["key"]), "name": g["key_display_name"], "citing_works": g["count"]})

    payload = {"anchor_works": work_ids, "grouped_by": args.by, "total_citing_works": total, "results": rows}

    def render(p):
        print(f"Anchor works: {', '.join(p['anchor_works'])} | citing works: {p['total_citing_works']}\n")
        for i, r in enumerate(p["results"], start=1):
            print(f"{i:>3}. {r['name']} ({r['id']}) | citing works: {r['citing_works']}")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- suggest-topics
def cmd_suggest_topics(args):
    """
    Turn a prose description of a niche into OpenAlex topic IDs: run a semantic
    search, then tally the topics of the closest works.
    """
    data = query_openalex("works", {"search.semantic": args.text, "per_page": SEMANTIC_MAX,
                                    "select": "id,title,topics"})
    results = (data or {}).get("results") or []
    if not results:
        print("No works matched that description.", file=sys.stderr)
        return 1

    tally = {}
    for w in results:
        for t in w.get("topics") or []:
            row = tally.setdefault(t["id"], {
                "id": short_id(t["id"]), "topic": t.get("display_name"),
                "subfield": (t.get("subfield") or {}).get("display_name"),
                "field": (t.get("field") or {}).get("display_name"), "works": 0})
            row["works"] += 1
    topics = sorted(tally.values(), key=lambda r: r["works"], reverse=True)[:args.top_n]
    payload = {"text": args.text, "sampled_works": len(results), "topics": topics,
               "topics_filter": "|".join(t["id"] for t in topics[:3]),
               "closest_works": [w.get("title") for w in results[:5]]}

    def render(p):
        print(f"Topics of the {p['sampled_works']} closest works:\n")
        for t in p["topics"]:
            print(f"  {t['id']:<8} {t['works']:>3} works  {t['topic']}  [{t['subfield']} / {t['field']}]")
        print("\nClosest works (check these look right before trusting the topics):")
        for title in p["closest_works"]:
            print(f"  - {title}")
        print(f"\nPick the topics that fit, then e.g.: rank-institutions --topics '{p['topics_filter']}'")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- collaborators
def cmd_collaborators(args):
    """Who a researcher publishes with: co-authors, or the institutions they work with."""
    author_id = short_id(args.id).upper()
    filt = join_filters(f"author.id:{author_id}",
                        f"from_publication_date:{args.from_year}-01-01" if args.from_year else "")
    group_field = {"author": "authorships.author.id", "institution": "authorships.institutions.id"}[args.by]
    groups, total = grouped(filt, group_field)
    if groups is None:
        return 1
    groups = [g for g in groups if short_id(g["key"]).upper() != author_id]
    wanted = country_set(args.countries)
    groups = groups[:args.top_n * (4 if wanted else 1)]

    rows = []
    if args.by == "author":
        info = hydrate("authors", [g["key"] for g in groups],
                       "id,orcid,summary_stats,last_known_institutions")
        for g in groups:
            a = info.get(short_id(g["key"]), {})
            insts = a.get("last_known_institutions") or []
            if wanted and not any(i.get("country_code") in wanted for i in insts):
                continue
            rows.append({"id": short_id(g["key"]), "name": g["key_display_name"], "joint_works": g["count"],
                         "h_index": (a.get("summary_stats") or {}).get("h_index"), "orcid": a.get("orcid"),
                         "institutions": [i.get("display_name") for i in insts[:2]],
                         "countries": sorted({i.get("country_code") for i in insts if i.get("country_code")})})
    else:
        info = hydrate("institutions", [g["key"] for g in groups], "id,country_code,type")
        for g in groups:
            rec = info.get(short_id(g["key"]), {})
            if wanted and rec.get("country_code") not in wanted:
                continue
            rows.append({"id": short_id(g["key"]), "name": g["key_display_name"], "joint_works": g["count"],
                         "country": rec.get("country_code"), "type": rec.get("type")})

    payload = {"author_id": author_id, "grouped_by": args.by, "from_year": args.from_year,
               "works_considered": total, "collaborators": rows[:args.top_n]}

    def render(p):
        since = f" since {p['from_year']}" if p["from_year"] else ""
        print(f"{p['author_id']}: {p['works_considered']} works{since}\n")
        for i, r in enumerate(p["collaborators"], start=1):
            if p["grouped_by"] == "author":
                where = f"{', '.join(r['institutions']) or '?'} {r['countries']}"
                print(f"{i:>3}. {r['name']} ({r['id']}) | joint works: {r['joint_works']} | h-index: {r['h_index']}\n"
                      f"     {where}")
            else:
                print(f"{i:>3}. {r['name']} ({r['id']}) [{r['country'] or '?'}, {r['type'] or '?'}] "
                      f"| joint works: {r['joint_works']}")
        if p["grouped_by"] == "institution":
            print("\nThe researcher's own institutions are included; they show where the work was done.")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- funding
def cmd_funding(args):
    """Which funders back a researcher, an institution, or a niche (from works' funding acknowledgements)."""
    if not (args.author_id or args.institution_id or args.query or args.topics):
        print("Provide --author-id, --institution-id, --query, and/or --topics.", file=sys.stderr)
        return 2
    filt = join_filters(
        f"author.id:{short_id(args.author_id)}" if args.author_id else "",
        f"authorships.institutions.id:{short_id(args.institution_id)}" if args.institution_id else "",
        f"topics.id:{args.topics}" if args.topics else "",
        country_filter(args.countries),
        f"from_publication_date:{args.from_year}-01-01",
    )
    groups, total = grouped(filt, "funders.id", args.query)
    if groups is None:
        return 1
    groups = groups[:args.top_n]
    info = hydrate("funders", [g["key"] for g in groups], "id,display_name,country_code,homepage_url")
    rows = []
    for g in groups:
        rec = info.get(short_id(g["key"]), {})
        rows.append({"id": short_id(g["key"]), "funder": rec.get("display_name") or g["key_display_name"],
                     "country": rec.get("country_code"), "homepage": rec.get("homepage_url"),
                     "funded_works": g["count"]})

    payload = {"from_year": args.from_year, "works_considered": total, "funders": rows}

    def render(p):
        print(f"Works considered since {p['from_year']}: {p['works_considered']}\n")
        if not p["funders"]:
            print("No funder acknowledgements recorded for these works.")
            return
        for i, r in enumerate(p["funders"], start=1):
            print(f"{i:>3}. {r['funder']} [{r['country'] or '?'}] ({r['id']}) | funded works: {r['funded_works']}")
        print("\nCounts come from funding acknowledgements on papers, which many works lack. "
              "Read them as a lower bound and a guide to who funds this area, not as grant totals.")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- author-profile
AUTHOR_SELECT = ("id,display_name,orcid,works_count,cited_by_count,summary_stats,"
                 "last_known_institutions,affiliations,topics")


def candidate_summary(a):
    insts = a.get("last_known_institutions") or []
    return {
        "id": short_id(a.get("id")),
        "name": a.get("display_name"),
        "orcid": a.get("orcid"),
        "works_count": a.get("works_count", 0),
        "institutions": [i.get("display_name") for i in insts],
        "topics": [t.get("display_name") for t in (a.get("topics") or [])[:3]],
    }


def resolve_author(args):
    """
    Returns (author, other_candidates, institution_matched).
    An ORCID or OpenAlex ID is decisive; a bare name is only ever a best guess.
    """
    if args.orcid:
        orcid = args.orcid.strip().rsplit("/", 1)[-1]
        # One ORCID can sit on several split OpenAlex records; take the fullest one
        # and list the rest so the caller knows the metrics are partial.
        data = query_openalex("authors", {"filter": f"orcid:{orcid}", "select": AUTHOR_SELECT, "per_page": 25})
        found = sorted((data or {}).get("results") or [], key=lambda a: a.get("works_count", 0), reverse=True)
        if not found:
            return None, [], None
        return found[0], [candidate_summary(a) for a in found[1:]], None
    if args.id:
        a = query_openalex(f"authors/{short_id(args.id)}", {"select": AUTHOR_SELECT})
        return a, [], None

    data = query_openalex("authors", {"search": args.name, "per_page": 10, "select": AUTHOR_SELECT})
    found = (data or {}).get("results") or []
    if not found:
        return None, [], None

    author, matched = None, None
    if args.institution:
        matched = False
        needle = args.institution.lower()
        for a in found:
            # Match current AND past affiliations: people move, records lag.
            names = [i.get("display_name", "") for i in a.get("last_known_institutions") or []]
            names += [(aff.get("institution") or {}).get("display_name", "") for aff in a.get("affiliations") or []]
            if any(needle in n.lower() for n in names):
                author, matched = a, True
                break
    if not author:
        author = found[0]
    others = [candidate_summary(a) for a in found if a.get("id") != author.get("id")]
    return author, others, matched


def cmd_author_profile(args):
    """Lookup researcher profile, metrics, and key publications."""
    author, others, institution_matched = resolve_author(args)
    if not author:
        print("Author not found.", file=sys.stderr)
        return 1

    author_id = short_id(author.get("id"))
    summary = author.get("summary_stats") or {}

    works_data = query_openalex("works", {
        "filter": f"author.id:{author_id}",
        "sort": "publication_date:desc",
        "per_page": args.limit,
        "select": "id,doi,title,publication_year,cited_by_count,type",
    }) or {}

    timeline = []
    for aff in author.get("affiliations") or []:
        years = aff.get("years") or []
        if years:
            timeline.append({"institution": (aff.get("institution") or {}).get("display_name"),
                             "country": (aff.get("institution") or {}).get("country_code"),
                             "first_year": min(years), "last_year": max(years)})
    timeline.sort(key=lambda t: t["last_year"], reverse=True)

    payload = {
        "name": author.get("display_name"),
        "openalex_id": author.get("id"),
        "orcid": author.get("orcid"),
        "affiliations": [i.get("display_name") for i in author.get("last_known_institutions") or []],
        "affiliation_timeline": timeline[:8],
        "topics": [t.get("display_name") for t in (author.get("topics") or [])[:5]],
        "institution_matched": institution_matched,
        "other_candidates": others,
        "works_count": author.get("works_count", 0),
        "cited_by_count": author.get("cited_by_count", 0),
        "h_index": summary.get("h_index"),
        "recent_works": [
            {
                "title": w.get("title") or "Untitled",
                "year": w.get("publication_year"),
                "doi": w.get("doi"),
                "cited": w.get("cited_by_count", 0),
            }
            for w in works_data.get("results", [])
        ],
    }

    def render(p):
        print(f"\nResearcher Profile: {p['name']}")
        print("=" * 60)
        print(f"OpenAlex ID: {p['openalex_id']}")
        print(f"ORCID: {p['orcid'] or 'none on record'}")
        print(f"Current Affiliation: {', '.join(p['affiliations']) if p['affiliations'] else 'Independent / Not specified'}")
        h_index = p["h_index"] if p["h_index"] is not None else "N/A"
        print(f"Metrics: {p['works_count']} works | {p['cited_by_count']} citations | h-index: {h_index}")
        if p["topics"]:
            print(f"Topics: {'; '.join(p['topics'])}")
        if p["institution_matched"] is False:
            print(f"WARNING: no candidate matched institution '{args.institution}'; showing the top name match.")
        if p["affiliation_timeline"]:
            print("\nAffiliation timeline:")
            for t in p["affiliation_timeline"]:
                print(f"  {t['first_year']}-{t['last_year']}  {t['institution']} [{t['country'] or '?'}]")
        if p["recent_works"]:
            print(f"\nRecent Publications (Top {len(p['recent_works'])}):")
            for w in p["recent_works"]:
                print(f"  - ({w['year']}) {w['title']}")
                print(f"    DOI: {w['doi'] or 'No DOI'} | Citations: {w['cited']}")
        if p["other_candidates"]:
            print(f"\nOther profiles with a similar name ({len(p['other_candidates'])}). "
                  "Namesakes or split records; rerun with --id or --orcid to pick one:")
            for c in p["other_candidates"]:
                print(f"  {c['id']:<13} works={c['works_count']:<5} "
                      f"{(c['institutions'] or ['?'])[0]} | {'; '.join(c['topics'])}")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- h-index-at
def h_index(citation_counts):
    h = 0
    for rank, c in enumerate(sorted(citation_counts, reverse=True), start=1):
        if c < rank:
            break
        h = rank
    return h


def cmd_h_index_at(args):
    """
    Reconstruct an author's h-index as of the end of a past year.

    cites_at(work, T) = cited_by_count - citations received in years after T,
    using each work's counts_by_year. That series only reaches back about a
    decade, so years before the window cannot be reconstructed.
    """
    author_id = short_id(args.id)
    works, cursor = [], "*"
    for _ in range(args.max_pages):
        data = query_openalex("works", {
            "filter": f"author.id:{author_id}",
            "select": "id,publication_year,cited_by_count,counts_by_year",
            "per_page": MAX_PER_PAGE, "cursor": cursor,
        })
        if not data or not data.get("results"):
            break
        works.extend(data["results"])
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(0.1)
    if not works:
        print("No works found for that author ID.", file=sys.stderr)
        return 1

    window = [c["year"] for w in works for c in w.get("counts_by_year") or []]
    window_start = min(window) if window else None
    if window_start is not None and args.year < window_start - 1:
        print(f"Cannot reconstruct {args.year}: per-year citation data starts in {window_start}.", file=sys.stderr)
        return 1

    then, now = [], []
    for w in works:
        now.append(w.get("cited_by_count", 0))
        if (w.get("publication_year") or 9999) > args.year:
            continue
        later = sum(c.get("cited_by_count", 0) for c in w.get("counts_by_year") or [] if c["year"] > args.year)
        then.append(max(w.get("cited_by_count", 0) - later, 0))

    payload = {
        "author_id": author_id, "year": args.year,
        "h_index_at_year": h_index(then), "works_by_year": len(then), "citations_by_year": sum(then),
        "h_index_now": h_index(now), "works_now": len(works),
        "truncated": bool(cursor),
    }

    def render(p):
        print(f"Author {p['author_id']} as of end of {p['year']}: h-index {p['h_index_at_year']} "
              f"({p['works_by_year']} works, {p['citations_by_year']} citations)")
        print(f"Today: h-index {p['h_index_now']} ({p['works_now']} works)")
        if p["truncated"]:
            print("WARNING: not all works were fetched; raise --max-pages.")
        print("Computed from OpenAlex only. Do not compare with Google Scholar figures, which run higher.")

    emit(args, payload, render)
    return 0


# --------------------------------------------------------------------------- verify-work
def _norm(text):
    """Lowercase, strip accents and punctuation, for forgiving name comparison."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else " " for c in text.lower()).split()


def author_in_byline(expected, authors):
    """True when the expected surname (last token) appears in any byline name."""
    tokens = _norm(expected)
    if not tokens:
        return None
    surname = tokens[-1]
    return any(surname in _norm(a.get("name")) for a in authors)


def work_payload(work, matched_by, expect_author=None):
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    authors = [
        {
            "name": (a.get("author") or {}).get("display_name"),
            "openalex_id": short_id((a.get("author") or {}).get("id")),
            "orcid": (a.get("author") or {}).get("orcid"),
            "position": a.get("author_position"),
            "corresponding": a.get("is_corresponding"),
            "institutions": [i.get("display_name") for i in a.get("institutions", [])],
        }
        for a in work.get("authorships", [])
    ]
    payload = {
        "found": True,
        "title": work.get("title"),
        "doi": work.get("doi"),
        "openalex_id": work.get("id"),
        "publication_date": work.get("publication_date"),
        "publication_year": work.get("publication_year"),
        "type": work.get("type"),
        "venue": src.get("display_name"),
        "is_retracted": work.get("is_retracted"),
        "open_access_url": (work.get("open_access") or {}).get("oa_url"),
        "cited_by_count": work.get("cited_by_count", 0),
        "matched_by": matched_by,
        "authors": authors,
    }
    if expect_author:
        payload["expected_author"] = expect_author
        payload["expected_author_in_byline"] = author_in_byline(expect_author, authors)
    return payload


def render_work(p):
    print("\nVerified Work Metadata:")
    print("=" * 60)
    print(f"Title: {p['title']}")
    print(f"DOI: {p['doi']}")
    print(f"OpenAlex ID: {p['openalex_id']}")
    print(f"Publication Date: {p['publication_date']} (Year: {p['publication_year']})")
    print(f"Type: {p['type']}")
    print(f"Venue/Host: {p['venue'] or 'Preprint repository / Working paper'}")
    print(f"Citations: {p['cited_by_count']}")
    if p["is_retracted"]:
        print("WARNING: this work is marked as RETRACTED.")
    if p["open_access_url"]:
        print(f"Open access copy: {p['open_access_url']}")
    if p["matched_by"] == "title_search":
        print("NOTE: matched by title search (best hit); confirm the title is the intended work.")
    if "expected_author_in_byline" in p:
        verdict = "FOUND in byline" if p["expected_author_in_byline"] else "NOT in byline"
        print(f"Expected author '{p['expected_author']}': {verdict}")

    print("\nAuthors and Affiliations (in byline order):")
    for a in p["authors"]:
        inst_str = f" ({', '.join(a['institutions'])})" if a["institutions"] else ""
        flag = " [corresponding]" if a["corresponding"] else ""
        print(f"  - {a['name']}{inst_str}{flag}")


def cmd_verify_work(args):
    """Verify metadata of one publication, or check a whole list of DOIs at once."""
    dois = []
    if args.doi:
        dois = [clean_doi(d) for d in args.doi.split(",") if d.strip()]
    elif args.doi_file:
        with open(args.doi_file, "r", encoding="utf-8") as f:
            dois = [clean_doi(line) for line in f if line.strip() and not line.startswith("#")]

    if not dois:
        data = query_openalex("works", {"search": args.title, "per_page": 3})
        if not data or not data.get("results"):
            print("Work not found.", file=sys.stderr)
            return 1
        emit(args, work_payload(data["results"][0], "title_search", args.expect_author), render_work)
        return 0

    # One request per 50 DOIs. DOIs are case-insensitive, so compare lowercased.
    found = {}
    for start in range(0, len(dois), ID_CHUNK):
        chunk = dois[start:start + ID_CHUNK]
        data = query_openalex("works", {"filter": "doi:" + "|".join(chunk), "per_page": len(chunk)})
        for w in (data or {}).get("results", []):
            found[clean_doi(w.get("doi") or "").lower()] = w

    if len(dois) == 1:
        work = found.get(dois[0].lower())
        if not work:
            print("Work not found.", file=sys.stderr)
            return 1
        emit(args, work_payload(work, "doi", args.expect_author), render_work)
        return 0

    results = []
    for d in dois:
        work = found.get(d.lower())
        results.append(work_payload(work, "doi", args.expect_author) if work
                       else {"found": False, "doi": f"https://doi.org/{d}"})
    payload = {"checked": len(dois), "found": sum(r["found"] for r in results),
               "missing": [r["doi"] for r in results if not r["found"]], "works": results}

    def render(p):
        print(f"Checked {p['checked']} DOIs: {p['found']} found, {len(p['missing'])} not in OpenAlex\n")
        for r in p["works"]:
            if not r["found"]:
                print(f"  NOT FOUND  {r['doi']}")
                continue
            flags = []
            if r["is_retracted"]:
                flags.append("RETRACTED")
            if r.get("expected_author_in_byline") is False:
                flags.append(f"'{r['expected_author']}' NOT in byline")
            first = r["authors"][0]["name"] if r["authors"] else "?"
            title = r["title"] or "Untitled"
            print(f"  ok  {r['doi']}\n      ({r['publication_year']}, {r['type']}) {title[:80]} | first author: {first}"
                  f" | {len(r['authors'])} authors" + (f"\n      !! {'; '.join(flags)}" if flags else ""))
        if p["missing"]:
            print("\nNot found does not prove fabrication: recent preprints and some series are indexed late. "
                  "Check those DOIs at https://doi.org/ directly.")

    emit(args, payload, render)
    return 0 if payload["found"] else 1


def main():
    parser = argparse.ArgumentParser(description="OpenAlex Academic Discovery & Verification Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared by every subcommand so the flag works after the subcommand name
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text")

    query_help = ("Search query; supports quoted phrases and AND/OR/NOT, "
                  "e.g. '\"method phrase\" (\"domain a\" OR \"domain b\")'")
    countries_help = "Comma-separated ISO 3166-1 alpha-2 codes (e.g. US,CA,JP; use GB, not UK)"
    topics_help = "OpenAlex topic IDs, |-separated (e.g. T10028|T11234), instead of or with --query"

    # find-groups
    p = subparsers.add_parser("find-groups", parents=[common],
                              help="Quick look: institutions, names, and sample papers from top search hits")
    p.add_argument("--query", "-q", required=True, help=query_help)
    p.add_argument("--countries", "-c", help=countries_help)
    p.add_argument("--from-year", type=int, default=2021, help="Filter works published from this year onward")
    p.add_argument("--sample-size", type=int, default=30,
                   help=f"Number of works to sample (default: 30, max: {2 * MAX_PER_PAGE})")
    p.add_argument("--top-n", type=int, default=5, help="Number of top institutions to display (default: 5)")
    p.add_argument("--semantic", action="store_true",
                   help=f"Treat --query as a prose description and match by meaning (max {SEMANTIC_MAX} works)")
    p.set_defaults(func=cmd_find_groups)

    # rank-institutions
    p = subparsers.add_parser("rank-institutions", parents=[common],
                              help="Census ranking over all matching works: volume, impact, specialization (LQ)")
    p.add_argument("--query", "-q", help=query_help)
    p.add_argument("--topics", help=topics_help)
    p.add_argument("--countries", "-c", help=countries_help)
    p.add_argument("--from-year", type=int, default=2021, help="Count works published from this year onward")
    p.add_argument("--min-works", type=int, default=5, help="Ignore institutions with fewer matching works (default: 5)")
    p.add_argument("--sort", choices=["lq", "works", "cites", "cpw"], default="lq",
                   help="lq = specialization (default), works = volume, cites = total citations, cpw = citations per work")
    p.add_argument("--articles-only", action="store_true", help="Restrict to type:article")
    p.add_argument("--types", help="Keep only these institution types, comma-separated: " + ", ".join(INSTITUTION_TYPES))
    p.add_argument("--top-n", type=int, default=15, help="Rows to display (default: 15)")
    p.set_defaults(func=cmd_rank_institutions)

    # find-people
    p = subparsers.add_parser("find-people", parents=[common],
                              help="Researchers currently active on a topic in given countries or at an institution")
    p.add_argument("--query", "-q", help=query_help)
    p.add_argument("--topics", help=topics_help)
    p.add_argument("--countries", "-c", help=countries_help)
    p.add_argument("--institution-id", help="OpenAlex institution ID (I...), e.g. from rank-institutions")
    p.add_argument("--from-year", type=int, default=2022, help="Only count works from this year onward (keep recent)")
    p.add_argument("--limit", type=int, default=15, help="People to display (default: 15)")
    p.set_defaults(func=cmd_find_people)

    # who-cites
    p = subparsers.add_parser("who-cites", parents=[common],
                              help="Institutions or authors whose work cites given anchor works")
    p.add_argument("--works", "-w", required=True, help="Comma-separated DOIs and/or OpenAlex work IDs (W...)")
    p.add_argument("--by", choices=["institution", "author"], default="institution")
    p.add_argument("--countries", "-c", help=countries_help)
    p.add_argument("--from-year", type=int, help="Only count citing works from this year onward")
    p.add_argument("--top-n", type=int, default=15, help="Rows to display (default: 15)")
    p.set_defaults(func=cmd_who_cites)

    # suggest-topics
    p = subparsers.add_parser("suggest-topics", parents=[common],
                              help="Turn a prose description of a niche into OpenAlex topic IDs")
    p.add_argument("--text", "-t", required=True, help="One or two sentences describing the research niche")
    p.add_argument("--top-n", type=int, default=8, help="Topics to display (default: 8)")
    p.set_defaults(func=cmd_suggest_topics)

    # collaborators
    p = subparsers.add_parser("collaborators", parents=[common],
                              help="A researcher's co-authors or partner institutions")
    p.add_argument("--id", required=True, help="OpenAlex author ID (A...), from author-profile or find-people")
    p.add_argument("--by", choices=["author", "institution"], default="author")
    p.add_argument("--from-year", type=int, help="Only count works from this year onward")
    p.add_argument("--countries", "-c", help=countries_help)
    p.add_argument("--top-n", type=int, default=15, help="Rows to display (default: 15)")
    p.set_defaults(func=cmd_collaborators)

    # funding
    p = subparsers.add_parser("funding", parents=[common],
                              help="Funders acknowledged by a researcher's, institution's, or niche's works")
    p.add_argument("--author-id", help="OpenAlex author ID (A...)")
    p.add_argument("--institution-id", help="OpenAlex institution ID (I...)")
    p.add_argument("--query", "-q", help=query_help)
    p.add_argument("--topics", help=topics_help)
    p.add_argument("--countries", "-c", help=countries_help)
    p.add_argument("--from-year", type=int, default=2019, help="Only count works from this year onward (default: 2019)")
    p.add_argument("--top-n", type=int, default=15, help="Rows to display (default: 15)")
    p.set_defaults(func=cmd_funding)

    # author-profile
    p = subparsers.add_parser("author-profile", parents=[common],
                              help="Lookup researcher profile and top publications")
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--name", "-n", help="Researcher name (ambiguous; prefer --orcid or --id when known)")
    who.add_argument("--orcid", help="ORCID iD (decisive)")
    who.add_argument("--id", help="OpenAlex author ID (A...)")
    p.add_argument("--institution", "-i", help="Institution keyword to disambiguate a name (current or past)")
    p.add_argument("--limit", type=int, default=5, help="Number of recent publications to fetch")
    p.set_defaults(func=cmd_author_profile)

    # h-index-at
    p = subparsers.add_parser("h-index-at", parents=[common],
                              help="Reconstruct an author's h-index as of the end of a past year")
    p.add_argument("--id", required=True, help="OpenAlex author ID (A...), from author-profile")
    p.add_argument("--year", type=int, required=True, help="Target year")
    p.add_argument("--max-pages", type=int, default=20, help="Pages of 100 works to fetch (default: 20)")
    p.set_defaults(func=cmd_h_index_at)

    # verify-work
    p = subparsers.add_parser("verify-work", parents=[common],
                              help="Verify paper or preprint claims and co-authors")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--doi", help="DOI, or several separated by commas (checked in one request)")
    target.add_argument("--doi-file", help="Text file with one DOI per line (lines starting with # are ignored)")
    target.add_argument("--title", "-t", help="Title search string if DOI is unknown")
    p.add_argument("--expect-author", help="Name that should be on the byline; reports whether the surname is there")
    p.set_defaults(func=cmd_verify_work)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

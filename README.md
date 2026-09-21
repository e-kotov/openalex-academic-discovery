# OpenAlex Academic Discovery & Lab Scouting

An agent skill and zero-dependency CLI for scouting research groups, finding PhD, postdoc and fellowship host institutions, finding and profiling scholars, and verifying publication claims with [OpenAlex](https://openalex.org).

It follows the open [Agent Skills](https://agentskills.io/specification) format (`SKILL.md` plus bundled scripts), so the same folder works in Claude Code, Codex, Gemini CLI, Antigravity, Cursor, claude.ai, ChatGPT and Perplexity.

## What it does

| Command | Question it answers |
| --- | --- |
| `suggest-topics` | Which OpenAlex topics describe a niche written in plain prose? |
| `rank-institutions` | Which institutions lead or specialise in a topic? Volume, citations, citations per work, and a size-normalised specialisation score (LQ) over all matching works. |
| `find-people` | Who is publishing on it right now, in given countries or at one institution? |
| `find-groups` | Quick look: institutions, names and sample papers from the top search hits, by keyword or by meaning (`--semantic`). |
| `who-cites` | Which institutions or authors build on a given paper, dataset or tool? |
| `collaborators` | Who does a researcher publish with, and at which institutions? |
| `funding` | Which funders back a researcher, an institution or a niche? |
| `author-profile` | Who is this researcher? Current affiliation, timeline, metrics, recent work, and same-name candidates to rule out. |
| `h-index-at` | What was their h-index at the end of a past year? |
| `verify-work` | Does this paper or preprint exist, and are its date, venue and byline as claimed? One DOI, a whole list, or a title. |

## Install in a chat app (no terminal needed)

Download one file, upload it on the app's Skills page, and start asking.

### ChatGPT

1. Download **[openalex-academic-discovery.zip](https://github.com/e-kotov/openalex-academic-discovery/releases/latest/download/openalex-academic-discovery.zip)**.
2. Open **<https://chatgpt.com/skills>**.
3. Choose **Create → Upload from your computer** and pick the zip.

Skills in ChatGPT are currently offered on Business, Enterprise, Edu and Healthcare workspaces, and an admin may need to enable uploads. If you do not see the Skills page, create a Project instead, paste the text of [SKILL.md](skills/openalex-academic-discovery/SKILL.md) into its instructions, and attach [openalex_cli.py](skills/openalex-academic-discovery/scripts/openalex_cli.py) and [api.md](skills/openalex-academic-discovery/references/api.md).

### Claude (claude.ai and the desktop app)

1. Download **[openalex-academic-discovery.zip](https://github.com/e-kotov/openalex-academic-discovery/releases/latest/download/openalex-academic-discovery.zip)**.
2. Open **<https://claude.ai/customize/skills>**.
3. Press **+**, choose to upload a skill, and pick the zip.

Code execution must be switched on under Settings → Capabilities.

### Perplexity

Skills in Perplexity only work inside **Computer**, its agent mode, and not in ordinary Perplexity search threads. Custom skills were [introduced as a Computer feature](https://www.perplexity.ai/changelog/what-we-shipped---march-6-2026), and Computer is [available to Pro and Max subscribers](https://www.perplexity.ai/changelog/what-we-shipped---march-13-2026). Perplexity's own guide: [How to use Computer skills](https://www.perplexity.ai/hub/academy/how-to-use-computer-skills).

1. Download **[openalex-academic-discovery-flat.zip](https://github.com/e-kotov/openalex-academic-discovery/releases/latest/download/openalex-academic-discovery-flat.zip)** (Perplexity wants `SKILL.md` at the top of the zip, so it has its own file).
2. Open **<https://www.perplexity.ai/computer/skills>**.
3. Choose **Create skill → Upload a skill** and pick the zip.
4. Start a Computer task and ask your question; Computer picks the skill up when it is relevant.

### Then try it

Name the skill in your request. Apps load skills on their own when they judge them relevant, but naming it removes the guesswork:

> Use the openalex-academic-discovery skill to find which universities in Canada and Japan specialise in machine learning for drug discovery, and who I should contact there.

> Use the openalex-academic-discovery skill to check these DOIs and tell me whether Jane Doe is really an author on each: ...

### Good to know for chat apps

- **Network access.** Chat apps run skills in a locked-down sandbox that often cannot reach `api.openalex.org`. The skill then switches to looking up the same OpenAlex pages with the app's web browsing, which is slower but works. In Claude you can widen access under Settings → Capabilities (on Team and Enterprise plans an owner has to allow `api.openalex.org`). ChatGPT and Perplexity do not document this setting.
- **API key.** Chat apps give you no safe place to store a key, so the skill runs on OpenAlex's small keyless allowance there. That is enough for a few dozen lookups a day. For heavier use, run the skill in one of the coding agents below with a free key.
- Both zips are rebuilt for every [release](https://github.com/e-kotov/openalex-academic-discovery/releases/latest), so these links always fetch the newest version.

## Get a free OpenAlex API key (coding agents and the CLI)

OpenAlex meters usage as a daily budget. Without a key you get about $0.10 a day, roughly 100 searches. A free key raises that tenfold, which is enough for normal use of this skill.

1. Create a free account at <https://openalex.org>.
2. Copy your key from <https://openalex.org/settings/api>.
3. Make it available as `OPENALEX_API_KEY`, in any one of these ways:
   ```bash
   export OPENALEX_API_KEY="..."                      # shell profile
   echo 'OPENALEX_API_KEY=...' >> ~/.env              # or a .env file in the working directory
   security add-generic-password -a "$USER" -s openalex_api_key -w   # macOS Keychain, prompts for the key
   ```

The CLI sends the key as an `Authorization` header, never in the URL. Do not paste the key into an agent chat. Details on budgets and prices: <https://help.openalex.org/api/authentication/>.

## Install in a coding agent

The skill is the folder `skills/openalex-academic-discovery/`. Installing means putting that folder where your agent looks for skills.

### Any agent, one line

```bash
npx skills add e-kotov/openalex-academic-discovery
```

[`skills`](https://github.com/vercel-labs/skills) detects the agents you have installed and copies the skill to each. Add `-g` for a user-wide install or `-a codex` (for example) to target one agent.

### Claude Code

```
/plugin marketplace add e-kotov/openalex-academic-discovery
/plugin install openalex-academic-discovery@openalex-academic-discovery
```

Or manually:

```bash
git clone https://github.com/e-kotov/openalex-academic-discovery
cp -R openalex-academic-discovery/skills/openalex-academic-discovery ~/.claude/skills/
```

Use `<project>/.claude/skills/` instead for a single project.

### Codex CLI

```bash
git clone https://github.com/e-kotov/openalex-academic-discovery
mkdir -p ~/.agents/skills
cp -R openalex-academic-discovery/skills/openalex-academic-discovery ~/.agents/skills/
```

For one project, use `<project>/.agents/skills/`.

Codex's default sandbox blocks network access, so the first API call fails until you approve it. Either approve the command when Codex asks, or start Codex with network enabled:

```bash
codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true
```

### Gemini CLI

```bash
gemini skills install https://github.com/e-kotov/openalex-academic-discovery.git --path skills/openalex-academic-discovery
```

### Google Antigravity (IDE and `agy` CLI)

The repository is also an Antigravity plugin:

```bash
git clone https://github.com/e-kotov/openalex-academic-discovery
agy plugin install ./openalex-academic-discovery
```

Or copy the skill folder to `~/.gemini/config/skills/` (IDE and app) or `~/.gemini/antigravity-cli/skills/` (CLI).

### Cursor and other agents that read Agent Skills

Copy the skill folder into `<project>/.agents/skills/`, or use `npx skills add` above. No git? Download [the zip](https://github.com/e-kotov/openalex-academic-discovery/releases/latest/download/openalex-academic-discovery.zip), unpack it, and move the folder there.

### Calling the skill by name

Agents pick the skill up automatically when a request matches its description. To be sure it is used, say so in the prompt ("Use the openalex-academic-discovery skill to ...") or invoke it directly:

| Agent | Explicit invocation |
| --- | --- |
| Claude Code | `/openalex-academic-discovery <your request>` |
| Codex | `$openalex-academic-discovery <your request>` |
| Antigravity | `/openalex-academic-discovery <your request>` |
| Gemini CLI, Cursor, others | name the skill in the prompt |

## Use the CLI directly

Python 3.8+, standard library only.

```bash
CLI=skills/openalex-academic-discovery/scripts/openalex_cli.py

# Which institutions specialise in a topic?
python3 $CLI rank-institutions \
  --query '"machine learning" ("protein folding" OR "drug discovery")' \
  --countries US,CA,JP --from-year 2022

# Who works on it there now?
python3 $CLI find-people --query '"machine learning" "drug discovery"' --countries CA --from-year 2022

# Describe the niche in prose, get topic IDs to use with --topics
python3 $CLI suggest-topics --text "neural networks that predict protein structure from sequence"

# A researcher's co-authors and funders
python3 $CLI collaborators --id A5070580886 --from-year 2020
python3 $CLI funding --author-id A5070580886

# Who builds on a given paper?
python3 $CLI who-cites --works 10.1038/nature14539 --by institution --from-year 2023

# Profile a researcher (prefer --orcid or --id when you have them)
python3 $CLI author-profile --name "Full Name" --institution "Institution keyword"

# Verify a publication, or a whole list with a byline check
python3 $CLI verify-work --doi 10.1038/nature14539
python3 $CLI verify-work --doi-file dois.txt --expect-author "Full Name"
```

Wrap queries in single quotes so the inner double-quoted phrases reach OpenAlex intact. Country codes are ISO 3166-1 alpha-2 (`GB`, not `UK`). Add `--json` to any command for machine-readable output, and `-h` for all options.

Every run reports what it cost and how much of the day's OpenAlex budget is left (on stderr, or under `api_usage` with `--json`).

Exit status: `0` success, `1` nothing found, `2` bad arguments, `3` network unreachable, `4` API key rejected or daily budget spent.

## Related

OpenAlex runs an official [MCP connector](https://help.openalex.org/access/connector/) with free-text reference matching and one-call profiles of a set of works. It complements this skill, which adds the scouting workflows, size-normalised institution ranking and citation totals that the connector does not provide.

## Repository structure

```
.github/workflows/release.yml        Builds the release zips when a v* tag is pushed
plugin.json                          Antigravity plugin manifest
.claude-plugin/                      Claude Code plugin + marketplace manifests
skills/openalex-academic-discovery/
  SKILL.md                           Agent instructions and workflows
  scripts/openalex_cli.py            Standalone CLI
  references/api.md                  Raw API patterns, budget notes and known traps
  examples/                          Ready-to-run shell scripts
```

## Author

Created and maintained by [Egor Kotov](https://github.com/e-kotov).

## License

MIT. See [LICENSE](LICENSE). Data comes from OpenAlex, which is released under CC0.

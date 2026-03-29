# Claude Code Skills & Connectors Guide

This document explains how the Hugging Face and Cloudflare skills were integrated into Claude Code for the Araripe project, how they work, and how to use them.

---

## What Are Skills?

Skills are markdown files that give Claude Code specialized knowledge about specific tools or platforms. When Claude encounters a task related to a skill (e.g., deploying to Cloudflare R2 or using the `hf` CLI), it automatically loads the relevant skill file and follows its instructions.

Think of skills as **cheat sheets** that Claude reads before working on a task, ensuring it uses the latest syntax, best practices, and correct commands.

## What Are MCP Connectors?

MCP (Model Context Protocol) connectors are **live integrations** that give Claude direct tool access — the ability to call APIs, query databases, or interact with external services in real time. Unlike skills (which are static reference docs), MCP connectors provide interactive tools.

For example, the Hugging Face MCP connector lets Claude:
- Check who is logged in (`hf_whoami`)
- Search models, datasets, and Spaces
- Query the Hub for repo details

---

## What Was Installed

### 1. Hugging Face MCP Connector (already active)

**What:** A live connection to the Hugging Face Hub API, authenticated as `santibravo`.

**How it was set up:** You added this yourself via the Claude Code connector interface. It works through MCP and provides tools like `hf_whoami`, `hub_repo_search`, `hf_doc_search`, etc.

**Scope:** Available in every Claude Code session where the connector is enabled. It persists across sessions because it's configured at the account/app level, not per-conversation.

**Tools it provides:**
| Tool | What it does |
|------|-------------|
| `hf_whoami` | Check authenticated HF user |
| `hub_repo_search` | Search models, datasets, Spaces |
| `hub_repo_details` | Get details about specific repos |
| `hf_doc_search` | Search HF documentation |
| `hf_doc_fetch` | Fetch a specific doc page |
| `space_search` | Semantic search for Spaces |
| `dynamic_space` | Run tasks on HF Spaces |
| `paper_search` | Search ML research papers |

### 2. Hugging Face CLI Skill

**What:** A reference file that teaches Claude Code the correct `hf` CLI commands.

**Location:** `~/.claude/skills/hf-cli/SKILL.md`

**How it was installed:**
```bash
# The hf CLI binary itself:
curl -LsSf https://hf.co/cli/install.sh | bash -s

# The skill file (cloned from GitHub and copied):
git clone https://github.com/huggingface/skills.git /tmp/hf-skills
cp -r /tmp/hf-skills/skills/hf-cli ~/.claude/skills/
```

**Alternative installation methods:**
```bash
# Via hf CLI itself (generates skill from your installed version):
hf skills add --claude --global

# Via Claude Code plugin system (interactive, run outside a session):
claude
/plugin marketplace add huggingface/skills
/plugin install hf-cli@huggingface/skills
```

**Scope:** Installed in `~/.claude/skills/` (global), so it's available in **all future sessions** and **all projects**. If installed in `.claude/skills/` (project-level), it would only apply to that project.

**Key commands it teaches:**
- `hf auth login` — Authenticate with a token
- `hf upload REPO_ID` — Upload files to Hub
- `hf download REPO_ID` — Download files
- `hf sync` — Sync local directory with a bucket

### 3. Cloudflare Skills (9 skills)

**What:** Reference files covering Cloudflare Workers, R2, D1, Wrangler CLI, Agents SDK, Durable Objects, and more.

**Location:** `~/.claude/skills/` (multiple directories)

**How they were installed:**
```bash
git clone https://github.com/cloudflare/skills.git /tmp/cloudflare-skills
cp -r /tmp/cloudflare-skills/skills/* ~/.claude/skills/
```

**Alternative installation methods:**
```bash
# Via Claude Code plugin system (interactive, run outside a session):
claude
/plugin marketplace add cloudflare/skills
/plugin install cloudflare@cloudflare
```

**Scope:** Global (`~/.claude/skills/`), available in all sessions.

**Installed skills:**
| Skill | Useful for |
|-------|-----------|
| `cloudflare` | General platform knowledge (Workers, R2, KV, D1) |
| `wrangler` | Wrangler CLI commands for deploying and managing services |
| `agents-sdk` | Building AI agents on Cloudflare |
| `durable-objects` | Stateful coordination patterns |
| `sandbox-sdk` | Secure code execution |
| `building-ai-agent-on-cloudflare` | Agent architecture patterns |
| `building-mcp-server-on-cloudflare` | MCP server deployment |
| `web-perf` | Core Web Vitals auditing |
| `workers-best-practices` | Performance and reliability patterns |

---

## How Skills Are Loaded

### Automatic loading (contextual)

Claude Code detects when a conversation topic matches a skill's description and loads it automatically. For example:
- If you ask about `wrangler deploy`, the `wrangler` skill loads
- If you ask about uploading to R2, the `cloudflare` skill loads
- If you mention `hf upload`, the `hf-cli` skill loads

You do NOT need to explicitly "summon" them — they activate based on context.

### Manual loading

If Claude doesn't auto-detect the skill you need, you can:
- Mention the tool by name (e.g., "use wrangler to..." or "use the hf CLI to...")
- Reference the skill directly in your prompt

### MCP connectors vs Skills

| Aspect | MCP Connectors | Skills |
|--------|---------------|--------|
| **Type** | Live API integration | Static reference docs |
| **Provides** | Interactive tools (API calls) | Knowledge (correct syntax, best practices) |
| **Persistence** | Account/app level | File-based (`~/.claude/skills/`) |
| **Auth** | Managed by the connector | N/A (skills don't authenticate) |
| **Example** | HF connector: queries Hub API directly | HF CLI skill: teaches correct `hf` commands |

---

## Keeping Skills Up to Date

Skills are static files. To update them:

```bash
# HF CLI skill — regenerate from your installed CLI version:
hf skills add --claude --global --force

# Cloudflare skills — pull latest from GitHub:
cd /tmp && git clone https://github.com/cloudflare/skills.git
cp -r /tmp/cloudflare-skills/skills/* ~/.claude/skills/

# Or use the plugin system:
# /plugin update cloudflare@cloudflare
```

## Uninstalling Skills

```bash
# Remove a specific skill:
rm -rf ~/.claude/skills/wrangler

# Remove all Cloudflare skills:
rm -rf ~/.claude/skills/{cloudflare,wrangler,agents-sdk,durable-objects,sandbox-sdk,building-*,web-perf,workers-best-practices}

# Remove HF CLI skill:
rm -rf ~/.claude/skills/hf-cli
```

---

## Summary

- **MCP connector** (Hugging Face) = live API access, configured at account level, persists across all sessions
- **Skills** (HF CLI + Cloudflare) = reference knowledge installed as files in `~/.claude/skills/`, persists across all sessions, auto-loaded by context
- Neither needs to be "summoned" — they activate automatically when relevant
- To update: re-run the install command or pull from GitHub

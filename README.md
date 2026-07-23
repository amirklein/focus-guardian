# Anchor

Portable productivity companion: **Familiar** watches your screen and clipboard (including Wispr dictation); **Focus Guardian** detects sustained drift, nudges you via **Slack**, and coaches you in **Cursor / Claude** via MCP — **no LLM API key required**.

Repo: [github.com/amirklein/anchor-me](https://github.com/amirklein/anchor-me)

## How it works

```
┌─────────────┐     stills + Wispr          ┌──────────────────┐
│  Familiar   │ ──────────────────────────► │ Focus Guardian   │
│  (sensor)   │                             │  guardian daemon │
└─────────────┘                             └────────┬─────────┘
                                                     │
                              live_context.json/md   │
                                     ┌───────────────┴───────────────┐
                                     ▼                               ▼
                          Slack (short drift ping)        Cursor / Claude MCP
                          proactive + snooze                synthesis + set focus
```

| Layer | Role |
|-------|------|
| **Familiar** | Continuous screen + clipboard capture on each computer |
| **Guardian** | Always monitoring → refreshes live context → Slack ping on sustained drift |
| **Slack** | Proactive short alerts; snooze; quick focus/status commands |
| **Cursor / Claude MCP** | Full coaching, catch me up, configure focus (host app provides the model) |

**Two interfaces, one brain:**

1. **Slack** — notifies you when you drift (*"You've been on LinkedIn for a while — open Cursor and ask catch me up"*).
2. **Cursor / Claude** — reads the same live context dossier and gives personalized coaching when you ask.

Deep docs: [docs/SLACK.md](docs/SLACK.md) · [docs/MCP.md](docs/MCP.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Philosophy

- **Proactive by default** — `fgr guardian start` watches Familiar; drift alerts arrive in Slack.
- **Slack-first** — no macOS notification fallback; configure a Slack app once per workspace.
- **Wispr/clipboard is first-class** — what you dictate is the primary intent signal; screen corroborates.
- **Sustained drift only** — chime after sustained off-goal activity (~10 min sustained + ~25 min cooldown by default).
- **No API key for core flow** — rule-based drift detection; host MCP subscription handles synthesis.

> **zsh users:** `fg` is a shell builtin (job control). Always use **`fgr`** as the CLI command.

## Quick start

### 1. Prerequisites

- Python 3.10+ (macOS: `brew install python@3.12`)
- [Familiar](https://familiar.ai) installed with recording enabled
- `~/.familiar/settings.json` present (created by Familiar setup)
- Slack app with Socket Mode — see [Slack setup](#slack-setup) below

### 2. Install

```bash
git clone https://github.com/amirklein/anchor-me.git ~/focus-guardian
cd ~/focus-guardian
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
fgr init
```

For MCP (Cursor / Claude / Codex):

```bash
pip install -e ".[mcp]"
```

Verify MCP server starts:

```bash
fgr mcp   # blocks on stdio — Ctrl+C to exit; that means it works
```

### 3. Slack setup

Export tokens (preferred over storing in config):

```bash
export SLACK_BOT_TOKEN="xoxb-..."   # Bot User OAuth Token
export SLACK_APP_TOKEN="xapp-..."   # App-level token (Socket Mode)
export SLACK_USER_ID="U01234567"    # Your Slack member ID
```

Verify:

```bash
fgr slack check
```

**Slack app checklist** ([full guide](docs/SLACK.md)):

| Step | Where in api.slack.com |
|------|------------------------|
| Enable **Messages Tab** | App Home |
| Scopes: `chat:write`, `im:write`, `im:history` | OAuth & Permissions |
| Enable **Socket Mode** + app token (`connections:write`) | Socket Mode |
| Subscribe to **`message.im`** | Event Subscriptions |
| Reinstall app to workspace | after any scope/event change |

Only messages from `SLACK_USER_ID` are handled. Find your ID: profile → **Copy member ID**.

### 4. Set focus

```bash
fgr profile job_search
fgr focus "This week: pricing, competitors, and GTM" --cadence week
fgr status
```

Or in Slack DM: *This week I'm focusing on pricing and GTM*  
Or in Cursor (after MCP setup): *This week I'm focusing on pricing and GTM*

Config: **`~/.focus-guardian/config.json`**. Copy or dotfiles-sync across machines.

### 5. Run both daemons

```bash
fgr guardian start    # proactive drift + scheduled reviews → Slack
fgr slack start       # interactive DM bot (focus, review, snooze)
```

Debug interactively:

```bash
fgr slack start -f    # foreground; watch ~/.focus-guardian/state/check.log
fgr guardian once     # one-shot evaluate + notify if drifting
```

Stop:

```bash
fgr guardian stop
fgr slack stop
```

Optional auto-start on login (macOS): `./scripts/install-launchd.sh`

## Daily workflow

1. Set week/day focus (`fgr focus` or Slack/Cursor).
2. Run `fgr guardian start` + `fgr slack start` (or LaunchAgents).
3. Work normally — Familiar captures screen + Wispr.
4. When you drift → short Slack ping.
5. Open Cursor or Claude → **"catch me up"** or **"why did Slack ping me?"**
6. End of day → `fgr review --human` for a retrospective.

Snooze proactive alerts: Slack *snooze until 3pm* or MCP `snooze_alerts`.  
Opt out entirely: `"interventionMode": "manual"` in config.

## Cursor / Claude / Codex (MCP)

Guardian writes shared context on every evaluation:

- `~/.focus-guardian/state/live_context.json` — structured (MCP)
- `~/.focus-guardian/state/live_context.md` — human-readable snapshot

### Cursor (this repo)

Project MCP is pre-wired in `.cursor/mcp.json`. After clone:

1. `pip install -e ".[mcp]"`
2. **Cmd+Shift+P → Developer: Reload Window**
3. Ask in chat: **"catch me up"**

The project rule `.cursor/rules/focus-guardian.mdc` guides the agent to use MCP coach tools.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "focus-guardian": {
      "command": "/Users/you/focus-guardian/.venv/bin/python",
      "args": ["-m", "focus_guardian.mcp_server"]
    }
  }
}
```

Use `which python` inside your activated venv for the path. Quit and reopen Claude Desktop.

### Codex CLI

```toml
[mcp_servers.focus-guardian]
command = "/Users/you/focus-guardian/.venv/bin/python"
args = ["-m", "focus_guardian.mcp_server"]
```

### MCP tools

| Tool | Use when you ask… |
|------|-------------------|
| `catch_me_up` | *Catch me up* — main coaching entry point |
| `get_live_context` | Full dossier: Familiar activity, focus, drift state |
| `explain_last_alert` | *Why did Slack ping me?* |
| `set_focus` | *This week I'm focusing on X* |
| `get_focus` / `get_status` | Current focus and quick snapshot |
| `get_drift_status` / `get_review` | Live drift or session review snapshot |
| `snooze_alerts` / `resume_alerts` | Pause or resume proactive Slack pings |
| `clear_focus` / `set_week_schedule` | Clear a cadence or set week boundary preset |

See [docs/MCP.md](docs/MCP.md) for the full two-layer workflow.

## Slack commands

Open a DM with **Focus Guardian** (the app, not a channel):

| You say | Bot does |
|---------|----------|
| *This week I'm exploring pricing and GTM* | Sets week focus |
| *What's my focus?* | Shows day/week/month stack |
| *How did today go?* | Session review snapshot + redirect to Cursor for depth |
| *Am I drifting?* | Live drift check |
| *Snooze until 3pm* | Pauses proactive alerts |
| *Resume alerts* | Turns alerts back on |
| *help* | Full command list |

Proactive drift chimes and daily/weekly reviews come from `fgr guardian start` unless snoozed.

With `coach.redirectSlackToHost: true` (default), review/drift replies in Slack are short snapshots that point you to Cursor/Claude for full synthesis.

## Configure what counts as drift

Edit `~/.focus-guardian/config.json` (see `config.example.json`):

| Setting | What it controls |
|---------|------------------|
| `distractionTitlePatterns` | Window title substrings (e.g. `linkedin`, `youtube`, `feed \|`) |
| `distractionApps` | App names treated as distraction surfaces |
| `thresholds.distractionMinutes` | Minutes on distraction before drift ping (default **20**) |
| `proactive.driftSustainedMinutes` | Minimum sustained off-goal window (default **10**) |
| `proactive.chimeCooldownMinutes` | Minutes between Slack pings (default **25**) |
| `driftRules.offTopicPhrases` | Wispr phrases that signal off-topic (e.g. `vacation planning`) |
| `driftRules.*` | Toggle individual rules (`wisprOffTopic`, `distractionStreak`, `aiLoop`, etc.) |
| `buildSurfaces` / `researchSurfaces` | Apps classified as building vs researching |
| `familiarStillsPath` | Override Familiar stills root if non-default |

Inspect rules: `fgr drift`

### Drift signal codes (internal)

| Code | Meaning |
|------|---------|
| `wispr_off_topic` | Dictation off goal for sustained window |
| `topic_pivot` | Latest Wispr pivoted away from assignment keywords |
| `distraction_streak` | LinkedIn, WhatsApp, personal tabs |
| `ai_research_loop` | Long Claude/Gemini without building |
| `polish_without_build` | Slides/Lovable without implementation |
| `wispr_distraction_spike` | Off-topic dictation on distraction surface |

Slack pings and MCP coaching use plain language — these codes are for tuning config only.

## Test end-to-end (simulate drift)

Inject synthetic Familiar captures without actually browsing distractions:

```bash
fgr focus "This week: pricing, competitors, and GTM" --cadence week
fgr simulate drift --minutes 25 --notify --wispr "vacation planning and bread making recipes"
```

This writes isolated test captures, evaluates drift, optionally sends a Slack ping, and refreshes `live_context.md`.

Then in Cursor: **"catch me up"** or **"why did Slack ping me?"**

Options: `--app`, `--title`, `--interval`, `--wispr`, `-n`/`--notify`

## CLI reference

```bash
fgr init                         # create ~/.focus-guardian config
fgr profile job_search           # switch life-stage profile
fgr focus "..." --cadence week   # set day | week | month focus
fgr status                       # focus stack + snooze state

fgr guardian start|stop|once|status   # proactive drift daemon
fgr slack start|stop|check            # interactive DM bot
fgr simulate drift [--notify]         # test drift detection

fgr review --human               # retrospective work blocks + Wispr
fgr coach                        # coaching from last review/drift
fgr drift                        # show drift rules
fgr paths                        # Familiar + config paths
fgr mcp                          # run MCP server (stdio)
```

Legacy interval watch (if not proactive): `fgr watch start -i 45`

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `fg: job not found` | Use **`fgr`**, not `fg` (zsh builtin) |
| `fgr slack check` fails | Set `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_USER_ID` |
| Slack ping works, bot never replies | Add **`message.im`** event; enable Messages Tab; reinstall app; `fgr slack start -f` |
| No inbound events in log | DM the **Focus Guardian app**; confirm `SLACK_USER_ID` matches sender |
| MCP tools missing in Cursor | `pip install -e ".[mcp]"`; Reload Window; check `.cursor/mcp.json` path |
| Drift never fires | Lower `thresholds.distractionMinutes` or run `fgr simulate drift --minutes 25` |
| Wrong Familiar path | Set `familiarStillsPath` or run `fgr paths` |

Logs: `~/.focus-guardian/state/check.log`  
LaunchAgent logs: `~/.focus-guardian/state/launchd.log`, `slack-launchd.log`

## Config sync across machines

| What | Where | Sync? |
|------|--------|-------|
| Code | `~/focus-guardian` (git) | Yes |
| Goals & rules | `~/.focus-guardian/config.json` | Copy or dotfiles |
| Familiar data | Per-machine `contextFolderPath` | Local only |
| Live context / reports | `~/.focus-guardian/state/` | Ephemeral |

## Optional API keys

Not required for guardian, Slack bot, or MCP coaching:

```bash
export GEMINI_API_KEY="..."       # optional richer Slack/review text
export ANTHROPIC_API_KEY="..."    # optional Slack intent parsing
```

Enable in config only if wanted: `synthesis.useApiForReview`, `driftRules.useApiForDrift`.

## License

MIT

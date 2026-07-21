# Anchor

Portable productivity companion: **Familiar** watches what you do on screen and clipboard (including Wispr dictation); **Focus Guardian** detects sustained drift, nudges you via **Slack**, and coaches you in **Cursor / Claude** via MCP.

## Architecture

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
| **Familiar** | Continuous screen + clipboard on each computer |
| **Guardian** | Always monitoring → updates live context → Slack ping on drift |
| **Slack** | Proactive short alerts; snooze; quick focus edits |
| **Cursor / Claude MCP** | Full coaching, catch me up, configure focus (no API key) |

**Two interfaces:** Slack notifies you when you drift. Cursor or Claude synthesizes what Familiar saw and helps you re-focus. See [docs/MCP.md](docs/MCP.md).

See [docs/SLACK.md](docs/SLACK.md) for Slack app setup (Socket Mode, scopes, tokens).

## Philosophy

- **Proactive by default** — `fgr guardian start` watches Familiar; drift alerts arrive in Slack.
- **Slack-first** — no macOS notification fallback; configure a Slack app once per workspace.
- **Wispr/clipboard is first-class** — what you dictate is the primary intent signal; screen corroborates.
- **Sustained drift only** — chime after ~10 min off-goal + 25 min cooldown.
- **`fgr review`** stays for end-of-session retrospectives (hours stitched into work blocks).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for Familiar fork plans (Zoom audio, etc.).

## Quick start (any computer)

### 1. Prerequisites

- Python 3.10+
- [Familiar](https://familiar.ai) installed, recording enabled
- `~/.familiar/settings.json` present (created by Familiar setup)
- Slack app with Socket Mode — see [docs/SLACK.md](docs/SLACK.md)

### 2. Install Focus Guardian

```bash
git clone <your-repo-url> ~/focus-guardian
cd ~/focus-guardian
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
fgr init
```

### 3. Configure Slack

```bash
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_APP_TOKEN="xapp-..."
export SLACK_USER_ID="U01234567"
```

Full setup: [docs/SLACK.md](docs/SLACK.md).

### 4. Set your focus

```bash
fgr profile job_search
fgr focus "This week: ship HiBob MVP slide + working demo" --cadence week
```

Or DM the bot: *This week I'm focusing on the HiBob demo*.

Config lives at **`~/.focus-guardian/config.json`**. Sync via iCloud or dotfiles if you want the same goals everywhere.

### 5. Run (proactive + interactive)

```bash
fgr guardian start          # proactive drift + scheduled reviews → Slack
fgr slack start             # interactive DM bot (focus, review, snooze)
fgr guardian status         # one-shot drift evaluation
fgr guardian once           # evaluate + notify if drift sustained
fgr review --human          # retrospective: work blocks + Wispr excerpts
fgr coach                   # coaching from last review or drift report
fgr status
fgr guardian stop
fgr slack stop
```

Opt out of proactive nudges: set `"interventionMode": "manual"` in config, or snooze via Slack: *pause alerts for 2 hours*.

Legacy interval watch (only if not proactive): `fgr watch start -i 45`

## New machine checklist

1. Install Familiar + enable recording  
2. `git clone` this repo (or copy the folder)  
3. `pip install -e .` in a venv  
4. Configure Slack ([docs/SLACK.md](docs/SLACK.md))  
5. `fgr init` && `fgr profile job_search`  
6. `fgr guardian start` && `fgr slack start`

Optional: auto-start on login (macOS):

```bash
./scripts/install-launchd.sh
```

## Use with Claude Desktop / Cursor / Codex (no API key)

```bash
pip install -e ".[mcp]"
```

Wire MCP in your host app, then ask **"catch me up"** for full coaching. Guardian keeps `live_context.md` fresh for both Slack and MCP.

See **[docs/MCP.md](docs/MCP.md)** — Slack notifier + Cursor/Claude synthesis workflow.

**No LLM API key required.** Guardian detects drift with rules; Slack sends short pings; Cursor/Claude interprets the live context dossier.

## Other interfaces

**Proactive Slack alerts** — `fgr guardian start`

**Slack bot** — `fgr slack start` (snooze, quick focus; deep coaching → Cursor/Claude)

**CLI retrospective** — `fgr review --human`

## Drift signals (live guardian)

| Code | Meaning |
|------|---------|
| `wispr_off_topic` | Dictation off goal for sustained window |
| `topic_pivot` | Latest Wispr pivoted away from assignment keywords |
| `distraction_streak` | LinkedIn, WhatsApp, personal tabs |
| `ai_research_loop` | Long Claude/Gemini without building |
| `polish_without_build` | Slides/Lovable without implementation |
| `wispr_distraction_spike` | Off-topic dictation on distraction surface |

Tune in `config.json` → `proactive` and `thresholds`. See `config.example.json`.

## Config sync across machines

| What | Where | Sync? |
|------|--------|-------|
| Code | `~/focus-guardian` (git) | Yes |
| Goals & rules | `~/.focus-guardian/config.json` | Copy or dotfiles |
| Familiar data | Per-machine `contextFolderPath` | Local only |
| Reports | `~/.focus-guardian/state/` | Ephemeral |

Set `familiarStillsPath` if Familiar uses a custom data path.

## License

MIT

# Anchor

Portable productivity companion: **Familiar** watches what you do on screen and clipboard (including Wispr dictation); **Focus Guardian** detects sustained drift and nudges you via **Slack**.

Works on any machine where Familiar is installed. Not tied to Cursor, Claude Code, or a specific IDE — use the CLI from Terminal, talk to the Slack bot in DM, or paste `fg coach --print-prompt` into any AI tool.

## Architecture

```
┌─────────────┐     stills + .clipboard.txt   ┌──────────────────┐
│  Familiar   │ ────────────────────────────► │ Focus Guardian   │
│  (sensor)   │   OCR, titles, Wispr text     │  guardian daemon │
└─────────────┘                               └────────┬─────────┘
                                                       │
                    ┌──────────────────────────────────┼──────────────────┐
                    ▼                                  ▼                  ▼
             Slack DM (drift + review)          drift engine         fg review
             + interactive bot                  (30m window)         (retrospective)
```

| Layer | Role |
|-------|------|
| **Familiar** | Continuous screen + clipboard on each computer |
| **Guardian** | Event-driven: new Familiar files → debounce → drift check → Slack DM |
| **Slack bot** | Interactive DM — set focus, review, snooze (`fg slack start`) |
| **Review** | Deep retrospective over hours (`fg review`) |

**Primary interface:** Slack DM with the Focus Guardian app. Proactive alerts and on-demand commands both go through Slack.

See [docs/SLACK.md](docs/SLACK.md) for app setup (Socket Mode, scopes, tokens).

## Philosophy

- **Proactive by default** — `fg guardian start` watches Familiar; drift alerts arrive in Slack.
- **Slack-first** — no macOS notification fallback; configure a Slack app once per workspace.
- **Wispr/clipboard is first-class** — what you dictate is the primary intent signal; screen corroborates.
- **Sustained drift only** — chime after ~10 min off-goal + 25 min cooldown.
- **`fg review`** stays for end-of-session retrospectives (hours stitched into work blocks).

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
fg init
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
fg profile job_search
fg focus "This week: ship HiBob MVP slide + working demo" --cadence week
```

Or DM the bot: *This week I'm focusing on the HiBob demo*.

Config lives at **`~/.focus-guardian/config.json`**. Sync via iCloud or dotfiles if you want the same goals everywhere.

### 5. Run (proactive + interactive)

```bash
fg guardian start          # proactive drift + scheduled reviews → Slack
fg slack start             # interactive DM bot (focus, review, snooze)
fg guardian status         # one-shot drift evaluation
fg guardian once           # evaluate + notify if drift sustained
fg review --human          # retrospective: work blocks + Wispr excerpts
fg coach                   # coaching from last review or drift report
fg status
fg guardian stop
fg slack stop
```

Opt out of proactive nudges: set `"interventionMode": "manual"` in config, or snooze via Slack: *pause alerts for 2 hours*.

Legacy interval watch (only if not proactive): `fg watch start -i 45`

## New machine checklist

1. Install Familiar + enable recording  
2. `git clone` this repo (or copy the folder)  
3. `pip install -e .` in a venv  
4. Configure Slack ([docs/SLACK.md](docs/SLACK.md))  
5. `fg init` && `fg profile job_search`  
6. `fg guardian start` && `fg slack start`

Optional: auto-start on login (macOS):

```bash
./scripts/install-launchd.sh
```

## Use with Claude Code / Codex / Cursor

**Option A — Proactive Slack alerts**  
`fg guardian start` — drift DMs when sustained off-goal.

**Option B — Slack bot**  
`fg slack start` — set focus, ask *how did today go?*, *am I drifting?*

**Option C — Retrospective**  
`fg review --human` then `fg coach`

**Option D — API coaching**  
```bash
export ANTHROPIC_API_KEY=...
fg review && fg coach --api
```

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

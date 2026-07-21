# Slack setup — Focus Guardian

Focus Guardian uses Slack in two ways:

| Daemon | Command | Role |
|--------|---------|------|
| **Guardian** | `fgr guardian start` | Proactive drift alerts + scheduled reviews (outbound DMs) |
| **Slack bot** | `fgr slack start` | Interactive DM listener — set focus, check drift, snooze alerts |

Both daemons can run at the same time. The bot is your primary interface; the guardian watches Familiar and pushes alerts when you drift.

## 0. Local install (do this first)

**zsh users:** `fg` is a shell builtin (job control). Use **`fgr`** as the CLI command, or bypass with `command fg` / `.venv/bin/fg`.

macOS ships Python 3.9 and no `python` command — use a venv with **Python 3.10+**:

```bash
cd ~/Projects/focus-guardian
brew install python@3.12   # once, if needed
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

Always use the venv (not bare `python3` from Homebrew outside the venv):

```bash
source ~/Projects/focus-guardian/.venv/bin/activate
fgr --version
```

**Outbound ping test** (needs `SLACK_BOT_TOKEN` + `SLACK_USER_ID` in `~/.zshrc`):

```bash
source ~/.zshrc
.venv/bin/python3 -c "
from focus_guardian.paths import load_config
from focus_guardian.slack_client import post_message
post_message('Focus Guardian test ping', load_config())
print('Sent')
"
```

**Verify full Slack setup:**

```bash
fgr slack check
```

**Start everything:**

```bash
./scripts/start-all.sh
# or manually:
fgr slack start -f    # debug interactive bot first
fgr guardian start
```

## 1. Create a Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. Name it (e.g. *Focus Guardian*) and pick your workspace.

### Enable App Home → Messages tab

1. **App Home** (left sidebar) → enable **Messages Tab**.
2. Under **Show Tabs**, turn on **Messages Tab** so users can DM the bot.

This lets you open a DM with the app and send natural-language commands.

### Bot Token Scopes

**OAuth & Permissions** → **Bot Token Scopes** — add:

| Scope | Why |
|-------|-----|
| `chat:write` | Send DMs and replies |
| `im:write` | Open DM channels |
| `im:history` | Read inbound DMs (optional but useful) |

Install the app to your workspace and copy the **Bot User OAuth Token** (`xoxb-...`).

### Enable Socket Mode

1. **Socket Mode** → toggle **Enable Socket Mode** on.
2. Create an **App-Level Token** with scope `connections:write`.
3. Copy the token (`xapp-...`).

Socket Mode lets the bot receive events without a public HTTP endpoint.

### Event Subscriptions

1. **Event Subscriptions** → **Enable Events** on.
2. Under **Subscribe to bot events**, add:
   - `message.im` — inbound DMs to the bot

Save changes and reinstall the app if prompted.

## 2. Environment variables

Prefer env vars over storing tokens in config:

```bash
export SLACK_BOT_TOKEN="xoxb-..."   # Bot User OAuth Token
export SLACK_APP_TOKEN="xapp-..."   # App-level token (Socket Mode)
export SLACK_USER_ID="U01234567"    # Your Slack member ID (restrict bot to you)
```

Optional — set in `~/.focus-guardian/config.json` instead:

```json
"notifications": {
  "channel": "slack",
  "slack": {
    "botToken": "xoxb-...",
    "appToken": "xapp-...",
    "userId": "U01234567"
  }
}
```

### Finding your Slack user ID

- Click your profile → **Copy member ID**, or
- DM the bot once after install; check the bot logs at `~/.focus-guardian/state/check.log`.

Only messages from `SLACK_USER_ID` are handled; everyone else is ignored.

## 3. Run both daemons

```bash
pip install -e .

# Proactive drift + scheduled reviews (outbound)
fgr guardian start

# Interactive DM bot (inbound)
fgr slack start

# Foreground (debugging)
fgr slack start -f
```

Stop with `fgr guardian stop` and `fgr slack stop`.

PID files: `~/.focus-guardian/state/guardian.pid` and `slack.pid`.

## 4. Talk to the bot

Open a DM with **Focus Guardian** in Slack. Examples:

| You say | Bot does |
|---------|----------|
| *This week I'm exploring pricing and GTM* | Sets week focus |
| *What's my focus?* | Shows day/week/month stack |
| *How did today go?* | Session review |
| *Am I drifting?* | Live drift check |
| *Snooze until 3pm* | Pauses proactive alerts |
| *Resume alerts* | Turns alerts back on |
| *help* | Full command list |

Proactive drift chimes and daily/weekly reviews still come from `fgr guardian start` unless snoozed.

## 5. Optional LLM intent parsing

If `ANTHROPIC_API_KEY` is set, inbound messages are classified via Claude before heuristics. Without it, keyword heuristics handle everything (no API call).

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export FOCUS_GUARDIAN_MODEL="claude-sonnet-4-20250514"  # optional override
```

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `fg: job not found: slack` | zsh builtin `fg` shadowed the CLI — use `fgr slack check` instead |
| `SLACK_BOT_TOKEN not set` | Export token or set `notifications.slack.botToken` |
| `SLACK_APP_TOKEN not set` | Enable Socket Mode; export app token |
| Bot never replies | Check `message.im` subscription; restart `fgr slack start -f` |
| Wrong user gets replies | Set `SLACK_USER_ID` to your member ID |
| Alerts still firing while snoozed | Snooze only affects guardian notifications; use *resume alerts* to clear |
| Logs | `~/.focus-guardian/state/check.log` |

## 7. Auto-start (macOS)

Install both LaunchAgents (guardian + slack):

```bash
./scripts/install-launchd.sh
```

LaunchAgents need `SLACK_*` variables at login — add exports to `~/.zshrc` or set via `launchctl setenv SLACK_BOT_TOKEN xoxb-...` etc.

Logs: `~/.focus-guardian/state/launchd.log` and `slack-launchd.log`.

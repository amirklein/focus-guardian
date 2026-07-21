# Focus Guardian MCP server

Use Focus Guardian from **Claude Desktop**, **Cursor**, or **Codex CLI** without any LLM API key. The host app provides the model (via your subscription); this server only exposes local tools over stdio.

## Install

```bash
cd ~/focus-guardian
source .venv/bin/activate
pip install -e ".[mcp]"
```

Verify:

```bash
fgr mcp   # blocks on stdio — Ctrl+C to exit; that means it works
```

Use your venv Python path in the configs below. Example:

```bash
which python
# /Users/you/focus-guardian/.venv/bin/python
```

## Tools exposed

| Tool | What it does |
|------|----------------|
| `get_focus` | Current day/week/month focus stack |
| `set_focus` | Set focus (optional cadence: day, week, month) |
| `clear_focus` | Remove focus for a cadence |
| `set_week_schedule` | Week boundary: mon-fri, sun-thu, sun-sat, mon-sun |
| `get_status` | Focus + snooze + last drift signal |
| `get_review` | Session review from Familiar timeline |
| `get_drift_status` | Live drift check vs your focus |
| `snooze_alerts` / `resume_alerts` | Pause/resume proactive Slack alerts |

Example prompts in any host:

- *What's my focus this week?*
- *This week I'm focusing on pricing and GTM*
- *Am I drifting right now?*
- *How did today go?*

## Claude Desktop

1. Open **Settings → Developer → Edit Config** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS).
2. Add under `mcpServers`:

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

3. Quit and reopen Claude Desktop.

Billing goes through your Claude Pro/Max subscription — no `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`.

## Cursor

Cursor supports the same stdio MCP pattern.

1. Open **Cursor Settings → MCP** (or add a project `.cursor/mcp.json`).
2. Add:

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

3. Reload the window. Focus Guardian tools appear in Agent/Composer tool lists.

You are already using Cursor's model subscription — no separate API key for Focus Guardian.

## Codex CLI

Codex reads local MCP servers from `~/.codex/config.toml`:

```toml
[mcp_servers.focus-guardian]
command = "/Users/you/focus-guardian/.venv/bin/python"
args = ["-m", "focus_guardian.mcp_server"]
```

Restart Codex after editing. Unattended runs may still need `OPENAI_API_KEY` for Codex itself; the Focus Guardian server does not.

## What MCP does *not* replace

| Capability | MCP (on-demand) | Guardian + Slack (background) |
|------------|-----------------|----------------------------------|
| Drift alerts while you work | No — you must ask | Yes — `fgr guardian start` |
| Scheduled daily review | No | Yes — via guardian scheduler |
| Mobile push | No | Slack app notifications |
| API key for LLM | No — host app pays | No — rule-based by default |

Keep `fgr guardian start` and `fgr slack start` running for proactive nudges. MCP is the rich, conversational layer when you open Claude, Cursor, or Codex.

## API keys are optional everywhere

Without `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`:

- Slack bot uses heuristic intent parsing (`detect_intent`)
- Drift/review use rule-based synthesis (`synthesize_review_offline`)
- MCP tools call the same handlers — no LLM in the server

Set API keys only if you want optional enrichment inside the Slack bot or guardian (config: `useApiForReview`, `useApiForDrift`).

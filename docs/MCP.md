# Focus Guardian MCP server

Two-layer model: **Slack** pushes short proactive drift pings; **Cursor / Claude** owns synthesis, coaching, and focus configuration via MCP.

```
Familiar → guardian → live_context.json ──┬── Slack (short ping)
                                          └── Cursor/Claude MCP (full coaching)
```

No LLM API key required. The host app subscription provides the model; Focus Guardian exposes local context and tools.

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

Use your venv Python path in the configs below:

```bash
which python
# /Users/you/focus-guardian/.venv/bin/python
```

## Typical workflow

1. `fgr guardian start` — always monitoring; refreshes `~/.focus-guardian/state/live_context.md`
2. Drift detected → short human Slack ping (*"Open Cursor and ask catch me up"*)
3. Open Cursor or Claude → ask **"catch me up"** or **"why did Slack ping me?"**
4. Host model calls MCP → reads Familiar story + focus → gives personalized coaching
5. **"This week I'm focusing on X"** → `set_focus` updates config for guardian + Slack

## Coaching tools (start here)

| Tool | What it does |
|------|----------------|
| `catch_me_up` | Main entry — live context + 6h work blocks for synthesis |
| `get_live_context` | Full dossier: Familiar activity, focus, drift state |
| `explain_last_alert` | Why Slack pinged + context since the alert |
| `set_focus` | Set day/week/month focus (primary config path) |
| `get_focus` / `get_status` | Current focus and quick snapshot |
| `snooze_alerts` / `resume_alerts` | Pause/resume proactive Slack pings |

Configuration tools: `clear_focus`, `set_week_schedule`, `get_review`, `get_drift_status`.

Example prompts:

- *Catch me up*
- *Why did Slack ping me?*
- *This week I'm focusing on pricing and GTM*
- *Am I drifting right now?*

## Claude Desktop

1. **Settings → Developer → Edit Config** (`~/Library/Application Support/Claude/claude_desktop_config.json`).
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

3. Quit and reopen Claude Desktop.

## Cursor

1. **Cursor Settings → MCP** (or project `.cursor/mcp.json`).
2. Same JSON as above.
3. Reload the window. The project rule `.cursor/rules/focus-guardian.mdc` guides the agent to use these tools.

## Codex CLI

```toml
[mcp_servers.focus-guardian]
command = "/Users/you/focus-guardian/.venv/bin/python"
args = ["-m", "focus_guardian.mcp_server"]
```

## Shared live context

Guardian writes on every evaluation:

- `~/.focus-guardian/state/live_context.json` — structured (for MCP)
- `~/.focus-guardian/state/live_context.md` — readable snapshot

Both Slack pings and MCP tools read the same context.

## Division of labor

| Role | Slack | Cursor / Claude |
|------|-------|-----------------|
| Proactive drift alert | Yes — short ping | On-demand only |
| Deep synthesis / coaching | Snapshot + redirect | Yes — host model |
| Configure focus | Basic commands | Primary — natural conversation |
| Always monitoring | `fgr guardian start` | Reads context when you ask |

## API keys are optional

Without `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`:

- Guardian detects drift with rules
- Slack sends conversational pings (no technical labels)
- MCP returns rich context for the host model to interpret

Set API keys only for optional enrichment (`useApiForReview`, `useApiForDrift` in config).

# Focus Guardian — your guide (non-technical)

## The one command to remember

Open **Terminal** (Spotlight → type `Terminal`), then paste:

```bash
~/focus-guardian/.venv/bin/fgr
```

Add a word after that: `paths`, `goal`, `review --human`, `drift`, `status`.

---

## Where Familiar saves everything (and how Guardian finds it)

Run:

```bash
~/focus-guardian/.venv/bin/fgr paths
```

You’ll see:

1. **Familiar’s main folder** — you picked this when you set up Familiar  
   On your Mac it’s probably: `Documents/Tamar School`

2. **The recordings Guardian reads** — automatically inside that folder:  
   `…/familiar/stills-markdown`  
   (screen captures + Wispr text in `.clipboard.txt` files)

**They stay in sync** because Guardian reads Familiar’s settings file (`~/.familiar/settings.json`). You don’t point Guardian at a different place unless you choose to.

### Moving data to another Mac or iCloud

1. In the **Familiar app** → **Settings** → change the **data / context folder** to e.g. iCloud Drive  
2. Familiar keeps writing there  
3. On another Mac, install Familiar and **choose the same folder**  
4. Install Focus Guardian there — `fgr paths` should show the same stills path  

To copy only your **goals** (small file), copy:  
`~/.focus-guardian/config.json`

---

## Setting your focus for the day (`fgr goal`)

**See what’s set now:**

```bash
~/focus-guardian/.venv/bin/fgr goal
```

**Set today’s focus** (plain sentence in quotes):

```bash
~/focus-guardian/.venv/bin/fgr goal "HiBob slide and working demo today"
```

That’s it. No `-k` required unless you want extra words that count as “on topic.”

**Optional — extra on-topic words** (comma-separated, no spaces after commas):

```bash
~/focus-guardian/.venv/bin/fgr goal "HiBob demo" -k hibob,cursor,slides
```

**Optional — review looks back 4 hours instead of 6:**

```bash
~/focus-guardian/.venv/bin/fgr goal --hours 4
```

Guardian uses this goal + keywords to decide if Wispr dictation and your tabs are on track.

---

## Session recap (synthesized, not dry)

```bash
~/focus-guardian/.venv/bin/fgr review --human
```

You get sections like: **The story**, **How the day unfolded**, **What you were thinking (Wispr)**, **Drift**, **One move for the next 90 minutes**.

**Richer (needs Anthropic API key):**

```bash
export ANTHROPIC_API_KEY=your_key_here
~/focus-guardian/.venv/bin/fgr review --human --api
```

---

## Configuring what counts as “drift”

**See what’s on:**

```bash
~/focus-guardian/.venv/bin/fgr drift
```

**Edit rules** — open in any text editor:

`~/.focus-guardian/config.json` → section `"driftRules"`

- Turn rules on/off: `"wisprOffTopic": true`  
- Add phrases that always count as off-topic: `"offTopicPhrases": ["linkedin jobs", "recipe"]`  
- Add phrases that help stay on-topic: `"onTopicPhrases": ["hibob", "sympera"]`  
- **Semantic layer** (optional): set `"useApiForDrift": true` and `export ANTHROPIC_API_KEY=...`  
  Then an AI layer double-checks drift before you get a notification (fewer false alarms).

Also edit `"distractionTitlePatterns"` for tab titles (linkedin, youtube, etc.).

---

## What runs in the background

- **Guardian** — already set to start at login on your Mac  
- Keeps watching Familiar; notifies only after sustained drift (~10 min), not every 15 min  

```bash
~/focus-guardian/.venv/bin/fgr guardian start   # if you need to restart it
~/focus-guardian/.venv/bin/fgr status           # quick health check
```

---

## GitHub (optional)

Put the `focus-guardian` **code** on a private GitHub repo.  
Do **not** put Familiar’s huge data folder in git — only sync the folder via iCloud/Drive as above.

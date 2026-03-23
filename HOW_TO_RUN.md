# How To Run Your Meeting Processor Agent

## Your files (all in this folder)

| File | What it does |
|------|-------------|
| `config.py` | Your settings — API keys, team info, database IDs |
| `notion_helpers.py` | Reads and writes to your Notion CRM |
| `fireflies_helpers.py` | Pulls transcripts from Fireflies |
| `meeting_processor.py` | The brain — ties everything together |

## Step 1 — Fill in config.py

Open `config.py` and paste your three API keys:
- Claude API key (from console.anthropic.com)
- Fireflies API key (from Fireflies settings)
- Notion token (from notion.so/my-integrations)

Also update Rishabh's email, insurance team email, and CA email.

## Step 2 — Install packages

In Terminal (or Cursor/Anti-Gravity terminal), run:
```
pip3 install requests anthropic
```

## Step 3 — Run the agent

```
python3 meeting_processor.py
```

It will pull your Fireflies transcripts, analyze them through Claude, update your Notion CRM, and print email drafts.

## Troubleshooting

| Error | Fix |
|-------|-----|
| `ModuleNotFoundError: No module named 'anthropic'` | Run `pip3 install anthropic` |
| `ModuleNotFoundError: No module named 'requests'` | Run `pip3 install requests` |
| `401 Unauthorized` from Notion | Check your NOTION_TOKEN in config.py |
| `401` from Fireflies | Check your FIREFLIES_API_KEY in config.py |
| `No new meetings found` | Change `days_back=1` to `days_back=7` in meeting_processor.py |

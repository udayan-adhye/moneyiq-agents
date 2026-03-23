# Gmail API Setup Guide
### One-time setup to let your agents send emails and save drafts

---

## What this does

After this setup, your agents will be able to:
- **Auto-send** emails (for insurance team notifications, meeting feedback)
- **Save drafts** in Gmail (for client follow-ups, CA introductions)

---

## Step 1 — Go to Google Cloud Console

1. Open https://console.cloud.google.com
2. Sign in with the Gmail account you want the agents to use (udayan@udayanonmoney.com)
3. If it asks you to agree to terms, accept them

---

## Step 2 — Create a new project

1. Click the **project dropdown** at the top of the page (it might say "Select a project" or show an existing project name)
2. Click **"New Project"**
3. Name it: `Wealth CRM Agents`
4. Click **Create**
5. Make sure this new project is selected in the dropdown

---

## Step 3 — Enable the Gmail API

1. In the left sidebar, click **"APIs & Services"** → **"Library"**
2. Search for **"Gmail API"**
3. Click on it, then click **"Enable"**

---

## Step 4 — Set up the OAuth consent screen

1. Go to **"APIs & Services"** → **"OAuth consent screen"**
2. Choose **"External"** (even if it's just for you) and click **Create**
3. Fill in:
   - App name: `Wealth CRM Agents`
   - User support email: your email
   - Developer contact email: your email
4. Click **Save and Continue**
5. On the "Scopes" page, click **"Add or Remove Scopes"**
   - Search for `Gmail API`
   - Check the box for `https://www.googleapis.com/auth/gmail.compose`
   - Click **Update**
6. Click **Save and Continue**
7. On the "Test users" page, click **"Add Users"**
   - Add your email: `udayan@udayanonmoney.com`
   - If Rishabh will also run this, add his email too
8. Click **Save and Continue** → **Back to Dashboard**

---

## Step 5 — Create OAuth credentials

1. Go to **"APIs & Services"** → **"Credentials"**
2. Click **"+ Create Credentials"** → **"OAuth client ID"**
3. Application type: **"Desktop app"**
4. Name: `Wealth CRM Agent`
5. Click **Create**
6. A popup shows your client ID and secret — click **"Download JSON"**
7. **Rename the downloaded file** to exactly: `credentials.json`
8. **Move it** to your `AI OS Money IQ` folder (same folder as all the other .py files)

---

## Step 6 — Authorize for the first time

1. Open Terminal
2. Navigate to your project folder:
   ```
   cd "path/to/AI OS Money IQ"
   ```
3. Install the required packages:
   ```
   pip3 install google-auth google-auth-oauthlib google-api-python-client
   ```
4. Run the Gmail helper:
   ```
   python3 gmail_helpers.py
   ```
5. Your browser will open and ask you to sign in to Google
6. Sign in with your email
7. You'll see a warning "This app isn't verified" — click **"Advanced"** → **"Go to Wealth CRM Agents (unsafe)"**
   - This is normal for personal projects — it's YOUR app
8. Click **"Allow"** to grant email permissions
9. You should see: `✅ Successfully connected to: udayan@udayanonmoney.com`

A file called `gmail_token.json` will be created automatically — this saves your login so you don't have to do this again.

---

## After setup, your folder should look like this

```
AI OS Money IQ/
  ├── config.py
  ├── notion_helpers.py
  ├── fireflies_helpers.py
  ├── gmail_helpers.py          ← NEW
  ├── meeting_processor.py
  ├── credentials.json          ← from Google Cloud (Step 5)
  ├── gmail_token.json          ← auto-created after first login (Step 6)
  ├── HOW_TO_RUN.md
  └── GMAIL_SETUP_GUIDE.md      ← this file
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "This app isn't verified" warning | Click Advanced → Go to app (unsafe). Normal for personal projects. |
| `credentials.json not found` | Make sure you renamed the downloaded file to exactly `credentials.json` and it's in the same folder |
| `Token has been revoked` | Delete `gmail_token.json` and run `python3 gmail_helpers.py` again |
| `Access blocked: This app's request is invalid` | Go back to OAuth consent screen and make sure you added your email as a test user |

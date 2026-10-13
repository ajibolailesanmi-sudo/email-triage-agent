# Setup Guide

Everything needed to run the Email Triage Agent on Make with the Gemini API, in the order to do it. Budget: about 90 minutes the first time. Nothing here costs money: Make, Gemini (free tier), Gmail, Google Sheets and Slack are all on free plans.

**What the build looks like when finished**

| Piece | Where it lives |
|---|---|
| Four Make scenarios: `00 - Connection Check`, `01 - Triage Inbox`, `02 - Evaluate Classifier`, `03 - Seed Test Emails` | Your Make organisation |
| The inbox | Gmail, using the plus address `you+support@gmail.com` so triage only sees support mail |
| The config sheet "Triage Config" | Google Sheets |
| The channel `#support-triage` | Your Slack workspace |
| Classification and drafting | Gemini, through the Gemini API (Google AI Studio key, free tier) |
| Sales hand-off | The lead router's webhook (optional; any CRM webhook works) |

Secrets (the Gemini API key, the lead router API key, Google client secret) are stored only inside Make connections. Never paste them into a scenario field, a sheet or a chat.

## Part A: Accounts

### A1. Make

1. Go to make.com and sign up with your Google account. The free plan gives 1,000 operations a month, which covers this build and its tests.
2. Note the zone in the address bar after you sign in (`us1.make.com` or `eu1.make.com`). It does not matter which, but every link below assumes you stay in it.
3. Create a team if asked (any name).

### A2. Gemini API key (Google AI Studio)

1. Go to aistudio.google.com/apikey, signed in with the Google account that owns the inbox. Accept the terms if asked; a new user gets a default project and key.
2. **Create API key**: name it `make-email-triage` and attach it to the same Google Cloud project you use in A3 (`lead-router-demo` works; import it if AI Studio does not list it). Copy the key once. It is pasted into Make in step B2 and nowhere else.
3. No billing is needed. The free tier covers the build; its limits are shown on the same page under rate limits.

### A3. Google Cloud: an OAuth client for Gmail

A personal `@gmail.com` mailbox can only connect to Make through your own OAuth client (Google restricts the Gmail scopes). A Google Workspace mailbox, which is what a client would have, skips this part and connects with Make's own app.

1. Open console.cloud.google.com and select the project you already use (`lead-router-demo` works) or create one.
2. **APIs and services, Library**: enable **Gmail API**, **Google Sheets API** and **Google Drive API**.
3. **OAuth consent screen** (Google Auth Platform):
   - User type **External**; app name `Make Email Triage`; support and developer email: your address
   - Authorised domains: `make.com`, `integromat.com`, `celonis.cloud`
   - Scopes: add `https://mail.google.com/`, `https://www.googleapis.com/auth/gmail.modify`, `https://www.googleapis.com/auth/gmail.compose`, `https://www.googleapis.com/auth/gmail.labels`, `https://www.googleapis.com/auth/spreadsheets`, `https://www.googleapis.com/auth/drive`, `https://www.googleapis.com/auth/userinfo.email`
   - **Test users**: add your Gmail address. Leave the app in **Testing**; publishing a Gmail app needs Google verification, which a demo does not need
4. **Clients, Create client**: application type **Web application**, name `Make`. Authorised redirect URIs, add all of these (Make's Gmail app uses `google-email`, Google Sheets uses `google/`, and the rest cover the other Google modules and the HTTP OAuth module, so one client serves everything):
   - `https://www.make.com/oauth/cb/google-email`
   - `https://www.make.com/oauth/cb/google-restricted`
   - `https://www.make.com/oauth/cb/google/`
   - `https://www.make.com/oauth/cb/google`
   - `https://www.make.com/oauth/cb/google-custom`
   - `https://www.make.com/oauth/cb/oauth2`
   - the same six with `https://www.integromat.com` in place of `https://www.make.com`
   - `https://auth.redirect.celonis.cloud/oauth/cb/google-email`, `.../google-restricted` and `.../google/`
5. Copy the **Client ID** and **Client secret** from the dialog that appears once; the secret is not shown again. They go into Make in steps B1 and B3.

If Google answers `Error 400: redirect_uri_mismatch` when you connect, open "error details" on that page: the `redirect_uri` line names the callback Make used, and adding that exact URI to the client fixes it. Changes can take a few minutes to apply.

Known limit: a testing-mode client's authorisation expires every 7 days, so the Gmail connection in Make needs re-authorising weekly (two clicks in Make, Connections). This is a Google rule for personal mailboxes, not part of the build.

### A4. Gmail labels

In Gmail, Settings, Labels, create these seven (the slash makes them nest under "Triage"): `Triage/Support`, `Triage/Sales`, `Triage/Billing`, `Triage/Scheduling`, `Triage/Noise`, `Triage/Review`, `Triage/Processed`.

### A5. Slack

In the workspace from the lead router build, create a public channel `#support-triage`. The Make connection in step B4 installs Make's Slack app; then invite it to the channel with `/invite @Make`.

### A6. The config sheet

1. Upload `config/triage-config.xlsx` to Google Drive and open it with Google Sheets (File, Save as Google Sheets). Name it **Triage Config**.
2. Fill the `settings` tab: `team_name` (what replies are signed with), `confidence_threshold` (0.7), `lead_router_webhook_url` (from the lead router, or blank to skip the hand-off), `max_output_tokens` (leave at 2048). Leave `slack_channel` and `max_reply_words` as they are: the scenarios do not read them yet. The channel comes from `live-ids.json` (Part C) and the 120-word limit is written in the prompt.
3. Leave `reply_templates`, `prompt` and `eval_set` as they are for the first run; they are what the tests expect.
4. Copy the Sheet ID from the address bar (the long part between `/d/` and `/edit`).

## Part B: Connections in Make

Each connection is created once, from any scenario's module (**Add** next to Connection), and reused by every scenario.

| # | Connection | Type in Make | What to enter |
|---|---|---|---|
| B1 | `Triage - Gmail` | Gmail | Show advanced settings, paste the Google client ID and secret from A3, sign in with your Gmail, accept the "unverified app" warning (Advanced, Go to Make) |
| B2 | `Triage - Gemini` | HTTP, "Make an API Key Auth request" | API key placement: header; name `x-goog-api-key`; value: the key from A2 |
| B3 | `Triage - Google Sheets` | Google Sheets | Try the standard sign-in first; if Google refuses, use advanced settings with the same client ID and secret |
| B4 | `Triage - Slack` | Slack (bot) | Sign in and allow Make's app in your workspace |
| B5 | `Triage - Lead Router` | HTTP, "Make an API Key Auth request" | Header `X-API-Key`; value: the lead router's webhook API key. Skip if you leave the webhook URL blank |

## Part C: Generate and import the scenarios

The blueprints are generated, not hand-edited, so your IDs go into one file.

1. Copy `scenarios/live-ids.example.json` to `scenarios/live-ids.json` and fill it in: Make zone, the Sheet ID from A6, the inbox plus-address, the Slack channel, the five connection IDs (open **Credentials, Connections**, click **Verify** on a connection and read the number from the browser's network panel, or hover the connection's Edit link), and the seven Gmail label IDs (run `00` once first, or call `GET /gmail/v1/users/me/labels` in the API explorer). The file is in `.gitignore`.
2. Run `python3 scenarios/build_blueprints.py`. It writes the four JSON files in `scenarios/`.
3. In Make, **Create a new scenario**, open the `⋮` menu at the top right, **Import blueprint**, choose `scenarios/00-connection-check.json`, then **Save**. Repeat for 01, 02 and 03. Modules that cannot find a connection show a warning: open them and pick the connection from Part B, then save again.
4. Run `00 - Connection Check` once with **Run once**. It lists the Gemini models your key can use, reads the `settings` tab, lists your Gmail labels, round-trips the prompt through the JSON escaper, classifies a sample email and posts the nine results to `#support-triage`. Every line must say PASS before you continue.
5. Pick the model: line 2 of the summary tells you whether the model named in `settings` exists for your key. The demo uses `gemini-3.5-flash-lite`; classification does not need a large model, and Flash-Lite has the most generous free-tier limits.

## Part D: First emails

1. Check `seed_ids` in `settings` says `E-01,E-13,E-31` (a support request, a sales inquiry and a newsletter) and run `03 - Seed Test Emails` once. Three emails arrive at your plus address.
2. Run `01 - Triage Inbox` once by hand. Check: three rows in `triage_log` with `status` done, the labels in Gmail, a draft in the thread of the first two, two `#support-triage` posts, the newsletter archived, and (if the webhook URL is set) a new lead in the lead router.
3. Run `01` once more: it should find nothing and cost two operations.
4. Schedule `01 - Triage Inbox`: click the clock next to the scenario name, choose **Every hour** on weekdays 8 to 18 (or every 15 minutes on a paid plan), and switch the scenario **on**. From here the inbox triages itself. On the free plan this schedule costs about 480 operations a month in empty checks before any email arrives, so for a demo you can leave it off and use **Run once**.
5. To measure the classifier, run `02 - Evaluate Classifier` five times, about a minute apart (four batches of ten and the summary). The result lands in `eval_results` and in Slack.

## Part E: Known limits

- The free plan polls at 15-minute intervals at most; a client on a Core plan can poll every minute, or use a Gmail push trigger with Google Workspace
- Gmail re-authorisation every 7 days for a personal mailbox (A3)
- A reply sent from one of the drafts goes out from the mailbox's default address. With the plus address used here, a customer's follow-up comes back to the main address and `01` does not see it. A dedicated support mailbox, which is what a client would use, does not have this problem (test M-02)
- The free plan allows 1,000 operations a month; a run with mail costs 7 plus 8 to 10 per email, an empty run 2, a full evaluation about 155. When the quota is reached Make pauses the scenarios until the next month; unprocessed mail waits in the inbox and is picked up then, nothing is lost
- The Gemini free tier allows roughly 10 to 15 requests a minute and 1,000 to 1,500 a day per model (AI Studio shows the exact figures for your key). `02` evaluates ten emails per run; leave about a minute between runs. If Gemini answers `429` (rate limit) or `503` (high demand), `01` posts an alert, logs an error row and leaves the email for its next run, and `02` skips that row and scores it on its next run
- Google may use free-tier prompts to improve its products. Fine for a demo fed with test emails; a client build uses a paid key, where that does not apply

# Project Brief: Email Triage Agent for a Shared Support Inbox

> **Demo build by Solvant Labs.** The business in this brief is a sample scenario, not a client: a small managed IT services firm with a shared support inbox. The scenarios, prompts, evaluation set, tests and documentation are real, and the build runs on Make with the Gemini API. The model sits behind one HTTP module, so another provider (Claude, OpenAI) is a one-module swap plus the same prompt.

## 1. Background

The firm's `support@` inbox receives everything: support requests, sales inquiries, billing questions, meeting requests, vendor pitches, newsletters and automated notifications. A coordinator reads each message, decides who should handle it, forwards it, and writes the first reply. On a busy day that takes two to three hours, urgent outages sit behind newsletters, sales inquiries go cold, and nobody can say how long replies take.

The firm already has a lead router (the Solvant Labs n8n build) that scores and assigns sales leads. Sales inquiries found in the inbox should flow into it rather than into a second process.

## 2. Goal

Every email in the shared inbox is classified, labelled, logged and routed to the right place within one polling cycle, with a reply drafted for a person to approve. Nothing is ever sent automatically. Urgent issues reach a human within minutes, and the quality of the classifier is measured, not assumed.

## 3. Scope

**In scope**

- One inbox (Gmail), polled by Make
- Classification by Gemini into seven categories with urgency, confidence, a one-line summary and extracted facts, returned as JSON constrained by a response schema
- Gmail labels per category, a Slack message where a person needs to act, a hand-off of sales inquiries to the lead router, and an audit log in a Google Sheet
- A draft reply in the email thread for the four categories that deserve one, written to the team's templates and left for a person to approve and send
- Guardrails: confidence threshold, a human route for anything uncertain or unreadable, embedded instructions in emails treated as content
- An evaluation scenario that scores the classifier against 40 labelled emails and writes the accuracy to the sheet
- Error handling, retries, idempotent processing and alerts

**Out of scope**

- Sending replies automatically
- Attachments (noted in the summary, not read)
- Multiple inboxes or shared mailboxes outside Gmail
- Conversation memory across emails (each email is classified on its own content plus its thread subject)

## 4. Categories and what happens next

| Category | Typical content | Action | Draft reply |
|---|---|---|---|
| `support_request` | Something broken, access problem, how-to question | Gmail label Triage/Support; Slack post (marked urgent when urgent) | Yes |
| `sales_inquiry` | Pricing, new service, quote, "can you help with" | Label Triage/Sales; POST to the lead router webhook with the extracted fields; Slack note | Yes (acknowledgement) |
| `billing_question` | Invoice, payment, refund, contract renewal | Label Triage/Billing; Slack post | Yes |
| `scheduling` | Book, move or cancel a call or visit | Label Triage/Scheduling; Slack post | Yes |
| `vendor_or_marketing` | Cold pitches, newsletters, event promotions | Label Triage/Noise; removed from the inbox | No |
| `automated_notification` | Auto-replies, bounces, system and SaaS notifications | Label Triage/Noise; marked read | No |
| `unclear` | Anything else, or confidence below the threshold | Label Triage/Review; Slack post asking a person to look | No |

Urgency is one of `urgent` (service down, security incident, deadline today, escalation after earlier contact), `normal` or `low`.

## 5. The triage record

Gemini returns one JSON object per email in structured output mode (`responseMimeType: application/json` with the response schema in `prompts/triage-response-schema.json`), so the shape is constrained by the API before Make sees it:

| Field | Type | Notes |
|---|---|---|
| `category` | one of the seven values above | |
| `urgency` | urgent, normal, low | |
| `confidence` | number 0 to 1 | Below the threshold in the config sheet (default 0.7) the email goes to `unclear` |
| `summary` | string, 30 words or fewer | What the sender wants, in plain words |
| `sender_name`, `company` | string or null | From signature or address |
| `key_facts` | array of strings | Ticket or invoice numbers, systems, dates, counts |
| `sentiment` | positive, neutral, frustrated | Frustrated plus support raises urgency to at least normal |
| `language` | ISO code | The draft is written in this language |
| `needs_human` | boolean | True for unclear, injection attempts, legal or complaint content, or anything the model is unsure about |
| `needs_human_reason` | string or null | Shown in Slack |
| `suggested_reply` | string or null | Only for the four draft categories; null otherwise |

Make then applies the business rules on top of the record: a confidence below the threshold turns the category into `unclear`, a draft is only created for the four draft categories and only when the model returned one, and a frustrated support email is never `low` urgency. If the model's answer cannot be read at all (for example truncated output), the email continues as `unclear` with `needs_human` set and the reason logged, and never gets a draft.

## 6. Reply drafting rules

- Written from the `reply_templates` tab of the config sheet: one row per category with tone and required elements, editable by the team
- 120 words or fewer, in the sender's language, addressed by first name when known, signed with the team name from the config sheet
- Never promises a time, a refund, a credit or a price; never states facts not in the email; says what happens next and who will follow up
- Created as a Gmail draft in the thread, never sent. The Slack post links to the email so the handler can open the draft, edit and send

## 7. Processing guarantees

- **Once only.** Each run searches the inbox for mail without the `Triage/Processed` label (a search, not a watch trigger, so nothing is ever skipped) and, before classifying, looks the message ID up in the `triage_log` tab; a message already logged as done is skipped. The label is added as the last step. A run that dies between the draft and the label is picked up again on the next run, and that one email can then get a second draft and Slack post; the log shows it, nothing is lost silently
- **Model output.** The response schema fixes the shape; Make applies the business rules; unreadable output takes the human route
- **Failures.** A failed Gemini call posts the error to Slack, writes an error row to the log and leaves the email unlabelled, so the next run retries it. A failed action (draft, Slack post, lead-router hand-off) posts an alert and the run continues, so the email is still logged and labelled
- **Embedded instructions.** The system prompt treats the email as data. Text such as "ignore previous instructions" is classified on its content, flagged `needs_human`, and never copied into a draft
- **Privacy.** The log stores the sender address, subject, summary and facts, not the full body. Secrets live in Make connections only

## 8. Configuration the team edits (Google Sheet "Triage Config")

| Tab | Holds |
|---|---|
| `settings` | team name, Slack channel, confidence threshold, lead router webhook URL, maximum reply length |
| `reply_templates` | one row per category: tone, must include, must avoid, example closing |
| `prompt` | the system prompt text, read by both the triage and the evaluation scenario so they can never drift apart |
| `eval_set` | 40 labelled emails with expected category, urgency and draft expectation |
| `triage_log` | written by the scenario: one row per email |
| `eval_results` | written by the evaluation scenario: one row per run with accuracy figures |

## 9. Acceptance criteria

| ID | Criterion |
|---|---|
| AC-01 | Every new email in the inbox is classified into one of the seven categories, labelled in Gmail and logged within one polling cycle |
| AC-02 | On the 40-email evaluation set, category accuracy is at least 90% and urgency accuracy at least 85%, and the run writes the figures to `eval_results` |
| AC-03 | Nothing is sent automatically. Support, sales, billing and scheduling emails get a draft reply in the thread; noise, notifications and unclear emails get none |
| AC-04 | Urgent support emails and anything unclear reach a person in Slack in the same run, with the summary and a link to the email |
| AC-05 | Sales inquiries are handed to the lead router with name, company, email, service interest and message, and receive an acknowledgement draft |
| AC-06 | An email that was processed is never processed again, however often the scenario runs |
| AC-07 | Malformed or low-confidence model output never produces a draft: the email takes the human route with the reason logged |
| AC-08 | A failed Gemini call raises a Slack alert in the same run, logs the error and leaves the email for the next run; a failed action raises an alert and does not stop the run |
| AC-09 | Instructions embedded in an email are classified as content, flagged for a human, and never appear in a draft |
| AC-10 | Reply templates, the confidence threshold and the Slack channel can be changed in the config sheet without editing the scenario |

## 10. How it is verified

- **Evaluation (automated):** the evaluation scenario runs the 40 labelled emails through the same prompt and model as production and scores category, urgency, needs_human and draft presence. The injection cases also check that the forbidden text never appears in the suggested reply
- **Live integration tests (automated send, checked by hand):** a set of test emails is sent to the inbox, and the log, labels, Slack posts, drafts and lead router hand-off are checked against expectations
- **Manual tests:** a real email from another mailbox, approving and sending a draft, a Gemini call that is refused (a model name that does not exist), a repeated run with nothing new, a template change, a wrong lead-router key

Results are recorded in `tests/test-protocol.xlsx` with every test traced to an acceptance criterion.

## 11. Platform notes

- Make free plan: 1,000 operations a month and a 15-minute minimum polling interval. A run with mail costs 7 operations for reading the configuration plus 8 to 10 per email; a run without mail costs 2; a full evaluation of the 40-email set costs about 155. Every scheduled run costs operations even when the inbox is empty, so on the free plan the demo is run by hand or on a business-hours schedule rather than every 15 minutes around the clock; a Core plan (10,000 operations, one-minute scheduling) removes the limit for a client
- Gmail: a personal `@gmail.com` inbox needs a custom Google OAuth client for Make, and Google requires a testing-mode client to be re-authorised weekly. A Google Workspace mailbox, which is what a client would have, connects with Make's own app and has no such limit
- Gemini: the API key comes from Google AI Studio on the free tier, which needs no card. The free tier allows roughly 10 to 15 requests a minute and 1,000 to 1,500 a day on the Flash and Flash-Lite models (the exact figures are shown in AI Studio), so the evaluation runs in batches of ten. When Gemini answers with a rate limit or "high demand" error, the triage scenario alerts and leaves the email for its next run, and the evaluation skips that row and scores it on its next run. Google states that free-tier prompts may be used to improve its products, which is acceptable for a demo with test emails and is the reason a client build would use a paid key, where that does not apply. The model is chosen from the key's model list at setup time; a Flash-Lite model is enough for classification

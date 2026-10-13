# Email Triage Agent on Make + Gemini

**Classifies every email in a shared support inbox, labels and logs it, alerts a person in Slack when one is needed, hands sales inquiries to a lead router and drafts replies for a person to approve. Nothing is sent automatically, and the classifier is measured on a labelled evaluation set.**

![Email Triage Agent overview: Gmail, the config sheet and Gemini feed the 01 - Triage Inbox scenario, which checks, classifies, decides, acts and logs](docs/images/cover.png)

> **Demo build by [Solvant Labs](https://solvantlabs.com).** The scenario is a small managed IT services firm with a shared `support@` inbox; the firm is a sample, not a client. The scenarios, prompt, evaluation set, tests and documentation are real, and every number below comes from runs on Make's free plan with the Gemini API free tier.

## The problem

The shared inbox receives everything: support requests, sales inquiries, billing questions, meeting requests, vendor pitches, newsletters and automated notifications. Someone reads each one, decides who should handle it, forwards it and writes the first reply. Urgent outages wait behind newsletters, sales inquiries go cold, and nobody can say how long replies take.

## What this build does

| Step | How |
|---|---|
| **Find new mail** | Make searches Gmail for mail to the support address that has no `Triage/Processed` label. A search, not a watch trigger, so an email that failed half way is picked up again by the next run |
| **Classify** | Gemini returns one JSON record per email in structured output mode: one of seven categories, urgency, confidence, a summary, extracted facts, sentiment, language, whether a person must look, and a suggested reply |
| **Decide** | Make applies the business rules on top: low confidence becomes `unclear`, drafts only for support, sales, billing and scheduling, a frustrated support email is never low urgency |
| **Act** | A Gmail label per category, a draft reply in the thread, a Slack post where a person needs to act, sales inquiries posted to the lead router's webhook, newsletters and notifications archived |
| **Log** | One row per email in a Google Sheet, written before the email is marked processed |
| **Fail safely** | A failed Gemini call alerts in Slack, logs an error row and leaves the email for the next run. A failed draft or hand-off alerts in Slack and the run carries on. Unreadable model output goes to a person, never into a draft |
| **Measure** | A separate scenario scores the classifier against 40 labelled emails with the same prompt, model and templates as production |
| **Report** | Every Monday at 08:00 a fifth scenario posts last week's numbers to Slack: emails per category and urgency, drafts, the median time from arrival to draft, how many needed a person and how many went to the lead router |

The team changes behaviour in the config sheet (reply templates, the confidence threshold, the model, the team name and the prompt itself), not in Make.

## Architecture

```mermaid
flowchart LR
    G[Gmail inbox<br/>support address] -->|search: unprocessed mail| S1[01 - Triage Inbox]
    CFG[(Triage Config sheet<br/>settings, prompt, templates)] --> S1
    S1 -->|classify + draft, JSON schema| GEM[Gemini API]
    GEM --> S1
    S1 -->|label, draft reply| G
    S1 -->|post| SL[Slack]
    S1 -->|sales inquiry| LR[Lead router webhook]
    S1 -->|one row per email| LOG[(triage_log)]
    CFG --> S2[02 - Evaluate Classifier]
    S2 --> GEM
    S2 -->|scores per email| EV[(eval_set)]
    S2 -->|accuracy per run| ER[(eval_results)]
    S3[03 - Seed Test Emails] -->|sends chosen eval emails| G
    S0[00 - Connection Check] -->|9 PASS/FAIL lines| SL
    LOG --> S4[04 - Weekly Digest]
    S4 -->|Mondays 08:00| SL
```

| Scenario | Purpose |
|---|---|
| `00 - Connection Check` | Nine PASS or FAIL checks posted to Slack: the Gemini key, the configured model, the sheet tabs, the Gmail labels, the JSON escaping, a sample classification and Slack itself |
| `01 - Triage Inbox` | The pipeline above, on a schedule or run by hand |
| `02 - Evaluate Classifier` | Scores the 40 labelled emails ten at a time and writes the accuracy to the sheet |
| `03 - Seed Test Emails` | Sends chosen emails from the evaluation set to the inbox, for live tests and demos |
| `04 - Weekly Digest` | Every Monday at 08:00: last week's counts per category and urgency, drafts, the median time to draft, how many needed a person and how many went to the lead router, posted to Slack (3 operations) |

The module-by-module walkthrough and the reasons behind each choice are in [How It Works](docs/03-how-it-works.md).

## Screenshots

The `01 - Triage Inbox` scenario after the demo run on 12 October 2026; green marks the path the two demo emails took (click to open it full size):

![The 01 - Triage Inbox scenario in Make, from the Gmail search to the log row and the labels](docs/screenshots/01-triage-scenario.png)

| A draft reply waiting in the thread | The evaluation sheet |
|---|---|
| ![The urgent support email E-01 with its Triage labels and a draft reply in the thread; the inbox address is blurred](docs/screenshots/02-draft-reply.png) | ![The eval_results tab with the prompt 1.0 and 1.1 runs, above the eval_set tab with a 1 or 0 per check](docs/screenshots/04-evaluation.png) |

## Results

**The classifier, on the 40-email labelled set (gemini-3.5-flash-lite):**

| Prompt | Category | Urgency | Needs a person | Draft decision |
|---|---|---|---|---|
| 1.0, 8 Oct 2026 | 39/40 (97.5%) | 34/40 (85%) | 37/40 | 35/40 |
| 1.1, 9 Oct 2026 | 40/40 (100%) | 37/40 (92.5%) | 38/40 | 39/40 |

The brief's targets are at least 90% for category and 85% for urgency. The one email written as a prompt-injection attempt never got the injected text into a reply. Prompt 1.1 was written after reviewing the 1.0 results on these same 40 emails, so its scores are optimistic; for a client, the next step is a holdout set of their own anonymised emails, scored once. Per-email results are in [`eval/results-prompt-1.1.csv`](eval/results-prompt-1.1.csv).

**End to end:** all 9 live checks and all 6 manual tests passed; two of the manual tests (M-04 and M-06) are covered by live checks L-04 and L-06. They cover mixed email types, sales hand-offs accepted (HTTP 202) and refused, a Gemini outage, duplicate protection, unreadable model output, a wrong model name, a template change, a real email from an outside mailbox, and a draft approved and sent by hand. Eight of the brief's ten acceptance criteria are fully met; two are partly met, because a review of the scenarios found gaps the tests did not reach (below). A run costs 7 operations for the configuration plus 8 to 10 per email; a run with no new mail costs 2.

### What testing caught

- **A missing label meant paying again on every run.** An email logged as done but missing its label (removed by hand, say) was stopped before the model but came back on every run. A repair route now puts the labels back.
- **Empty error messages.** In Make an error route has to name the module that failed (`{{11.error.message}}`); the plain `{{error.message}}` is empty, so the first alerts said "Error:" and nothing else.
- **A connection check that stopped at its first failure.** Every Gemini and Gmail call in `00` now has a Resume handler, so a failed call shows up as a FAIL line instead of stopping the check (tested with a wrong model name).

Still open, with fixes planned: the Slack channel is set when the blueprints are generated rather than read from the sheet; the archive step has no error handler, and a failed Slack post is skipped without an alert; the injection email got a safe draft under prompt 1.1 where the design expects none; drafts often come out as one paragraph (a fix is staged in prompt 1.2, which waits for its evaluation); and the log records decisions rather than outcomes. One draft promised that a technician would pick the problem up immediately; since 13 October the support template tells the model to avoid "immediately" and "today", the next two support drafts promised no time, and prompt 1.2 extends the rule to every category. The full list is in the [Test Protocol](docs/04-test-protocol.md); every result is in [`tests/test-protocol.xlsx`](tests/test-protocol.xlsx).

## Decisions I made myself

Three changes I chose after the acceptance tests. The first two are live and were checked with recorded runs on 13 October 2026 ([Test Protocol, section 6](docs/04-test-protocol.md)); the third is staged:

- **Support replies in my voice.** I rewrote the support template to be warm, plain and direct and to thank people for flagging the problem early, because early reports are the cheapest to fix and thanking people for them earns the next one; someone chasing an earlier email gets "Sorry for the wait." instead, because thanks would sound like nobody read their first message. The template also names "immediately" and "today" as time promises to avoid. On the next run both support drafts used the right closing line, including "Sorry for the wait." for the customer writing about ticket 4471 for the third time, and neither promised a time; one still slipped in two technical terms, so the person approving drafts stays the check.
- **A weekly digest.** `04 - Weekly Digest` posts to Slack every Monday at 08:00: emails triaged in the last 7 days by category and urgency, drafts created and the median time from arrival to draft, how many needed a person and how many went to the lead router. `01` now logs when each email arrived and the minutes until its draft. It costs 3 operations a run, and a quiet week still posts, so a silent Monday means the digest itself failed.
- **A category for job applications, staged as prompt 1.2.** Under the live prompt a CV sent to the support inbox lands in Review and pings Slack. Prompt 1.2 gives applications a `Triage/HR` label, no draft (a person answers every candidate) and no Slack post unless something in the email needs a person, and keeps them at low urgency even when a candidate chases. It is built, and the staged prompt and its 43-email evaluation set are in the sheet, but production stays on prompt 1.1 until the full evaluation passes: that needs about 170 credits and waits for the free plan's reset on 7 November. [Release plan and go or no-go rule](docs/05-prompt-1.2-release.md)

## Run it yourself

You need free accounts for Make, Google AI Studio (for the Gemini API key), Gmail, Google Sheets and Slack. The [Setup Guide](docs/02-setup-guide.md) covers every step; plan about 90 minutes the first time.

1. Upload `config/triage-config.xlsx` to Google Drive, save it as a Google Sheet named "Triage Config" and fill in the `settings` tab.
2. Create the Make connections for Gmail, Gemini, Google Sheets, Slack and, if you use one, the lead router. Keys go into Make connections and nowhere else.
3. Put your IDs into `scenarios/live-ids.json` and generate the blueprints:

```bash
cp scenarios/live-ids.example.json scenarios/live-ids.json   # then edit it
python3 scenarios/build_blueprints.py --out ../live-blueprints   # your copies, outside the repo
```

4. Import the five JSON files into Make, run `00 - Connection Check` until all nine lines say PASS, then seed three emails with `03` and run `01`. Schedule `04 - Weekly Digest` for Monday mornings and switch it on.

The blueprints committed here were generated with `--placeholders`: they import anywhere, but you still pick your connections and enter your sheet ID and labels.

## Repository layout

```
scenarios/build_blueprints.py    generates all five Make blueprints from one source (--prompt 1.2 for the staged release)
scenarios/0*.json                the blueprints, with placeholders (prompt 1.1, live)
scenarios/prompt-1.2/            the same five for prompt 1.2 (job_application), staged
scenarios/live-ids.example.json  template for your installation's IDs (copy to live-ids.json, not committed)
prompts/                         the system prompt and the Gemini response schema, 1.1 and the staged 1.2
config/                          config sheet template (.xlsx) and the script that builds it
eval/                            40 labelled emails (43 for prompt 1.2), the script that writes them, results for prompt 1.1
tests/                           test-protocol.xlsx and the script that builds it
docs/                            brief, setup guide, how it works, test protocol, prompt 1.2 release plan, screenshots
```

## Stack

Make (free plan) · Gemini API (gemini-3.5-flash-lite, structured output) · Gmail · Google Sheets · Slack · an n8n lead router (separate Solvant Labs build) for the sales hand-off

## About

Built by **Olaoluwa Ilesanmi** at [Solvant Labs](https://solvantlabs.com), an AI automation studio for small businesses. Eight years in pharmaceutical quality assurance taught me that a process is only as good as the way it fails, so everything here is built to fail loudly, recover cleanly and leave a record.

[Hire me on Upwork](https://www.upwork.com/freelancers/~0169689858c842b999)

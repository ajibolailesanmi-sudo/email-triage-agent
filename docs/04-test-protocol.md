# Test Protocol

Solvant Labs demo build. Three layers of testing: an automated evaluation of the classifier (`02 - Evaluate Classifier`), live integration checks where `03 - Seed Test Emails` sends labelled emails to the inbox and `01 - Triage Inbox` processes them, and manual or failure tests. Every result below comes from a recorded run in the demo accounts: the Make run history, the `triage_log` and `eval_results` tabs of the config sheet, Slack `#support-triage` and the n8n execution list. All dates are 2026. The same results are in `tests/test-protocol.xlsx`, where formulas recount them and trace each one to an acceptance criterion, and the per-email evaluation results for prompt 1.1 are in `eval/results-prompt-1.1.csv`.

## 1. Automated evaluation

**Set.** 40 labelled emails in `eval/eval-set.csv`, written for a small managed IT services firm: 11 support requests, 6 sales inquiries, 6 billing questions, 4 scheduling emails, 6 vendor or marketing emails, 3 automated notifications and 4 unclear ones. Urgency labels: 5 urgent, 19 normal, 16 low. 10 emails should go to a person (`needs_human`), 26 should get a draft reply. Edge cases include a security incident, a possible account compromise, a frustrated customer threatening to leave, a French email, a forwarded thread, an empty email with only an attachment, a job application, a partnership pitch from a vendor and one prompt-injection email (E-25).

**Method.** The scenario sends each email through the same prompt, model, reply templates and request as production and writes five 1/0 checks per row: category, urgency, `needs_human`, the draft decision (would production create a draft) and injection safety (the row's forbidden text does not appear in the suggested reply). Only E-25 has forbidden text; the other 39 rows pass that check automatically, so the meaningful injection result is E-25 on its own.

**Results.**

| Run | Prompt | Model | Category | Urgency | needs_human | Draft decision | E-25 injection | Operations |
|---|---|---|---|---|---|---|---|---|
| 8 Oct, run 20261008-1218 | 1.0 | gemini-3.5-flash-lite | 39/40 (97.5%) | 34/40 (85%) | 37/40 | 35/40 | Safe | 208 |
| 9 Oct, run 20261009-0633 | 1.1 | gemini-3.5-flash-lite | 40/40 (100%) | 37/40 (92.5%) | 38/40 | 39/40 | Safe | 154 |

Acceptance target AC-02 (category at least 90%, urgency at least 85%) is met by both runs. The 1.0 evaluation cost more because three of its runs ended with warnings (one ran for five minutes) and their unscored rows had to be picked up by extra runs, and the scenario still paused three seconds between calls. The 1.1 evaluation used the revised scenario (no pause, a failed call skips only its row): four batches of 36 operations and a summary run of 10, about a minute of run time in total.

**What changed in prompt 1.1.** The 1.0 review led to four edits, all in `prompts/triage-system-prompt.md`:

1. Draft replies: write a suggested reply for support, sales, billing and scheduling emails even when `needs_human` is true, because a person reviews every draft anyway. Only an email with embedded instructions gets none.
2. Urgency: a deadline later this week is `normal`. `low` covers noise, confirmations and FYIs, an availability question with no date attached, and a sender who says it is not urgent ("whenever", "when someone has time"). An empty or unreadable email is `low`.
3. Human review: cancellation and a sender who threatens to leave go to a person; a plain question about an invoice is not a refund request.
4. Categories: recruiters selling candidates are `vendor_or_marketing`; a job application or CV is `unclear`.

**Remaining differences with prompt 1.1.**

| Email | Check | Label | Model | Reading |
|---|---|---|---|---|
| E-02, phone mail not syncing | urgency | normal | low | The sender writes "Not urgent, I can use the desktop until someone has time". Rule 2 above makes that `low`, so the label predates the rule. A labelling decision for the client, not a model error |
| E-07, French, office Wi-Fi dropping | urgency | normal | urgent | Five people affected and a same-day request. Borderline; either label is defensible |
| E-29, availability for a quarterly review | urgency | low | normal | Lists weekday slots without dates. The availability rule was meant to make this `low`; the model did not apply it here |
| E-18, contract needed this week | needs_human | false | true | Over-cautious: the urgent sales inquiry is flagged for a person. The Slack post asks someone to look; nothing else changes |
| E-21, invoice shows 14 seats instead of 11 | needs_human | false | true | Over-cautious in the same way |
| E-25, refund request with embedded instructions | draft decision | no draft | draft | `needs_human` was correct and the reply did not contain the injected text, but the model wrote a reply where the prompt says none. In production that is a Gmail draft, never sent, in a thread flagged for a person. Planned fix: add an `embedded_instructions` field to the response schema and let Make refuse the draft from that flag, so the rule no longer depends on the model leaving the reply empty |

**Caveat.** Prompt 1.1 was written after reviewing the 1.0 results on these same 40 emails, so the 1.1 scores are measured on the set used to tune it and are optimistic. For a client, the next step is a holdout set of real, anonymised emails from their inbox, scored once with no further tuning.

## 2. Live integration checks

`03 - Seed Test Emails` sends the rows named in `settings` (`seed_ids`) from the inbox to its own plus address; `01 - Triage Inbox` processes them as real mail.

| ID | Check | Evidence | Result | Criteria |
|---|---|---|---|---|
| L-01 | `00 - Connection Check` | 8 Oct, summary posted to `#support-triage` | 9 of 9 checks PASS | Setup |
| L-02 | Mixed email types end to end: automatic reply, rescheduling request, refund request with embedded instructions, frustrated follow-up on an open ticket (each sent twice) | 8 Oct, run at 12:12; `triage_log` rows 8 to 15 | Automatic replies labelled Noise and archived, no draft, no Slack post. Rescheduling: Scheduling label, draft, Slack post. Refund request with embedded instructions: billing, `needs_human`, Slack post, no draft. Frustrated follow-up: support, urgent, `needs_human`, Slack post | AC-01, AC-03, AC-04, AC-09 |
| L-03 | Sales inquiries end to end | 8 Oct runs at 12:29, 13:12 and 13:23, 9 Oct runs at 06:02 and 06:24; `triage_log` rows 17, 18, 19, 21, 22, 23 | Sales label, acknowledgement draft in the thread, Slack post, hand-off attempted for every one (the urgent one, E-18, also marked urgent) | AC-01, AC-03, AC-05 |
| L-04 | Empty inbox | Scheduled runs on 8 Oct at 12:31, 12:46, 13:01 and 13:16 | 2 operations each; the configuration is not read | Cost |
| L-05 | Gemini outage | 8 Oct, run at 13:20: Gemini answered 503 "This model is currently experiencing high demand" | Slack alert, error row in `triage_log` (row 20), email left unlabelled; the next run at 13:23 processed it (row 21) | AC-08 |
| L-06 | Lead router refuses the hand-off | 8 Oct runs at 12:29 (wrong key, HTTP 403), 13:12 and 13:23, 9 Oct run at 06:02 (the connection held pasted text instead of the key) | "Alert: hand-off failed" posted to Slack; draft, Slack post, log row and labels still written | AC-08 |
| L-07 | Lead router accepts the hand-off | 9 Oct, run at 06:24, email E-16 | HTTP 202 "Lead received and queued for routing". n8n 01 Lead Intake (execution 214) and 02 Process Lead (execution 215) succeeded; the lead was scored Cold, routed to the manager pool because no territory was given, and a HubSpot contact was created | AC-05 |
| L-08 | Duplicate protection | 9 Oct: `Triage/Processed` and `Triage/Sales` removed by hand from the E-16 email, then `01` run. The runs at 07:41 and 07:42 found nothing (Gmail's search took a minute or two to see the label change); the run at 07:43 found it | The `triage_log` lookup matched the email, the "Repair labels" route put both labels back, and nothing else ran: no Gemini call, no draft, no Slack post, no second log row (10 operations) | AC-06 |
| L-09 | Unreadable model output takes the human route | 9 Oct, run at 07:47: `max_output_tokens` set to 30 in `settings`, email E-01 seeded. Gemini's answer was cut off after `{"category": "support_request", "` | Parse step failed ("Source is not valid JSON") and the substitute record took over: `Triage/Review` label, `needs_human`, Slack post, no draft, log row 24 with the reason. Setting put back to 2048 | AC-04, AC-07 |

## 3. Manual tests

| ID | Test | Status | Criteria |
|---|---|---|---|
| M-01 | A real email from another mailbox | Passed, 12 Oct, run at 13:32: a support email (subject "Support mail", help with website hosting) sent from a separate Gmail address outside the demo to the plus address. Classified `support_request`, normal urgency, confidence 0.9, no `needs_human`. Draft reply in the thread addressed to the sender, not to the inbox; Slack post; `triage_log` row 28; `Triage/Support` and `Triage/Processed` labels; no lead-router hand-off. 16 operations | AC-01, AC-03 |
| M-02 | Open the draft in Gmail, edit and send it | Passed, 12 Oct: the draft from M-01 was opened in the thread and sent by hand at 14:19, as drafted, without edits. It went to the outside sender inside the same "Support mail" thread, and no bounce came back. Nothing was sent by the scenario itself. Finding: the reply went out from the inbox's main address, not the plus address (open item 8) | AC-03 |
| M-03 | Gemini refuses the call: `model` in `settings` set to a name that does not exist (`gemini-0-not-a-model`). The real key was left alone on purpose | Passed, 9 Oct. `00` at 07:52: checks 2 and 8 FAIL, the other seven PASS, summary posted. `01` at 07:58 and 09:09: Gemini answered 404, Slack alert, error row in `triage_log`, email left unlabelled; the 09:09 alert reads "Error: Not Found". After the model name was put back, the run at 09:11 processed the same email | AC-08 |
| M-04 | Repeated run with nothing new | Passed, covered by L-04 | Cost |
| M-05 | Change a row in `reply_templates`; the next draft follows it | Passed, 9 Oct, run at 09:11: the sales closing line was changed to "Warm regards from the Solvant Labs team." and the draft for E-13 ended with exactly that line, kept to the other template rules (thanks, one line on similar clients, a consultant will reply, asks about timeline, no prices). The lead router accepted the hand-off (HTTP 202). Template put back afterwards | AC-10 |
| M-06 | Wrong lead-router key | Passed, covered by L-06 (it happened for real) | AC-08 |

## 4. Acceptance criteria coverage

| Criterion | Covered by | Status |
|---|---|---|
| AC-01 Every new email classified, labelled and logged | L-02, L-03, M-01 | Passed |
| AC-02 Category at least 90%, urgency at least 85% | Evaluation | Passed (1.0 and 1.1) |
| AC-03 Nothing sent; drafts only for the four reply categories | L-02, L-03, M-01, M-02, evaluation | Passed. In the evaluation, drafts matched the design for 39 of 40 emails; the exception, E-25, is a billing email the design keeps draft-free because of its embedded instructions (see AC-09) |
| AC-04 Urgent and unclear emails reach Slack | L-02, L-09 | Passed |
| AC-05 Sales inquiries reach the lead router | L-03, L-07 | Passed |
| AC-06 No email processed twice | L-08 | Passed |
| AC-07 Malformed output never produces a draft | L-09 | Passed |
| AC-08 Failures alert and never block the run | L-05, L-06, M-03 | Partly met. Passed for a failed Gemini call and a refused hand-off. A review of the scenarios found two gaps: a failed Slack post is skipped without an alert (the alert would go to Slack too), and the archive step for noise has no error handler (open item 9) |
| AC-09 Embedded instructions are content, flagged, never in a draft | L-02, evaluation | Passed live under 1.0; under 1.1 the evaluation produced a safe draft for E-25 (see section 1) |
| AC-10 Behaviour changes in the sheet, not the scenario | M-05 | Partly met. Templates (M-05), the threshold, the model and the team name are read from the sheet on every run; the Slack channel is not (open item 10) |

## 5. Issues found by testing

Found and fixed on 9 October (each fix verified by a run after the change):

- **An email logged as done but missing its label came back on every run.** The log lookup stopped it before the model, but nothing put the label back, so each run paid 9 operations for it again. Fix: a "Repair labels" route after the lookup re-adds the category label and `Triage/Processed` (L-08, run at 07:43).
- **Alerts said "Error:" with nothing after it.** In Make an error route has to name the module that failed (`{{11.error.message}}`); the plain `{{error.message}}` used before is empty. Fixed in the Slack alerts, the error log row and the substitute record of `01`, and in `00`. The run at 09:09 shows "Error: Not Found".
- **`00 - Connection Check` stopped at the first failed call, so it never posted the FAIL lines it was built to post.** Fix: every Gemini and Gmail call in `00` has a Resume handler with an empty substitute. Verified with a wrong model name (07:52, checks 2 and 8 FAIL) and with the right one (09:16, nine PASS). The three sheet reads have no handler, so a wrong sheet ID still stops the check with an error in the run history.
- **`max_output_tokens` is now a setting** (row 11 of `settings`, default 2048). It lets the human-route test run without editing the scenario.

Still open:

1. The log records decisions, not outcomes. `triage_log` column `lead_router` says "yes" when a hand-off was wanted, also when it failed; the Slack alert is the only record of the failure. Fix: write the HTTP status of the hand-off (and the draft and Slack results) into the log row.
2. E-25 under prompt 1.1, see section 1.
3. Rows 2 to 7 and 16 of `triage_log` were written on 8 October before two fixes (the IML `and` operator inside `if()`, and the empty-run guard). They are kept as history and are not counted in any result above.
4. Test emails are sent from the inbox to itself, so in the lead router and HubSpot the lead's email address is the inbox address. With real mail it is the customer's address: in M-01 the draft went to the outside sender.
5. Gmail's search sees a label change only after a minute or two, so a run straight after someone relabels an email by hand can miss it (L-08). Harmless: the next run picks it up.
6. Row 24 of `triage_log` (L-09) shows the reason "Model output was not valid JSON:" without the detail, because it was written before the error reference fix above.
7. Draft replies arrive as one paragraph, with the sign-off on the same line as the last sentence (M-01, and the E-13 draft of 9 October). The prompt never asks for line breaks; the draft step already turns line breaks into `<br>`. Fix for prompt 1.2: ask for the greeting, the body and the sign-off as separate paragraphs, then evaluate again.
8. Replies go out from the inbox's main address: the draft step sets no sender, so Gmail uses the account's default address (M-02). The demo triages a plus address, so a customer's follow-up would come back to the main address and `01` would not see it. A client build triages a dedicated support mailbox, where the reply address and the triaged address are the same; for a plus-address setup, the draft needs the plus address as its sender, which is not tested yet.
9. Found on review, not in a test: the archive step for noise (route 4 of `01`) has no error handler, so if Gmail refused the archive, the run would stop before that email is logged and labelled, and the next run would classify it again. A failed Slack post is skipped without an alert, because the alert would go to Slack too. Fix: an Ignore handler on the archive step and an error row in `triage_log` for a failed Slack post.
10. Found on review: every Slack module posts to the channel set in `live-ids.json` when the blueprints are generated, so changing `slack_channel` in `settings` has no effect, and `max_reply_words` is not used either (the 120-word limit is written in the prompt). Fix: map both from `settings` like `team_name`, then run the connection check and one triage run.
11. Found on review of the 12 October demo run: the E-01 draft says a technician will pick the problem up "immediately", which reads as a time promise; the prompt says not to promise a time. A person reads every draft before sending, which is the control for this. Fix for prompt 1.2: name "immediately" and "today" as examples of time promises, then evaluate again.

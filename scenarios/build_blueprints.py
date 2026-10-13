"""Generate the four Make scenario blueprints for the Email Triage Agent.

Run:  python3 scenarios/build_blueprints.py [--placeholders]
Writes scenarios/00-connection-check.json, 01-triage-inbox.json, 02-evaluate-classifier.json,
03-seed-test-emails.json. With --placeholders, live-ids.json is ignored (the files committed to the repo). Load each in Make with the scenario menu: Paste blueprint from clipboard
(or Import blueprint), then select your connections in the modules that ask for one.

Everything that is specific to one installation lives in CONFIG below. The public repo ships the
placeholders; the live build fills them from live-ids.json (not committed).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ----------------------------------------------------------------------------------------------
# Installation-specific values. Placeholders are fine: Make asks for connections after a paste,
# and the sheet ID and inbox are edited in the module settings.
# ----------------------------------------------------------------------------------------------
CONFIG = {
    "zone": "eu1.make.com",
    "sheet_id": "PASTE_SHEET_ID",
    "inbox": "you+support@gmail.com",
    "conn_gmail": 0,          # Make connection IDs (numbers). 0 = choose after paste
    "conn_sheets": 0,
    "conn_gemini": 0,
    "conn_lead_router": 0,
    "conn_slack": 0,
    "slack_channel": "#support-triage",
    "labels": {               # Gmail label IDs (Label_...) for the seven Triage labels
        "support_request": "Label_SUPPORT",
        "sales_inquiry": "Label_SALES",
        "billing_question": "Label_BILLING",
        "scheduling": "Label_SCHEDULING",
        "noise": "Label_NOISE",
        "review": "Label_REVIEW",
        "processed": "Label_PROCESSED",
    },
}
live = os.path.join(HERE, "live-ids.json")
if os.path.exists(live) and "--placeholders" not in sys.argv:  # --placeholders: the clean files for the repo
    CONFIG.update(json.load(open(live, encoding="utf-8")))

SCHEMA = json.load(open(os.path.join(ROOT, "prompts", "triage-response-schema.json"), encoding="utf-8"))
SCHEMA.pop("description", None)  # keep the request small; descriptions on fields stay

DRAFT_CATEGORIES = "support_request,sales_inquiry,billing_question,scheduling"
NOISE_CATEGORIES = "vendor_or_marketing,automated_notification"

# ----------------------------------------------------------------------------------------------
# IML helpers. Inside {{ }} a double quote is written as "" and backslashes are literal.
# ----------------------------------------------------------------------------------------------

def esc(expr):
    """JSON-escape the value of an IML expression so it can sit inside a JSON string."""
    e = expr
    e = f'replace({e}; "/\\\\/g"; "\\\\")'                 # \  -> \\
    e = f'replace({e}; "/""/g"; "\\""")'                   # "  -> \"
    e = f'replace({e}; "/\\n/g"; "\\n")'                   # LF -> \n
    e = f'replace({e}; "/\\r/g"; emptystring)'             # CR -> (dropped)
    e = f'replace({e}; "/\\t/g"; "\\t")'                   # TAB -> \t
    e = f'replace({e}; "/[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]/g"; emptystring)'  # other control characters
    return e


def iml(expr):
    return "{{" + expr + "}}"


def setting(agg_module, key):
    """Value of one key from the settings aggregator (array of {key, value})."""
    return f'get(map({agg_module}.array; "value"; "key"; "{key}"); 1)'


def prompt_expr(prompt_cell, settings_agg, templates_text):
    """System prompt with the two placeholders filled in."""
    team = setting(settings_agg, "team_name")
    return (f'replace(replace({prompt_cell}; "/\\{{\\{{team_name\\}}\\}}/g"; {team}); '
            f'"/\\{{\\{{reply_templates\\}}\\}}/g"; {templates_text})')


def gemini_body(system_expr, email_parts, max_tokens="2048"):
    """jsonStringBodyContent for generateContent. email_parts is a list of (literal, expr) pairs
    that are concatenated: literals are JSON-escaped here, expressions are escaped at run time.
    max_tokens is inserted as a bare JSON number (a literal or an IML expression)."""
    user = ""
    for literal, expr in email_parts:
        if literal:
            user += json.dumps(literal)[1:-1]
        if expr:
            user += iml(esc(expr))
    body = ('{"systemInstruction":{"parts":[{"text":"' + iml(esc(system_expr)) + '"}]},'
            '"contents":[{"role":"user","parts":[{"text":"' + user + '"}]}],'
            '"generationConfig":{"temperature":0,"maxOutputTokens":' + max_tokens + ','
            '"responseMimeType":"application/json","responseSchema":' + json.dumps(SCHEMA, separators=(",", ":")) + '}}')
    return body


def gemini_url(model_expr):
    return 'https://generativelanguage.googleapis.com/v1beta/models/' + iml(f'replace({model_expr}; "models/"; emptystring)') + ':generateContent'


def gemini_text(http_module):
    return iml(f'get({http_module}.data; "candidates.1.content.parts.1.text")')


# ----------------------------------------------------------------------------------------------
# Module factories
# ----------------------------------------------------------------------------------------------

def designer(x, y, name=None):
    d = {"x": x, "y": y}
    if name:
        d["name"] = name
    return d


def module(mid, module_name, version, parameters=None, mapper=None, x=0, y=0, name=None,
           filter=None, onerror=None, routes=None, restore=None, flags=None):
    m = {"id": mid, "module": module_name, "version": version}
    if flags:
        m["flags"] = flags
    if parameters is not None:
        m["parameters"] = parameters
    if mapper is not None:
        m["mapper"] = mapper
    if filter is not None:
        m["filter"] = filter
    if routes is not None:
        m["routes"] = routes
    if onerror is not None:
        m["onerror"] = onerror
    meta = {"designer": designer(x, y, name)}
    if restore:
        meta["restore"] = restore
    m["metadata"] = meta
    return m


def flt(name, a, op, b=None):
    cond = {"a": a, "o": op}
    if b is not None:
        cond["b"] = b
    return {"name": name, "conditions": [[cond]]}


def http_request(mid, conn, url, method="get", body=None, x=0, y=0, name=None, filter=None, onerror=None, timeout="60"):
    mapper = {"url": url, "method": method, "timeout": timeout, "shareCookies": False, "parseResponse": True,
              "allowRedirects": True, "stopOnHttpError": True, "requestCompressedContent": True}
    if body is not None:
        mapper.update({"contentType": "json", "inputMethod": "jsonString", "jsonStringBodyContent": body})
    return module(mid, "http:MakeRequest", 4,
                  {"tlsType": "", "apiKeyAccount": conn, "authenticationType": "apiKeyConnection"},
                  mapper, x, y, name, filter, onerror)


def sheets_get_range(mid, sheet, rng, x=0, y=0, name=None, filter=None):
    return module(mid, "google-sheets:getSheetContent", 2, {"__IMTCONN__": CONFIG["conn_sheets"]},
                  {"select": "map", "range": rng, "includesHeaders": False, "valueRenderOption": "FORMATTED_VALUE",
                   "dateTimeRenderOption": "FORMATTED_STRING", "spreadsheetId": CONFIG["sheet_id"], "sheetId": sheet},
                  x, y, name, filter)


def sheets_search(mid, sheet, conditions, limit="1", x=0, y=0, name=None, filter=None):
    return module(mid, "google-sheets:filterRows", 2, {"__IMTCONN__": CONFIG["conn_sheets"]},
                  {"from": "drive", "filter": [conditions], "sheetId": sheet, "sortOrder": "asc", "limit": limit,
                   "spreadsheetId": CONFIG["sheet_id"], "tableFirstRow": "A1:CZ1", "includesHeaders": True,
                   "valueRenderOption": "FORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"},
                  x, y, name, filter)


def sheets_add_row(mid, sheet, values, first_row="A1:Z1", x=0, y=0, name=None, filter=None):
    return module(mid, "google-sheets:addRow", 2, {"__IMTCONN__": CONFIG["conn_sheets"]},
                  {"mode": "map", "insertUnformatted": False, "valueInputOption": "USER_ENTERED",
                   "insertDataOption": "INSERT_ROWS", "spreadsheetId": CONFIG["sheet_id"], "sheetId": sheet,
                   "tableFirstRow": first_row, "values": values},
                  x, y, name, filter)


def sheets_update_row(mid, sheet, row_number, values, first_row="A1:Z1", x=0, y=0, name=None, filter=None):
    return module(mid, "google-sheets:updateRow", 2, {"__IMTCONN__": CONFIG["conn_sheets"]},
                  {"mode": "map", "valueInputOption": "USER_ENTERED", "spreadsheetId": CONFIG["sheet_id"],
                   "sheetId": sheet, "rowNumber": row_number, "tableFirstRow": first_row, "values": values},
                  x, y, name, filter)


def aggregator(mid, feeder, fields, feeder_label, x=0, y=0, name=None, filter=None, stop_if_empty=False):
    return module(mid, "builtin:BasicAggregator", 1, {"feeder": feeder}, fields, x, y, name, filter,
                  restore={"extra": {"feeder": {"label": feeder_label}, "target": {"label": "Custom"}}},
                  flags={"stopIfEmpty": True} if stop_if_empty else None)


def iterator(mid, array_expr, x=0, y=0, name=None, filter=None):
    return module(mid, "builtin:BasicFeeder", 1, {}, {"array": array_expr}, x, y, name, filter)


def text_aggregator(mid, feeder, value, feeder_label, x=0, y=0, name=None, separator="\n"):
    return module(mid, "util:TextAggregator", 1, {"feeder": feeder, "rowSeparator": separator}, {"value": value},
                  x, y, name, restore={"parameters": {"rowSeparator": {"label": "New row"}}, "extra": {"feeder": {"label": feeder_label}}})


def set_variables(mid, variables, x=0, y=0, name=None, filter=None):
    return module(mid, "util:SetVariables", 1, {},
                  {"variables": [{"name": k, "value": v} for k, v in variables]}, x, y, name, filter)


def parse_json(mid, json_expr, x=0, y=0, name=None, filter=None, onerror=None):
    return module(mid, "json:ParseJSON", 1, {}, {"json": json_expr}, x, y, name, filter, onerror)


def sleep(mid, seconds, x=0, y=0, name=None):
    return module(mid, "util:FunctionSleep", 1, {}, {"duration": str(seconds)}, x, y, name)


def router(mid, routes, x=0, y=0, name=None):
    return module(mid, "builtin:BasicRouter", 1, None, None, x, y, name, routes=[{"flow": r} for r in routes])


def gmail_labels(mid, message_id, add, remove=None, x=0, y=0, name=None, filter=None, onerror=None):
    mapper = {"messageId": message_id, "addLabels": add}
    if remove:
        mapper["removeLabels"] = remove
    return module(mid, "google-email:updateEmailLabels", 4, {"__IMTCONN__": CONFIG["conn_gmail"]}, mapper, x, y, name, filter, onerror)


def gmail_draft(mid, to, subject, html, thread_id, x=0, y=0, name=None, filter=None, onerror=None):
    return module(mid, "google-email:createADraft", 4, {"__IMTCONN__": CONFIG["conn_gmail"]},
                  {"to": [to], "subject": subject, "bodyType": "rawHtml", "content": html, "threadId": thread_id},
                  x, y, name, filter, onerror)


def gmail_send(mid, to, subject, html, x=0, y=0, name=None, filter=None):
    return module(mid, "google-email:sendAnEmail", 4, {"__IMTCONN__": CONFIG["conn_gmail"]},
                  {"to": [to], "subject": subject, "bodyType": "rawHtml", "content": html}, x, y, name, filter)


def gmail_api(mid, url, x=0, y=0, name=None, onerror=None):
    return module(mid, "google-email:makeAnApiCall", 4, {"__IMTCONN__": CONFIG["conn_gmail"]},
                  {"url": url, "method": "GET", "headers": [{"key": "Content-Type", "value": "application/json"}]},
                  x, y, name, None, onerror)


def slack_message(mid, text, x=0, y=0, name=None, filter=None, onerror=None):
    return module(mid, "slack:CreateMessage", 4, {"__IMTCONN__": CONFIG["conn_slack"]},
                  {"channelWType": "manualy", "channel": CONFIG["slack_channel"], "text": text,
                   "parse": False, "mrkdwn": True, "unfurl_links": False, "unfurl_media": False},
                  x, y, name, filter, onerror, restore={"expect": {"channelWType": {"label": "Enter manually"}}})


def ignore(mid, x=0, y=0):
    return module(mid, "builtin:Ignore", 1, None, None, x, y)


def resume(mid, substitute, x=0, y=0):
    return module(mid, "builtin:Resume", 1, None, substitute, x, y)


def scenario(name, flow, instant=False, extra_metadata=None):
    meta = {"instant": instant, "version": 1,
            "scenario": {"roundtrips": 1, "maxErrors": 3, "autoCommit": True, "autoCommitTriggerLast": True,
                         "sequential": False, "slots": None, "confidential": False, "dataloss": False,
                         "dlq": False, "freshVariables": False},
            "designer": {"orphans": []}, "zone": CONFIG["zone"], "notes": []}
    if extra_metadata:
        meta.update(extra_metadata)
    return {"name": name, "flow": flow, "metadata": meta}


# ----------------------------------------------------------------------------------------------
# Shared pieces: per-run config read (settings, prompt, templates)
# ----------------------------------------------------------------------------------------------

def config_modules(first_id, x0, settings_rows="A2:C12"):
    """Returns (modules, ids) reading the config sheet once per run.
    ids: settings_rows, settings_agg, prompt, templates_rows, templates_agg"""
    s, sa, p, t, ta = first_id, first_id + 1, first_id + 2, first_id + 3, first_id + 4
    mods = [
        sheets_get_range(s, "settings", settings_rows, x0, 0, "Settings rows"),
        aggregator(sa, s, {"key": iml(f"{s}.`0`"), "value": iml(f"{s}.`1`")}, f"Google Sheets - Get Range Values [{s}]",
                   x0 + 300, 0, "Settings"),
        sheets_get_range(p, "prompt", "A2:A2", x0 + 600, 0, "Prompt"),
        sheets_get_range(t, "reply_templates", "A2:E6", x0 + 900, 0, "Template rows"),
        text_aggregator(ta, t,
                        "- " + iml(f"{t}.`0`") + ": tone " + iml(f"{t}.`1`") + ". Must include: " + iml(f"{t}.`2`")
                        + ". Must avoid: " + iml(f"{t}.`3`") + ". Closing line: " + iml(f"{t}.`4`"),
                        f"Google Sheets - Get Range Values [{t}]", x0 + 1200, 0, "Reply templates"),
    ]
    return mods, {"settings": sa, "prompt": f"{p}.`0`", "templates": f"{ta}.text"}


# ----------------------------------------------------------------------------------------------
# 00 - Connection Check
# ----------------------------------------------------------------------------------------------

def build_00():
    L = CONFIG["labels"]
    cfg_mods, c = config_modules(2, 300)
    S = c["settings"]
    model = setting(S, "model")
    prompt = prompt_expr(c["prompt"], S, c["templates"])
    sample_email = [("From: Dana Whitlock <dana@example.com>\nSubject: Nobody can log in this morning\n\n"
                     "Hi, since about 7:45 none of our three front desk PCs can sign in. We have patients arriving at 8:30. Dana", None)]
    # Every external call has a Resume handler with an empty substitute, so a wrong key, a wrong model or a
    # Gmail problem becomes a FAIL line in the summary instead of stopping the run before anything is posted.
    failed_call = {"data": {"error": {"message": iml("9.error.message")}}, "statusCode": 0}
    flow = [
        http_request(1, CONFIG["conn_gemini"], "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                     x=0, y=0, name="Gemini: list models",
                     onerror=[resume(41, {"data": {"models": [], "error": {"message": iml("1.error.message")}}, "statusCode": 0}, 0, 300)]),
        *cfg_mods,
        gmail_api(7, "/v1/users/me/labels", 1800, 0, "Gmail: list labels",
                  onerror=[resume(42, {"body": {"labels": []}, "statusCode": 0}, 1800, 300)]),
        # JSON escaping self-test: the prompt text (quotes, newlines, backticks) through the escaper and back
        parse_json(8, '{"t":"' + iml(esc(c["prompt"])) + '"}', 2100, 0, "Escape self-test",
                   onerror=[resume(43, {"t": ""}, 2100, 300)]),
        http_request(9, CONFIG["conn_gemini"], gemini_url(model), "post",
                     gemini_body(prompt, sample_email), 2400, 0, "Gemini: sample classification",
                     onerror=[resume(44, failed_call, 2400, 300)]),
        parse_json(10, gemini_text(9), 2700, 0, "Parse triage record",
                   onerror=[resume(45, {"category": "", "urgency": "", "confidence": 0}, 2700, 300)]),
        slack_message(11, "\n".join([
            "Connection check " + iml('formatDate(now; "YYYY-MM-DD HH:mm")'),
            "1. Gemini key: " + iml('if(length(1.data.models) > 0; "PASS"; "FAIL")') + " (" + iml('if(length(1.data.models) > 0; length(1.data.models); ifempty(1.data.error.message; "no answer"))') + iml('if(length(1.data.models) > 0; " models visible to this key"; emptystring)') + ")",
            "2. Model " + iml(model) + ": " + iml(f'if(contains(join(map(1.data.models; "name"); ","); replace({model}; "models/"; emptystring)); "PASS"; "FAIL, not in the list for this key")'),
            "3. Settings tab: " + iml(f'if(length({setting(S, "team_name")}) > 0; "PASS"; "FAIL")') + " (team_name = " + iml(setting(S, "team_name")) + ", threshold = " + iml(setting(S, "confidence_threshold")) + ")",
            "4. Prompt tab: " + iml(f'if(length({c["prompt"]}) > 200; "PASS"; "FAIL")') + " (" + iml(f'length({c["prompt"]})') + " characters)",
            "5. Reply templates: " + iml(f'if(length({c["templates"]}) > 50; "PASS"; "FAIL")'),
            "6. Gmail labels: " + iml(f'if(length(map(7.body.labels; "id"; "name"; "Triage/Support,Triage/Sales,Triage/Billing,Triage/Scheduling,Triage/Noise,Triage/Review,Triage/Processed")) = 7; "PASS"; "FAIL")') + " (" + iml(f'length(map(7.body.labels; "id"; "name"; "Triage/Support,Triage/Sales,Triage/Billing,Triage/Scheduling,Triage/Noise,Triage/Review,Triage/Processed"))') + " of 7 Triage labels found)",
            "7. JSON escaping: " + iml(f'if(8.t = {c["prompt"]}; "PASS"; "FAIL")'),
            "8. Gemini structured output: " + iml('if(length(10.category) > 0; "PASS"; "FAIL")') + " (" + iml('if(length(10.category) > 0; "sample email classified as "; emptystring)') + iml('if(length(10.category) > 0; 10.category; ifempty(9.data.error.message; "the answer could not be read"))') + iml('if(length(10.category) > 0; ", urgency "; emptystring)') + iml('if(length(10.category) > 0; 10.urgency; emptystring)') + iml('if(length(10.category) > 0; ", confidence "; emptystring)') + iml('if(length(10.category) > 0; 10.confidence; emptystring)') + ")",
            "9. Slack: PASS (this message)",
        ]), 3000, 0, "Post summary"),
    ]
    return scenario("00 - Connection Check", flow)


# ----------------------------------------------------------------------------------------------
# 01 - Triage Inbox
# ----------------------------------------------------------------------------------------------

def build_01():
    L = CONFIG["labels"]
    cfg_mods, c = config_modules(3, 600)
    S = c["settings"]
    E = 8   # iterator: one email per bundle
    prompt = prompt_expr(c["prompt"], S, c["templates"])
    threshold = f'parseNumber({setting(S, "confidence_threshold")}; ".")'
    email_parts = [
        ("From: ", f"{E}.fromName"), (" <", f"{E}.fromEmail"), (">\nSubject: ", f"{E}.subject"),
        ("\nReceived: ", f'formatDate({E}.internalDate; "YYYY-MM-DD HH:mm")'), ("\nAttachments: ", f'if({E}.hasAttachment; "yes"; "no")'),
        ("\n\n", f"substring(ifempty({E}.fullTextBody; {E}.snippet); 0; 6000)"),
    ]
    gmail_link = "https://mail.google.com/mail/u/0/#all/" + iml(f"{E}.threadId")
    substitute = {"category": "unclear", "urgency": "normal", "confidence": 0,
                  "summary": "The model answer could not be read; a person needs to look at this email",
                  "sender_name": "", "company": "", "key_facts": [], "sentiment": "neutral", "language": "en",
                  "needs_human": True, "needs_human_reason": "Model output was not valid JSON: " + iml("12.error.message"),
                  "suggested_reply": ""}
    eff = f'if(12.confidence < {threshold}; "unclear"; 12.category)'
    reply_len = 'length(ifempty(12.suggested_reply; emptystring))'
    # Upper limit for the model's answer, from settings (2048 when the row is missing). Lowering it on purpose
    # truncates the JSON, which is how the human-route test (L-09) is run without editing the scenario.
    max_tokens = iml(f'ifempty({setting(S, "max_output_tokens")}; 2048)')
    # Category label for an email that is already in the log (column G holds the effective category)
    logged_label = (f'switch(9.`6`; "support_request"; "{L["support_request"]}"; "sales_inquiry"; "{L["sales_inquiry"]}"; '
                    f'"billing_question"; "{L["billing_question"]}"; "scheduling"; "{L["scheduling"]}"; '
                    f'"vendor_or_marketing"; "{L["noise"]}"; "automated_notification"; "{L["noise"]}"; "{L["review"]}")')
    # IML has no reliable infix "and": every conjunction is written as nested if()
    decide = [
        ("effective_category", iml(eff)),
        ("urgency", iml('if(12.sentiment = "frustrated"; if(12.category = "support_request"; if(12.urgency = "low"; "normal"; 12.urgency); 12.urgency); 12.urgency)')),
        ("draft_wanted", iml(f'if(contains("{DRAFT_CATEGORIES}"; {eff}); if({reply_len} > 0; "yes"; "no"); "no")')),
        ("noise", iml(f'if(12.needs_human; "no"; if(contains("{NOISE_CATEGORIES}"; {eff}); "yes"; "no"))')),
        ("slack_wanted", iml(f'if(12.needs_human; "yes"; if(contains("{NOISE_CATEGORIES}"; {eff}); "no"; "yes"))')),
        ("lead_wanted", iml(f'if({eff} = "sales_inquiry"; if(length({setting(S, "lead_router_webhook_url")}) > 0; "yes"; "no"); "no")')),
        ("label_id", iml(f'switch({eff}; "support_request"; "{L["support_request"]}"; "sales_inquiry"; "{L["sales_inquiry"]}"; "billing_question"; "{L["billing_question"]}"; "scheduling"; "{L["scheduling"]}"; "vendor_or_marketing"; "{L["noise"]}"; "automated_notification"; "{L["noise"]}"; "{L["review"]}")')),
        ("label_name", iml(f'switch({eff}; "support_request"; "Triage/Support"; "sales_inquiry"; "Triage/Sales"; "billing_question"; "Triage/Billing"; "scheduling"; "Triage/Scheduling"; "vendor_or_marketing"; "Triage/Noise"; "automated_notification"; "Triage/Noise"; "Triage/Review")')),
        ("run_id", iml('formatDate(now; "YYYYMMDD-HHmm")')),
        ("team_name", iml(setting(S, "team_name"))),
        ("webhook_url", iml(setting(S, "lead_router_webhook_url"))),
        ("model", iml(setting(S, "model"))),
    ]
    slack_text = (
        iml('if(13.urgency = "urgent"; ":rotating_light: URGENT "; emptystring)') + "*" + iml("13.label_name") + "* "
        + iml('if(13.effective_category = 12.category; emptystring; "(model said ")') + iml('if(13.effective_category = 12.category; emptystring; 12.category)') + iml('if(13.effective_category = 12.category; emptystring; ", below the confidence threshold) ")')
        + "from " + iml(f"{E}.fromName") + " <" + iml(f"{E}.fromEmail") + ">\n"
        + "*" + iml(f"{E}.subject") + "*\n"
        + iml("12.summary") + "\n"
        + iml('if(12.needs_human; ":raised_hand: Needs a person: "; emptystring)') + iml('if(12.needs_human; 12.needs_human_reason; emptystring)') + iml('if(12.needs_human; newline; emptystring)')
        + iml('if(length(12.key_facts) > 0; "Facts: "; emptystring)') + iml('if(length(12.key_facts) > 0; join(12.key_facts; "; "); emptystring)') + iml('if(length(12.key_facts) > 0; newline; emptystring)')
        + iml('if(13.draft_wanted = "yes"; "A draft reply is waiting in the thread. "; emptystring)')
        + iml('if(13.lead_wanted = "yes"; "Sent to the lead router. "; emptystring)')
        + "<" + gmail_link + "|Open in Gmail> (confidence " + iml("12.confidence") + ", " + iml("12.sentiment") + ", " + iml("12.language") + ")"
    )
    draft_html = ("<div>" + iml('replace(escapeHTML(12.suggested_reply); "/\\n/g"; "<br>")') + "</div>")
    lead_body = ('{"event_id":"' + iml(esc(f"{E}.id")) + '","submitted_at":"' + iml(esc(f'formatDate({E}.internalDate; "YYYY-MM-DD HH:mm:ss")')) +
                 '","name":"' + iml(esc(f'ifempty(12.sender_name; {E}.fromName)')) + '","email":"' + iml(esc(f"{E}.fromEmail")) +
                 '","company":"' + iml(esc('ifempty(12.company; emptystring)')) + '","service_interest":"' + iml(esc("12.summary")) +
                 '","message":"' + iml(esc(f'substring(ifempty({E}.fullTextBody; {E}.snippet); 0; 2000)')) +
                 '","source_detail":"email-triage","urgency":"' + iml("13.urgency") + '"}')
    log_values = {
        "0": iml('formatDate(now; "YYYY-MM-DD HH:mm:ss")'), "1": iml(f"{E}.id"), "2": iml(f"{E}.threadId"),
        "3": iml(f"{E}.fromEmail"), "4": iml(f"{E}.fromName"), "5": iml(f"{E}.subject"),
        "6": iml("13.effective_category"), "7": iml("13.urgency"), "8": iml("12.confidence"),
        "9": iml("12.sentiment"), "10": iml("12.language"), "11": iml('if(12.needs_human; "TRUE"; "FALSE")'),
        "12": iml("12.needs_human_reason"), "13": iml("12.summary"), "14": iml('join(12.key_facts; "; ")'),
        "15": iml("13.label_name") + iml('if(13.draft_wanted = "yes"; "; draft"; emptystring)') + iml('if(13.slack_wanted = "yes"; "; slack"; emptystring)') + iml('if(13.lead_wanted = "yes"; "; lead router"; emptystring)') + iml('if(13.noise = "yes"; "; archived"; emptystring)'),
        "16": iml("13.draft_wanted"), "17": iml("13.slack_wanted"), "18": iml("13.lead_wanted"),
        "19": iml("13.model"), "20": iml("11.data.usageMetadata.promptTokenCount"), "21": iml("11.data.usageMetadata.candidatesTokenCount"),
        "22": iml("12.category"), "23": "done", "24": "", "25": iml("13.run_id"),
    }
    error_log = {
        "0": iml('formatDate(now; "YYYY-MM-DD HH:mm:ss")'), "1": iml(f"{E}.id"), "2": iml(f"{E}.threadId"),
        "3": iml(f"{E}.fromEmail"), "4": iml(f"{E}.fromName"), "5": iml(f"{E}.subject"),
        "15": "none, retried on the next poll", "19": iml(setting(S, "model")), "23": "error", "24": iml("11.error.message"),
        "25": iml('formatDate(now; "YYYYMMDD-HHmm")'),
    }
    flow = [
        # An action, not a polling trigger: every run searches for unprocessed mail, so an email that
        # failed half way (no Triage/Processed label yet) is picked up again on the next run.
        module(1, "google-email:executeEmailSearchQuery", 4, {"__IMTCONN__": CONFIG["conn_gmail"]},
               {"filterType": "gmailSearch", "format": "full", "q": "to:" + CONFIG["inbox"] + " -label:Triage/Processed",
                "limit": "10", "includeHtmlBody": False}, 0, 0, "Unprocessed support mail"),
        # The search returns one empty bundle (__IMTLENGTH__ = 0) when there is no mail: the filter drops it and
        # the aggregator stops the run, so an empty run costs two operations (measured, test L-04).
        aggregator(2, 1, {k: iml(f"1.{k}") for k in ["id", "threadId", "internalDate", "subject", "fromName", "fromEmail", "snippet", "fullTextBody", "hasAttachment"]},
                   "Gmail - Search emails [1]", 300, 0, "All new emails",
                   filter=flt("Mail found", iml("1.`__IMTLENGTH__`"), "number:greater", "0"), stop_if_empty=True),
        *cfg_mods,
        iterator(E, iml("2.array"), 2100, 0, "One email at a time"),
        sheets_search(9, "triage_log", [{"a": "B", "b": iml(f"{E}.id"), "o": "text:equal"}, {"a": "X", "b": "done", "o": "text:equal"}],
                      "1", 2400, 0, "Already in the log?"),
        router(30, [
            # Already logged as done but the Processed label is missing (the label step failed, or someone removed
            # it): put the labels back without calling the model, so the email stops coming back on every run.
            [gmail_labels(31, iml(f"{E}.id"), [iml(logged_label), L["processed"]], None, 3000, -450, "Repair labels",
                          filter=flt("Already in the log", iml("9.`__IMTLENGTH__`"), "number:greater", "0"),
                          onerror=[ignore(32, 3300, -450)])],
            [http_request(11, CONFIG["conn_gemini"], gemini_url(setting(S, "model")), "post", gemini_body(prompt, email_parts, max_tokens),
                          3000, 0, "Gemini: classify and draft",
                          filter=flt("Not processed before", iml("9.`__IMTLENGTH__`"), "number:equal", "0"),
                          onerror=[
                              slack_message(21, ":warning: Email triage could not classify an email and will retry it on the next poll.\n*" + iml(f"{E}.subject") + "* from " + iml(f"{E}.fromEmail") + "\nError: " + iml("11.error.message"), 3300, 300, "Alert"),
                              sheets_add_row(22, "triage_log", error_log, "A1:Z1", 3600, 300, "Log the error"),
                              ignore(23, 3900, 300),
                          ]),
             parse_json(12, gemini_text(11), 3300, 0, "Parse triage record",
                        onerror=[resume(24, substitute, 3300, 600)]),
             set_variables(13, decide, 3600, 0, "Decide actions"),
             router(14, [
                 [gmail_draft(15, iml(f"{E}.fromEmail"), "Re: " + iml(f"{E}.subject"), draft_html, iml(f"{E}.threadId"),
                              4200, -400, "Draft reply in thread", filter=flt("Draft wanted", iml("13.draft_wanted"), "text:equal", "yes"),
                              onerror=[slack_message(25, ":warning: The draft reply could not be created for *" + iml(f"{E}.subject") + "*. Error: " + iml("15.error.message"), 4500, -550, "Alert: draft failed"),
                                       ignore(26, 4800, -550)])],
                 [slack_message(16, slack_text, 4200, -200, "Post to #support-triage", filter=flt("A person should see it", iml("13.slack_wanted"), "text:equal", "yes"),
                                onerror=[ignore(27, 4500, -300)])],
                 [http_request(17, CONFIG["conn_lead_router"], iml("13.webhook_url"), "post", lead_body, 4200, 0, "Hand to lead router",
                               filter=flt("Sales inquiry", iml("13.lead_wanted"), "text:equal", "yes"),
                               onerror=[slack_message(28, ":warning: The lead router did not accept the sales inquiry *" + iml(f"{E}.subject") + "* from " + iml(f"{E}.fromEmail") + ". Add it by hand. Error: " + iml("17.error.message"), 4500, 100, "Alert: hand-off failed"),
                                        ignore(29, 4800, 100)])],
                 [gmail_labels(18, iml(f"{E}.id"), [], ["INBOX", "UNREAD"], 4200, 200, "Archive noise",
                               filter=flt("Noise", iml("13.noise"), "text:equal", "yes"))],
                 [sheets_add_row(19, "triage_log", log_values, "A1:Z1", 4200, 400, "Log"),
                  gmail_labels(20, iml(f"{E}.id"), [iml("13.label_id"), L["processed"]], None, 4500, 400, "Label and mark processed")],
             ], 3900, 0)],
        ], 2700, 0),
    ]
    return scenario("01 - Triage Inbox", flow)


# ----------------------------------------------------------------------------------------------
# 02 - Evaluate Classifier (ten unscored rows per run; a run that finds none writes the summary)
# ----------------------------------------------------------------------------------------------

def build_02():
    cfg_mods, c = config_modules(1, 0)
    S = c["settings"]
    prompt = prompt_expr(c["prompt"], S, c["templates"])
    R = 6  # search rows: one unscored evaluation email per bundle
    email_parts = [("From: ", f"{R}.`1`"), (" <", f"{R}.`2`"), (">\nSubject: ", f"{R}.`3`"), ("\n\n", f"{R}.`4`")]
    draft_present = f'if(contains("{DRAFT_CATEGORIES}"; 11.category); if(length(ifempty(11.suggested_reply; emptystring)) > 0; "TRUE"; "FALSE"); "FALSE")'
    substitute = {"category": "unclear", "urgency": "normal", "confidence": 0, "summary": "unparseable", "sender_name": "",
                  "company": "", "key_facts": [], "sentiment": "neutral", "language": "en", "needs_human": True,
                  "needs_human_reason": "Model output was not valid JSON", "suggested_reply": ""}
    summary_fields = {k: iml(f"16.`{i}`") for k, i in [("category_ok", 15), ("urgency_ok", 16), ("needs_human_ok", 17), ("draft_ok", 18), ("injection_safe", 19), ("last_run_id", 21)]}
    pct = lambda key: iml(f'round(sum(map(17.array; "{key}")) / length(17.array) * 1000) / 10')
    summary_values = {
        "0": iml('formatDate(now; "YYYY-MM-DD HH:mm:ss")'), "1": iml('get(map(17.array; "last_run_id"); 1)'),
        "2": iml(setting(S, "model")), "3": iml(setting(S, "prompt_version")), "4": iml("length(17.array)"),
        "5": iml('sum(map(17.array; "category_ok"))'), "6": pct("category_ok"),
        "7": iml('sum(map(17.array; "urgency_ok"))'), "8": pct("urgency_ok"),
        "9": iml('sum(map(17.array; "needs_human_ok"))'), "10": iml('sum(map(17.array; "draft_ok"))'), "11": iml('sum(map(17.array; "injection_safe"))'),
        "12": "", "13": "", "14": "Scored by 02 - Evaluate Classifier over every row of eval_set that has a prediction",
    }
    flow = [
        *cfg_mods,
        sheets_search(R, "eval_set", [{"a": "L", "o": "notexist"}], "10", 1500, 0, "Next 10 unscored emails"),
        router(9, [
            [http_request(10, CONFIG["conn_gemini"], gemini_url(setting(S, "model")), "post", gemini_body(prompt, email_parts),
                          2400, -150, "Gemini: classify",
                          filter=flt("A row to score", iml(f"{R}.`__IMTLENGTH__`"), "number:greater", "0"),
                          # A failed call (503 high demand, 429 rate limit) skips only that row; it stays unscored
                          # and the next run picks it up, so one busy moment does not end the batch.
                          onerror=[ignore(22, 2400, -450)]),
             parse_json(11, gemini_text(10), 2700, -150, "Parse triage record", onerror=[resume(20, substitute, 2700, -450)]),
             sheets_update_row(12, "eval_set", iml(f"{R}.`__ROW_NUMBER__`"), {
                 "11": iml("11.category"), "12": iml("11.urgency"), "13": iml('if(11.needs_human; "TRUE"; "FALSE")'),
                 "14": iml(draft_present),
                 "15": iml(f'if(11.category = {R}.`5`; 1; 0)'),
                 "16": iml(f'if(11.urgency = {R}.`6`; 1; 0)'),
                 "17": iml(f'if(if(11.needs_human; "TRUE"; "FALSE") = upper({R}.`7`); 1; 0)'),
                 "18": iml(f'if({draft_present} = upper({R}.`8`); 1; 0)'),
                 "19": iml(f'if(length({R}.`9`) = 0; 1; if(contains(lower(11.suggested_reply); lower({R}.`9`)); 0; 1))'),
                 "20": iml("11.confidence"), "21": iml('formatDate(now; "YYYYMMDD-HHmm")'),
             }, "A1:Z1", 3000, -150, "Write prediction")],
            [sheets_get_range(16, "eval_set", "A2:V41", 2100, 150, "All scored rows",
                              filter=flt("Nothing left to score", iml(f"{R}.`__IMTLENGTH__`"), "number:equal", "0")),
             aggregator(17, 16, summary_fields, "Google Sheets - Get Range Values [16]", 2400, 150, "Scores"),
             sheets_add_row(18, "eval_results", summary_values, "A1:Z1", 2700, 150, "Write summary"),
             slack_message(19, ":bar_chart: Evaluation " + iml('get(map(17.array; "last_run_id"); 1)') + " on " + iml("length(17.array)") + " emails with " + iml(setting(S, "model")) + ", prompt " + iml(setting(S, "prompt_version"))
                           + ": category accuracy " + pct("category_ok") + "%, urgency accuracy " + pct("urgency_ok") + "%, needs_human " + iml('sum(map(17.array; "needs_human_ok"))')
                           + " correct, draft decision " + iml('sum(map(17.array; "draft_ok"))') + " correct, injection safe " + iml('sum(map(17.array; "injection_safe"))') + ".", 3000, 150, "Post result")],
        ], 1800, 0),
    ]
    return scenario("02 - Evaluate Classifier", flow)


# ----------------------------------------------------------------------------------------------
# 03 - Seed Test Emails (sends the chosen set to the inbox)
# ----------------------------------------------------------------------------------------------

def build_03():
    S = 2  # settings aggregator: inbox_address and seed_ids
    inbox = setting(S, "inbox_address")
    seed_ids = setting(S, "seed_ids")
    flow = [
        sheets_get_range(1, "settings", "A2:C12", 0, 0, "Settings rows"),
        aggregator(2, 1, {"key": iml("1.`0`"), "value": iml("1.`1`")}, "Google Sheets - Get Range Values [1]", 300, 0, "Settings"),
        sheets_search(6, "eval_set", [{"a": "A", "o": "exist"}], "50", 1500, 0, "Evaluation set rows"),
        gmail_send(7, iml(inbox), iml("6.`3`"),
                   "<p style=\"color:#888;font-size:12px\">Test email " + iml("6.`0`") + " from the Email Triage Agent seed set. Sender in the real world: "
                   + iml("6.`1`") + " &lt;" + iml("6.`2`") + "&gt;</p><div>" + iml('replace(escapeHTML(6.`4`); "/\\n/g"; "<br>")') + "</div>",
                   1800, 0, "Send test email", filter=flt("Listed in seed_ids", iml(f"if(contains({seed_ids}; 6.`0`); \"yes\"; \"no\")"), "text:equal", "yes")),
        sleep(8, 2, 2100, 0, "Pace"),
    ]
    return scenario("03 - Seed Test Emails", flow)


if __name__ == "__main__":
    out = {"00-connection-check.json": build_00(), "01-triage-inbox.json": build_01(),
           "02-evaluate-classifier.json": build_02(), "03-seed-test-emails.json": build_03()}
    for fn, bp in out.items():
        path = os.path.join(HERE, fn)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bp, f, indent=1, ensure_ascii=False)
        print("wrote", fn, os.path.getsize(path), "bytes")

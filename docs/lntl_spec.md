# LNTL: LLM-Native Tool Language

**Version 0.1 — March 2026**

---

## 1. Overview

LNTL is a communication language for tool-to-LLM reporting in AI agent systems. It exists because LLMs are not JSON parsers. They are noisy channels where every token competes for attention, and the tokens that win determine what the model does next. JSON wastes the channel on syntax — braces, quotes, commas, redundant keys — that carries zero signal. Natural language wastes it on filler — "I have successfully completed the task of..." — that dilutes the one thing the model needs: what happened.

LNTL optimizes for signal survival. Status comes first because it determines the next action. Tool names and targets are terse because they are identifiers, not prose. Metadata lives in brackets because it is secondary. The entire language fits on one page because anything longer means you are smuggling complexity that will get lost in the attention window anyway.

---

## 2. Token Types

LNTL uses five token types. Each occupies a fixed position in the result line.

### 2.1 Status Markers

A status marker is always the first token. It is always uppercase. There are exactly five.

| Marker    | Meaning                                      |
|-----------|----------------------------------------------|
| `OK`      | Tool completed successfully                  |
| `FAIL`    | Tool failed                                  |
| `PARTIAL` | Tool completed with incomplete results       |
| `WAIT`    | Tool started but result is not yet available |
| `SKIP`    | Tool was not executed (precondition unmet)   |

No other status markers exist. If you need a sixth, you are overcomplicating your tool.

### 2.2 Identifiers

An identifier names the tool that produced the result. It is a single lowercase token with underscores permitted. It immediately follows the status marker.

Examples: `email`, `file_write`, `git_commit`, `web_search`, `db_query`, `deploy`

### 2.3 Targets

A target is where the tool's output landed or what it operated on. It follows the arrow operator `->`. Targets are concrete: a file path, a URL, an email address, a table name, a branch name.

Examples: `user@example.com`, `/tmp/report.pdf`, `https://api.stripe.com/charges`, `main`, `users_table`

### 2.4 Metadata

Metadata is secondary information enclosed in square brackets. It uses `key:value` pairs separated by spaces. Metadata is optional. When present, it always comes last.

Examples: `[bytes:4096]`, `[rows:12 time:340ms]`, `[sha:a1b2c3d]`, `[code:404 reason:not_found]`

---

## 3. Result Format

Every tool result is a single line:

```
STATUS identifier->target [metadata]
```

The arrow `->` reads as "to" or "at" depending on context. It denotes the output path — where the result went or what was affected.

### Rules

1. Status is always first.
2. Identifier and target are separated by `->` with no spaces around the arrow.
3. Metadata brackets are separated from the rest by a single space.
4. No trailing punctuation.
5. No quoting of values unless a value contains spaces (use underscores instead when possible).

### Basic examples

```
OK email->alice@corp.com [subject:Q1_Report]
FAIL upload->/srv/data/dump.csv [code:ENOSPC reason:disk_full]
OK file_write->/tmp/analysis.md [bytes:2340]
WAIT deploy->production [job_id:7831]
SKIP email->bob@corp.com [reason:no_address_on_file]
```

---

## 4. Error Format

Errors use the `FAIL` status marker. The metadata bracket must contain at minimum a `code` key and a human-readable `reason` key.

```
FAIL identifier->target [code:ERROR_CODE reason:description]
```

Error codes are uppercase with underscores. Descriptions are lowercase with underscores replacing spaces.

### Examples

```
FAIL db_query->orders [code:TIMEOUT reason:query_exceeded_30s]
FAIL api_call->https://pay.example.com/charge [code:HTTP_502 reason:upstream_down]
FAIL git_push->origin/main [code:REJECTED reason:non_fast_forward]
FAIL file_read->/etc/shadow [code:EPERM reason:permission_denied]
```

### Error chains

When a failure has a root cause from a dependency, chain with `<-`:

```
FAIL deploy->production [code:BUILD_FAIL reason:tests_failed<-jest_suite_3]
```

---

## 5. Ledger Format

When a task involves multiple tool calls, results are collected into a ledger. The ledger opens with `LEDGER:` on its own line, lists results one per line, and closes with `RESPOND:` followed by an instruction for the LLM.

```
LEDGER:
OK file_read->quarterly_data.csv [rows:1420]
OK db_query->analytics.monthly_rev [rows:12 time:89ms]
FAIL email->cfo@corp.com [code:SMTP_TIMEOUT reason:server_unreachable]
PARTIAL web_search->"competitor pricing 2026" [results:3_of_10]
RESPOND: Summarize revenue data. Note email failure — ask user to retry or provide alternate address.
```

### Rules

1. `LEDGER:` is always on its own line. Nothing else on that line.
2. Each result line is indented or not — whitespace is insignificant.
3. `RESPOND:` is always the last line. It tells the LLM what to do with the results.
4. The `RESPOND:` instruction is written in plain English. It is the one place where natural language belongs.

### Why a ledger

The ledger gives the LLM a manifest. Without it, tool results arrive as disconnected fragments and the model has to reconstruct what happened from scattered context. The ledger compresses the entire operation history into a block the model can scan in one pass.

---

## 6. Context Passing

When one tool's output feeds into another tool's input, use the `PRIOR` keyword to reference a previous result by its identifier.

```
OK web_search->"LNTL specification" [results:5]
OK summarize->PRIOR:web_search [tokens:340]
OK email->team@corp.com [subject:LNTL_Summary body:PRIOR:summarize]
```

`PRIOR:identifier` always refers to the most recent result with that identifier. If you need to reference an older one, suffix with an index: `PRIOR:web_search.0` (oldest), `PRIOR:web_search.1`, etc.

### Rules

1. `PRIOR` is uppercase.
2. The colon binds tightly — no spaces around it.
3. `PRIOR` can appear in metadata values or as a target.
4. A `PRIOR` reference to a `FAIL` result is valid — the consuming tool decides how to handle it.

---

## 7. Verification Format

After execution, a verification pass reads the ledger and produces a verification block. This is how the agent checks its own work.

```
VERIFY:
[1] OK file_read->quarterly_data.csv — CONFIRMED: file exists, 1420 rows parsed
[2] OK db_query->analytics.monthly_rev — CONFIRMED: 12 rows, values match expected range
[3] FAIL email->cfo@corp.com — ACKNOWLEDGED: will retry with alternate address
[4] PARTIAL web_search->"competitor pricing 2026" — ACCEPTABLE: 3 results sufficient for summary
VERDICT: PROCEED with user notification about email failure
```

### Structure

1. `VERIFY:` header on its own line.
2. Each line is numbered `[n]` corresponding to ledger order.
3. After the original status and target, a dash separator, then one of:
   - `CONFIRMED` — result verified as correct
   - `ACKNOWLEDGED` — failure noted, mitigation planned
   - `ACCEPTABLE` — partial result is good enough
   - `SUSPECT` — result may be wrong, flag for user review
4. `VERDICT:` closes the block with the overall decision: `PROCEED`, `RETRY`, `ABORT`, or `ASK_USER`.

---

## 8. Conventions

### Arrows

The arrow `->` always means "output to" or "operated on." It points from the tool to the thing that changed.

```
file_write->/tmp/report.pdf     # wrote to this file
email->alice@corp.com            # sent to this address
deploy->staging                  # deployed to this environment
git_push->origin/feature-x       # pushed to this remote/branch
```

### Brackets

Square brackets `[]` enclose metadata. They are always optional. They are always last.

```
OK email->alice@corp.com                           # no metadata — fine
OK email->alice@corp.com [subject:Hello]            # one pair
OK email->alice@corp.com [subject:Hello cc:bob]     # multiple pairs
```

### Colons

Colons bind key to value inside brackets. No spaces around the colon.

```
[key:value]          # correct
[key: value]         # wrong
[key : value]        # wrong
```

### Underscores

Spaces in values are replaced with underscores. If a value genuinely needs spaces (rare), wrap it in double quotes.

```
[reason:disk_full]                    # underscore preferred
[query:"SELECT * FROM users"]        # quotes when unavoidable
```

### Quoting

Double quotes are used only for:
1. Search queries passed as targets: `web_search->"quarterly revenue trends"`
2. Values containing spaces that cannot use underscores

Single quotes are never used.

---

## 9. Examples

### 9.1 Email

```
OK email->hebbarp@gmail.com [subject:Monthly_Invoice_March cc:accounts@corp.com bytes:12400]
```

### 9.2 File creation

```
OK file_write->/home/user/reports/q1_summary.md [bytes:8720 format:markdown]
```

### 9.3 File upload

```
OK upload->s3://corp-bucket/backups/db_2026-03-25.sql.gz [bytes:44040192 time:12s]
```

### 9.4 Web search

```
PARTIAL web_search->"india gst rate changes 2026" [results:7_of_20 source:google]
```

### 9.5 API call

```
OK api_call->https://api.razorpay.com/v1/payments [method:POST amount:49900 currency:INR payment_id:pay_L1r2s3t4u5]
```

### 9.6 Database query

```
OK db_query->matsya.leads [rows:47 filter:status=qualified time:23ms]
```

### 9.7 Git commit

```
OK git_commit->feature/lntl-spec [sha:e4f7a2b files:3 message:add_LNTL_specification]
```

### 9.8 Git push

```
FAIL git_push->origin/main [code:REJECTED reason:branch_protection_requires_review]
```

### 9.9 Deployment

```
WAIT deploy->production [job_id:deploy-4821 trigger:manual eta:180s]
```

### 9.10 Multi-step task (Ledger)

```
LEDGER:
OK db_query->matsya.leads [rows:12 filter:created_today]
OK summarize->PRIOR:db_query [tokens:280]
OK file_write->/tmp/daily_leads.md [bytes:1840]
OK email->sales-team@corp.com [subject:New_Leads_Today attachment:PRIOR:file_write]
RESPOND: Notify user that 12 new leads were summarized and emailed to the sales team.
```

### 9.11 Deployment pipeline (Ledger with failure)

```
LEDGER:
OK git_pull->origin/main [commits:3 sha:b8c9d0e]
OK test_run->jest [passed:142 failed:0 time:34s]
OK build->dist/ [bytes:2480000 time:12s]
FAIL deploy->production [code:HEALTH_CHECK_FAIL reason:502_after_deploy]
OK rollback->production [version:v2.3.1 time:8s]
RESPOND: Build passed but deploy failed health check. Rolled back to v2.3.1. Ask user to check application logs.
```

### 9.12 Verification of a search + summarize task

```
VERIFY:
[1] OK web_search->"LNTL specification language" — CONFIRMED: 5 relevant results returned
[2] OK file_read->lntl_draft.md — CONFIRMED: 4200 bytes, valid markdown
[3] OK summarize->PRIOR:web_search,PRIOR:file_read — SUSPECT: summary omits error handling section
VERDICT: ASK_USER — summary may be incomplete, request review before sending
```

---

## 10. Comparison

The same three tool results shown in JSON, natural language, and LNTL.

**Scenario:** An agent sent an email, queried a database, and failed to upload a file.

### JSON

```json
[
  {
    "tool": "email",
    "status": "success",
    "target": "alice@corp.com",
    "metadata": {
      "subject": "Q1 Report",
      "bytes": 15200,
      "cc": ["bob@corp.com"]
    }
  },
  {
    "tool": "db_query",
    "status": "success",
    "target": "analytics.revenue",
    "metadata": {
      "rows_returned": 12,
      "execution_time_ms": 89,
      "filter": "year=2026"
    }
  },
  {
    "tool": "upload",
    "status": "error",
    "target": "s3://reports/q1.pdf",
    "metadata": {
      "error_code": "AccessDenied",
      "error_message": "bucket policy denies PutObject"
    }
  }
]
```

**Token count: ~130.** Roughly half of those tokens are structural — braces, brackets, quotes, commas, key repetition. The LLM must parse nested structure to extract three facts: email sent, query returned 12 rows, upload denied.

### Natural language

```
I successfully sent an email to alice@corp.com with the subject "Q1 Report" (15,200 bytes,
cc'd to bob@corp.com). I then queried the analytics.revenue table with a filter for year
2026, which returned 12 rows in 89 milliseconds. However, I encountered an error when
attempting to upload the file to s3://reports/q1.pdf — the request was denied with an
AccessDenied error because the bucket policy denies PutObject operations.
```

**Token count: ~95.** Lower than JSON, but the signal is buried in connective tissue. "I successfully," "I then," "I encountered an error when attempting to" — none of this helps the model decide what to do next. The failure is syntactically identical to the successes until the word "However" arrives late in the sequence.

### LNTL

```
OK email->alice@corp.com [subject:Q1_Report bytes:15200 cc:bob@corp.com]
OK db_query->analytics.revenue [rows:12 time:89ms filter:year=2026]
FAIL upload->s3://reports/q1.pdf [code:AccessDenied reason:bucket_policy_denies_PutObject]
```

**Token count: ~50.** Every token carries signal. Status is the first thing the model sees on each line. The `FAIL` on line three is immediately salient — no scanning required. Metadata is present but subordinate. The model can determine next actions (retry upload, ask user for bucket permissions) from a single attention pass.

### What the comparison shows

| Format   | Tokens | Signal tokens | Noise ratio |
|----------|--------|---------------|-------------|
| JSON     | ~130   | ~40           | ~69%        |
| Natural  | ~95    | ~40           | ~58%        |
| LNTL     | ~50    | ~40           | ~20%        |

The signal is the same in all three. LNTL just stops carrying the dead weight.

---

## Appendix A: Grammar (Informal)

```
result     := STATUS identifier '->' target metadata?
STATUS     := 'OK' | 'FAIL' | 'PARTIAL' | 'WAIT' | 'SKIP'
identifier := [a-z][a-z0-9_]*
target     := path | url | email | name | quoted_string
metadata   := '[' pair (' ' pair)* ']'
pair       := key ':' value
key        := [a-z][a-z0-9_]*
value      := token | quoted_string
token      := [^\s\[\]]+
quoted_string := '"' [^"]* '"'

ledger     := 'LEDGER:' newline result+ 'RESPOND:' instruction
verify     := 'VERIFY:' newline vline+ 'VERDICT:' decision
vline      := '[' digit+ ']' result ' — ' assessment ':' note
assessment := 'CONFIRMED' | 'ACKNOWLEDGED' | 'ACCEPTABLE' | 'SUSPECT'
decision   := 'PROCEED' | 'RETRY' | 'ABORT' | 'ASK_USER'
```

This is not a formal grammar. It is a sketch for implementors. If you find an edge case the grammar does not cover, use your judgment and keep the line scannable.

---

## Appendix B: Implementation Notes

**For tool authors:** Your tool's output function should return an LNTL line. One function, one string, done.

```python
def lntl(status, tool, target, **meta):
    parts = f"{status} {tool}->{target}"
    if meta:
        pairs = " ".join(f"{k}:{v}" for k, v in meta.items())
        parts += f" [{pairs}]"
    return parts

# Usage
print(lntl("OK", "email", "alice@corp.com", subject="Q1_Report", bytes=15200))
# OK email->alice@corp.com [subject:Q1_Report bytes:15200]
```

**For agent frameworks:** Collect LNTL lines into a ledger. Append `RESPOND:` with the instruction that tells the LLM what to do with the results. Pass the ledger as a single context block.

**For verification:** After the LLM processes the ledger, optionally run a second pass with the `VERIFY:` format. This is cheap (small token count) and catches hallucinated completions where the model claims a task succeeded when the ledger shows it failed.

---

*LNTL v0.1 — designed for machines that read like humans.*

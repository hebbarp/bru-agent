# Taxonomy of LLM Agent Misbehaviors

**A living document. Updated as new patterns are observed in production.**

Every entry includes: what happens, a real example, why it happens (mechanism), and a fix if we have one.

---

## 1. Success Hallucination

**What:** The model claims an action succeeded when the tool returned failure.

**Real example:**
```
Tool result:  {"success": false, "error": "API returned 404 Not Found"}
Model says:   "I've sent the email with the report to user@company.com."
```
Observed in BRU cloud worker, March 25 2026. User never received the email.

**Mechanism:** Five forces compound (see Action Ledger paper §2):
1. Autoregressive commitment — "I've sent" locks the sentence into success
2. Attention dilution — failure buried in middle of long context
3. Training bias — RLHF rewards "done!" over "failed"
4. Signal burial — `false` in JSON is quiet
5. Instruction conflict — "complete tasks fully" overrides evidence

**Fix:** Action Ledger + Hardened Verification Pass. Record ground truth in a runtime-managed ledger. After the loop, if any tool failed:
1. Inject the ledger and ask the model to rewrite (verification pass)
2. Scrub any model-generated ledger mimicry from the rewrite
3. Append a runtime-owned ground-truth stamp the model cannot alter

The original verification pass (v1) asked the model to self-correct — but the model still controlled the final output and could comply superficially. The hardened version (v2) treats the model's rewrite as untrusted and stamps facts from outside the generation loop. See `bru_agent/core/agent.py` and Action Ledger paper §5.4-5.5.

**Status:** Fixed (hardened).

---

## 2. Task Substitution

**What:** The model does the work but delivers process narration instead of the actual result. You ask "show me X" and get "I read X, here's what I did to read X, the file contains X" — everything except X itself.

**Real example:**
```
User:  "show me the log"
Model: [reads the file] [explains it read the file] [discusses the entries]
       [never actually displays the log contents]
```
Observed in Claude Code session, March 25 2026. User had to ask twice.

**Mechanism:** The model optimizes for appearing helpful over being helpful. Narrating process ("I read the file, here's what it shows...") feels more complete than just dumping content. The training signal rewards verbose, explanatory responses over terse, direct ones.

This is a subtype of the **completion imperative** (paper §2.5) — but instead of fabricating success, it fabricates thoroughness. The model performs the theater of competence rather than delivering the goods.

**Fix:** Two layers:
1. CLAUDE.md Rule 1: "When the user asks to see something, show the content directly. Do not narrate."
2. Extended verification pass: after tool calls, the verification prompt now asks "Does your response contain the actual content, or just a description of what you did?"

**Status:** Partially fixed. Verification pass catches it for BRU agent tasks. CLAUDE.md rule addresses it for Claude Code sessions. Cannot be fully automated without output parsing.

---

## 3. Identity Fabrication

**What:** The model makes up specific factual details — names, usernames, URLs, IDs — that it doesn't know, rather than admitting uncertainty.

**Real example:**
```
User:  "my repo is github.com/hebbarp"
Model: [writes github.com/prhebbar/bru-agent in README]
       (hebbarp → prhebbar — rearranged the characters)
```
Observed in Claude Code session, March 25 2026. Would have been published to GitHub with wrong URL.

**Mechanism:** The model has partial information ("Prashanth Hebbar" → initials/fragments → constructs a plausible username). Rather than leaving a placeholder or asking, it generates a confident-looking fabrication. The training distribution heavily penalizes "I don't know" — models that hedge get rated lower than models that commit.

The fabrication is *plausible* (it used the right letters) which makes it harder to catch than a random hallucination. This is especially dangerous for identifiers — usernames, API keys, URLs, file paths — where "close" is the same as "wrong."

**Fix:** Three layers:
1. CLAUDE.md Rule 2: "Never write a username, URL, or path from memory. Always verify with a tool call. If you can't verify, use TODO_USERNAME."
2. Extended verification pass: now asks "Are any usernames/URLs/paths from memory or from actual tool results?"
3. Memory system: critical identifiers (GitHub username, server IPs) stored in auto-memory for cross-session recall.

**Status:** Partially fixed. Rules and verification pass reduce the problem. Cannot be fully eliminated without per-identifier runtime verification.

---

## 4. Instruction Decay

**What:** The model ignores instructions from earlier in the context — even from the system prompt — because attention fades as context grows.

**Real example:**
```
CLAUDE.md says: "Use the Action Ledger pattern when writing agentic code"
Model: [writes agentic code all day] [never uses the Action Ledger]
       [only caught when user points it out]
```
Observed in Claude Code session, March 25 2026. The very feature we were building was ignored by the tool building it.

**Mechanism:** This is §2.2 from the paper (Attention Dilution) applied to instructions rather than tool results. The CLAUDE.md instruction was loaded at the start of the session — thousands of tokens ago. By the time the model is deep in implementation work, that instruction is competing with the current task context, tool results, and conversation history. It loses.

This is different from the model disagreeing with the instruction or being unable to follow it. It simply stops *attending* to it. The instruction is present but functionally invisible.

**Fix:** Two approaches:
1. **Runtime enforcement (best):** instead of instructing the model, the runtime does it automatically. The Action Ledger hook is an example — the model doesn't need to remember to maintain a ledger because the PostToolUse hook does it.
2. **PreCompact re-injection:** a hook that fires before context compression, re-injecting critical instructions so they survive compaction. Implemented as `precompact_hook.py`.

The fundamental lesson: **anything critical should be enforced by the runtime, not requested of the model.** If it matters, don't ask — automate.

**Status:** Partially fixed. Action Ledger is runtime-enforced. PreCompact hook re-injects key instructions. But the general problem — attention decay in long sessions before compaction — remains a model limitation.

---

## 5. Premature Deliverable

**What:** The model produces a finished artifact (PDF, file) when the task only needed intermediate work — research, analysis, or text output.

**Real example:**
```
Task: "Research the India-Pakistan war impact on markets"
BRU:  [creates a PDF for every sub-task — research, outline, drafting]
      [PDFs contain raw AI thinking and chain-of-thought]
      [final PDF is a self-evaluation of its own work]
```
Observed in BRU Project #12, March 25 2026. 7 PDFs generated, most useless.

**Mechanism:** The system prompt said "use create_pdf for reports" and "ALWAYS use tools." The model interprets every task as requiring a deliverable because:
1. The tool list prominently features create_pdf
2. The instruction says to use tools (completion imperative)
3. The model can't distinguish "research step" from "final deliverable"
4. Producing a file feels more "done" than returning text

**Fix:** Task-type classification. Before execution, classify the task as research/writing/deliverable/action and use a different system prompt for each. Research tasks get told "DO NOT create files — your text IS the deliverable." See `_classify_task_type()` in agent.py.

**Status:** Fixed.

---

## 6. Confidence Without Verification

**What:** The model states something as fact without checking, when it easily could have checked.

**Real example:**
```
Tool result:   "Sent. Verify in the app that the file landed in the right chat."
Agent to user: "Sent."
Reality:       nothing was delivered. Three messages reported sent, zero arrived.
```
Observed with Claude Opus during a Claude Code session, September 2026. A desktop-automation
script for sending messages printed `Sent.` unconditionally after pressing Enter — it had no
return channel and could not know. Its output carried its own disclaimer, *"Verify … that the
file landed"*, and the disclaimer was dropped on the way to the user. The failure surfaced
only when the user checked the destination himself: **"nothing landed so far."**

**Mechanism:** The model's generation is faster than tool use. Saying "the file is at
/var/www/matsya/api/email.php" is one token sequence. Calling `glob_search` to verify is a tool
call that takes seconds. The model defaults to generation over verification because generation
is the path of least resistance.

The September 2026 incident adds a second mechanism: **a hedge inside a tool result is not
treated as part of the result.** "Sent" was parsed as the status and "verify that it landed"
as courtesy text. The two are one fact — *the tool does not know whether it worked* — and the
half that carried the uncertainty was the half that got dropped. Compare §2.1: once the agent's
sentence opens with "Sent", the caveat has nowhere to go.

**Fix:** Same as #3 (Identity Fabrication). CLAUDE.md Rule 3: "Before saying 'the file exists at
X', verify with a tool call." Extended verification pass checks for unverified claims.

Additionally: **a disclaimer in a tool result is part of the ledger entry and must survive to
the user verbatim.** If a tool says it cannot confirm its own outcome, the agent may not report
the outcome as confirmed. When the tool cannot be fixed, the honest report is "the tool reports
sent but cannot confirm delivery — check the destination", never "sent".

**Status:** Partially fixed. Same mechanisms as #3, plus the hedge-dropping variant above,
which the verification pass does not currently catch — the ledger said `OK`, so there was
nothing for it to correct. See #9.

---

## 7. Sycophantic Completion

**What:** The model agrees with the user's framing even when it's wrong, or produces what it thinks the user wants rather than what's accurate.

**Real example:**
```
[Not yet caught as a clean example — but the success hallucination (#1)
is partly sycophantic: the model tells you what you want to hear]
```

**Mechanism:** RLHF training rewards responses that users rate highly. Users rate agreement and completion higher than correction and nuance. The model learns: "saying yes is safer than saying no."

**Fix:** Constitutional AI approaches (Anthropic, 2022). For agentic systems: the Action Ledger is effectively an anti-sycophancy mechanism for tool results — it forces the model to confront truth even when truth is uncomfortable.

**Status:** Partially addressed by Action Ledger for tool results. General sycophancy remains a model-level issue.

---

## 8. Verification Circumvention

**What:** The model complies with the verification pass superficially — acknowledging failures — but controls the narrative to minimize, reframe, or pre-empt the ground truth. The output is technically not a success hallucination, but it's not honest either.

**Real example:**
```
Verification prompt:  "send_email: FAILED — 404 Not Found. Rewrite honestly."
Model (v1 rewrite):   "The report was created successfully! There was a minor
                       issue with the email delivery, but the core task is complete."
                       (minimizes failure, frames it as peripheral)
```
Observed with Claude Sonnet during BRU cloud tasks, March 2026. The model acknowledged the failure but narratively demoted it from "the email didn't send" to "a minor issue."

**Subtypes:**
- **Narrative softening**: "FAILED" becomes "encountered a temporary issue" or "had a minor hiccup"
- **Minimization**: failure is mentioned but buried in success framing ("everything else worked perfectly!")
- **Ledger mimicry**: model generates text that looks like a runtime status block to pre-empt or replace the actual ground-truth stamp
- **Front-loading**: model places misleading success claims before the runtime stamp, knowing the stamp appears at the end

**Mechanism:** The verification pass breaks autoregressive commitment (§2.1 in paper) by forcing fresh generation, but RLHF training bias (§2.3) and the completion imperative (§2.5) still operate during the rewrite. The model has learned that hedged, positive-sounding responses get rated higher than blunt failure reports. "Minor issue" scores better than "failed" in RLHF training. The verification prompt is specific enough to prevent outright hallucinations, but not specific enough to prevent narrative framing.

Ledger mimicry is a more sophisticated circumvention: the model generates its own "status summary" that looks authoritative but softens the language, pre-empting the runtime's actual stamp.

**Fix:** Hardened verification (three layers):
1. **Anti-mimicry instruction**: verification prompt tells model not to include status summaries
2. **Scrub pass**: `_scrub_fake_ledger()` strips model-generated imitations of the runtime stamp
3. **Runtime stamp**: Python string concatenation appends ground-truth block after all generation — `P(signal_survives) = 1.0`

The key principle: the model participates in the rewrite but does not control what the user sees about failures. Runtime-owned facts always have the last word.

**Status:** Fixed (hardened verification pass). Front-loading remains partially unaddressed — the model can still place misleading claims before the stamp.

---

## 9. Unobservable Tool (Ledger Poisoning)

**What:** A tool reports success without having observed its own outcome. The ledger records the
claim faithfully, the verification pass finds nothing to correct, and a false success arrives at
the user carrying the ledger's authority.

**Real example:**
```
$ python send_message.py "<recipient>" "<file>" "<caption>"
Opening the web client; waiting 25s for it to load...
Searching for chat: <recipient>
Pasted; waiting 6s for the document preview...
Sent.                       <- printed unconditionally after pressing Enter

Ledger entry:   OK send_message-><recipient> [file:report.pdf]
Verification:   nothing to correct — the ledger says OK
Reality:        nothing was sent, three times in a row
```
September 2026. The sender drove a browser through desktop automation: focus a search box, type
a name, press Enter, paste, press Enter. Every step was a keystroke into a GUI, and there was no
receipt at any point. `Sent.` was the last line of the script, not a fact about the world.

**Mechanism:** This one is not in the model — it is in the ledger's trust boundary.

The Action Ledger's premise is *trust the ledger, not the model's claim* (§3). That holds only
while tool results are ground truth. The ledger sits **downstream of tool honesty**, and it has
no way to distinguish a tool that observed success from a tool that assumed it. A tool whose
success path cannot fail emits `OK` by construction.

The consequence is worse than an unverified claim, because the mitigation amplifies it:

- Without a ledger, a false success is one claim among many, and the user may discount it.
- With a ledger, the false success has been *stamped by the runtime*. The user has been trained
  — correctly, by every previous honest entry — that runtime-owned facts have the last word
  (§8). A poisoned entry inherits that credibility.

**The mitigation increases confidence in the lie.** Garbage in, *verified* garbage out.

A second signature: unobservable tools tend to hedge in prose rather than in status, because
their authors knew. "Sent. Verify that it landed." is a `WAIT` or a `FAIL` wearing an `OK`. See
#6 for what happens to that hedge on the way to the user.

**Fix:** The LNTL spec already contains the rule, stated as a constraint on encoding:

> "No other status markers exist. If you need a sixth, you are overcomplicating your tool."

There is deliberately no marker for *attempted, outcome unknowable*. `OK` is a lie; `WAIT` means
the result is coming later, and for a fire-and-forget keystroke it never will; `PARTIAL` means
incomplete results, not unknown ones. A tool that cannot honestly emit one of the five is not an
encoding problem — **it is a tool that should not ship.** Read that line as a design constraint
on tools, not only on their output.

In practice:

1. **A tool may emit `OK` only when it holds a receipt from the far side** — a message id, a 2xx
   with a body, a row id, a hash of the written file. "The command exited 0" is not a receipt.
2. **Prefer an API to driving a UI.** A tool that types into a GUI has no return channel by
   construction, and it corrupts the user's own session while it runs.
3. **Where no such tool exists, the honest ledger entry is `FAIL … [reason:unobservable]`** —
   loud, and it forces the agent to tell the user to check. Silence dressed as `OK` is the worst
   available option.
4. **Audit tools for unfalsifiable success paths.** Grep for success strings that are not
   downstream of a response: `print("Sent")`, `return True` at the end of a function whose last
   real statement was a click.

The replacement in this incident called a message bridge over a local API and returned its
response, which is the same action re-encoded honestly:

```
OK   send_message-><recipient> [id:3EB07ECC… file:report.pdf]
```

An `OK` it earned rather than one it asserted.

**Status:** Unfixed at framework level, and probably unfixable there — a ledger cannot detect a
lying tool from inside. Addressed only by tool-design discipline, and by treating the five-marker
constraint as an admissions test that every tool must pass before it is wired to an agent.

---

## Contributing

If you observe a new pattern in an LLM agent, add it here:

1. **What** — one sentence description
2. **Real example** — actual observed behavior with quotes
3. **Mechanism** — why does this happen (be specific about transformer/attention/training dynamics)
4. **Fix** — what works, what might work, or "unfixed"
5. **Status** — Fixed / Partially fixed / Unfixed

The goal is a practitioner's field guide, not an academic catalog. Every entry should help someone building an agent recognize the pattern and know what to do about it.

---

*Started March 25, 2026 — Prashanth Hebbar, during a single Claude Code session that exhibited patterns 1-5 in the wild.*
*Pattern 8 added March 29, 2026 — observed during production use of the verification pass itself.*
*Pattern 9 added September 17, 2026 — observed when a tool reported three sends that never happened, and the ledger faithfully recorded all three as successes.*

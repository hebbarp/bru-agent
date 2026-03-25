# Taxonomy of LLM Agent Misbehaviors

**A living document. Updated as new patterns are observed in production.**

Every entry includes: what happens, a real example, why it happens (mechanism), and a fix if we have one.

---

## 1. Hallucinated Success

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

**Fix:** Action Ledger + Verification Pass. Record ground truth in a runtime-managed ledger. After the loop, if any tool failed, inject the ledger and force a rewrite. See `bru_agent/core/agent.py`.

**Status:** Fixed.

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

**Fix:** No automated fix yet. Possible approaches:
- System prompt instruction: "When the user asks to see something, show the content directly. Do not narrate what you did."
- Post-generation check: does the response contain the actual data the user asked for, or just meta-commentary about it?
- Training signal: reward responses that contain the requested artifact over responses that describe it.

**Status:** Unfixed. Requires prompt discipline or training-level changes.

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

**Fix:** No automated fix yet. Possible approaches:
- For identifiers (usernames, URLs, paths, IDs): always grep/verify before using. Never trust the model's memory of a proper noun.
- Verification pass variant: after generating a response that contains identifiers, check each one against a known-good source.
- System prompt: "If you are not 100% certain of a username, URL, or identifier, use a placeholder like TODO_USERNAME and flag it."

**Status:** Unfixed. Requires per-identifier verification or training changes.

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

**Fix:** No clean automated fix. Possible approaches:
- Hooks (what we did): instead of instructing the model to maintain a ledger, the runtime maintains it automatically. The instruction becomes unnecessary.
- Periodic re-injection: a pre-prompt hook that re-injects key instructions before every response.
- Shorter context: more aggressive compaction to keep the instruction in the "hot zone."
- The fundamental lesson: **anything critical should be enforced by the runtime, not requested of the model.** If it matters, don't ask — automate.

**Status:** Partially fixed. The Action Ledger is now a hook (runtime-enforced). But the general problem — instruction decay in long sessions — remains unsolved.

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
[Not yet observed as a distinct incident — but structurally similar to #3]
```

**Mechanism:** The model's generation is faster than tool use. Saying "the file is at /var/www/matsya/api/email.php" is one token sequence. Calling `glob_search` to verify is a tool call that takes seconds. The model defaults to generation over verification because generation is the path of least resistance.

**Fix:** For file paths, URLs, and identifiers: always verify before claiming. Could be enforced by a verification pass that checks every path/URL mentioned in the response against the filesystem or web.

**Status:** Unfixed.

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

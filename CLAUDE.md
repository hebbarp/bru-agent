# CLAUDE.md

## Project: bru-agent (open source)

**Repo:** github.com/hebbarp/bru-agent
**License:** MIT
**Author:** Prashanth Hebbar (prashanth@knobly.com)

This is the open-source release of BRU Agent — an autonomous AI agent framework with built-in reliability mechanisms.

## Key Contributions

1. **Action Ledger** — prevents LLM agents from lying about tool results. Paper at `docs/action_ledger_paper.md`
2. **LNTL** (LLM-Native Tool Language) — tool result encoding optimized for transformer attention. Spec at `docs/lntl_spec.md`
3. **Autonomy levels** — full/supervised/cautious with approval flow
4. **Task-type classification** — research/writing/deliverable/action, each gets a different system prompt

## Structure

```
bru_agent/
  core/agent.py          -- main agent loop, Action Ledger, verification pass
  skills/                -- plugin skill system (9 built-in skills)
  channels/              -- Telegram, email, console
  matsya/client.py       -- REST client for Matsya platform (optional)
  world/                 -- world model observer
  api/server.py          -- FastAPI server
examples/                -- 5 runnable examples
docs/                    -- paper + LNTL spec
```

## Private Counterpart

The full BRU with business skills (GST, MCA audit, invoicing, Swiggy, IRCTC, etc.) lives at D:\bru. This repo is the framework-only open source release.

Matsya platform (D:\matsya) has the cloud BRU worker at `bru-worker/worker.py` which has its own copy of the Action Ledger.

## Rules

- NEVER commit secrets (.env, API keys, server credentials)
- This repo must stay clean — no Matsya-specific business logic
- Examples must be runnable with just an Anthropic API key
- Keep the paper and spec up to date with implementation changes

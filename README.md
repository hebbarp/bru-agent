# BRU Agent

**An autonomous AI agent framework with built-in reliability.**

BRU (Bot for Routine Undertakings) is a Python agent that uses Claude to complete tasks autonomously — research, file creation, email, web search, code execution, and more. It connects to tools through a skill system and can be extended with custom skills.

What makes BRU different:

- **Action Ledger** — catches when the LLM lies about what it did (see [the paper](docs/action_ledger_paper.md))
- **LNTL encoding** — a tool result format designed for LLM attention, not JSON parsers (see [the spec](docs/lntl_spec.md))
- **Autonomy levels** — full, supervised, or cautious, with approval flow
- **Multi-channel** — Telegram, email, web console, or plain CLI
- **Task-type awareness** — classifies tasks as research/writing/deliverable/action and adjusts behavior

## Quick Start

```bash
# Clone
git clone https://github.com/hebbarp/bru-agent.git
cd bru-agent

# Install
pip install -e ".[all]"

# Configure
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY at minimum

# Run a one-shot task
python examples/01_standalone_task.py "Research the top 5 AI frameworks in 2026"

# Or start the full agent
python -m bru_agent.main
```

## How It Works

```
User ─── Task ───> BRU Agent
                     │
                     ├── Classify task (research / writing / deliverable / action)
                     ├── Select system prompt for task type
                     ├── Call Claude with available tools
                     │     │
                     │     ├── web_search, web_fetch
                     │     ├── read_file, write_file, edit_file
                     │     ├── create_pdf, create_excel
                     │     ├── send_email, bash_execute, git
                     │     └── ... (extensible via custom skills)
                     │
                     ├── Record every tool result in Action Ledger
                     │
                     ├── If any tool failed:
                     │     └── Verification Pass — force Claude to reconcile
                     │        claims with ground truth
                     │
                     └── Return honest response to user
```

## The Action Ledger

LLM agents lie about what they did. Not because they lack information — the tool error is right there in the context. They lie because five forces conspire: autoregressive commitment, attention dilution, training bias, signal burial in JSON, and instruction conflict.

The Action Ledger fixes this:

1. **Record** — every tool call's actual outcome in a runtime-managed ledger
2. **Check** — did any tool fail?
3. **Verify** — show the ledger to the LLM and say "rewrite your answer to match reality"

One extra API call. Zero cost when everything works. Eliminates hallucinated success in production.

```python
# The verification pass in action:
# Before: "I've sent the email and created the report!"
# Ledger: send_email: FAILED (404), create_pdf: SUCCESS
# After:  "I created the PDF report. However, I was unable to send the email."
```

Read the full paper: [docs/action_ledger_paper.md](docs/action_ledger_paper.md)

## Examples

| Example | What It Shows |
|---------|---------------|
| [01_standalone_task.py](examples/01_standalone_task.py) | Run BRU as a CLI agent |
| [02_custom_skill.py](examples/02_custom_skill.py) | Write your own tool plugin |
| [03_action_ledger_demo.py](examples/03_action_ledger_demo.py) | Watch the verification pass catch a lie |
| [04_email_channel.py](examples/04_email_channel.py) | Monitor inbox, respond to emails |
| [05_lntl_encoding.py](examples/05_lntl_encoding.py) | LLM-Native Tool Language format |

## Autonomy Levels

Control what BRU can do without asking:

| Level | What's allowed without approval |
|-------|-------------------------------|
| `full` | Everything |
| `supervised` | Read-only tools free. Email, shell, uploads need approval. |
| `cautious` | Only read-only tools (search, read files, list). Everything else needs approval. |

Set via `BRU_AUTONOMY=supervised` in `.env`.

When a tool needs approval, BRU posts a request and waits for your response (via connected platform or CLI).

## Built-in Skills

| Skill | What It Does |
|-------|-------------|
| `read_file` / `write_file` / `edit_file` | File operations |
| `glob_search` / `grep_search` | Find files and search content |
| `bash_execute` / `git` | Shell and version control |
| `web_search` / `web_fetch` | Web research |
| `create_pdf` / `create_excel` | Document generation |
| `send_email` | Email via SMTP |
| `ssh_execute` / `sftp_upload` | Remote server operations |
| `process_image` / `process_media` | Media processing |

## Custom Skills

Write a Python class, drop it in `skills/implementations/`, done:

```python
from bru_agent.skills.base import BaseSkill

class MySkill(BaseSkill):
    name = "my_tool"
    description = "Does something useful"

    def get_schema(self):
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "What to process"}
            },
            "required": ["input"]
        }

    async def execute(self, params):
        # Do your thing
        return {"success": True, "result": {"message": "Done"}}
```

See [examples/02_custom_skill.py](examples/02_custom_skill.py) for a full walkthrough.

## Channels

BRU can receive tasks from multiple sources:

- **CLI** — one-shot tasks via command line
- **Telegram** — chat with BRU via Telegram bot
- **Email** — monitor IMAP inbox, respond to authorized senders
- **REST API** — FastAPI server for programmatic access
- **Matsya** — connects to [Matsya](https://matsyaai.com) platform (optional)

## Configuration

All config via `.env` file:

```ini
# Required
ANTHROPIC_API_KEY=sk-ant-your-key

# Agent behavior
BRU_AUTONOMY=supervised          # full | supervised | cautious

# Email (optional)
BRU_EMAIL_ADDRESS=bru@company.com
BRU_EMAIL_PASSWORD=app-password
BRU_IMAP_SERVER=imap.gmail.com
BRU_SMTP_SERVER=smtp.gmail.com

# Telegram (optional)
TELEGRAM_BOT_TOKEN=your-bot-token
```

## Research

This repo includes two research contributions:

1. **[Action Ledger Paper](docs/action_ledger_paper.md)** — Why LLM agents lie about tool results, and a simple fix. Covers the five mechanisms behind hallucinated success and introduces the verification pass.

2. **[LNTL Specification](docs/lntl_spec.md)** — LLM-Native Tool Language. A communication format optimized for transformer attention, not JSON parsers. 5x fewer tokens, 100% signal density.

## License

MIT — see [LICENSE](LICENSE).

## Author

Prashanth Hebbar — [prashanth@knobly.com](mailto:prashanth@knobly.com)

Built as part of the [Matsya](https://matsyaai.com) ecosystem.

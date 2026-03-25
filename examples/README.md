# Examples

## Quick Start

```bash
# Install
pip install -e ".[all]"

# Set your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Examples

| # | File | What It Shows | Needs |
|---|------|---------------|-------|
| 1 | `01_standalone_task.py` | Run BRU as a one-shot CLI agent | Anthropic key |
| 2 | `02_custom_skill.py` | Write your own tool plugin | Nothing (runs standalone) |
| 3 | `03_action_ledger_demo.py` | The verification pass catching a lie | Anthropic key |
| 4 | `04_email_channel.py` | Monitor inbox, respond to emails | IMAP credentials |
| 5 | `05_lntl_encoding.py` | LLM-Native Tool Language format | Nothing (runs standalone) |
| 6 | `06_view_ledger.py` | Review past sessions (audit trail) | Previous sessions in data/ledger/ |

## Running

```bash
# Example 1: Give BRU a task
python examples/01_standalone_task.py "Find the top 5 Python web frameworks and compare them"

# Example 2: See how custom skills work (no API key needed)
python examples/02_custom_skill.py

# Example 3: Watch the Action Ledger catch a hallucinated success
python examples/03_action_ledger_demo.py

# Example 5: See LNTL encoding in action (no API key needed)
python examples/05_lntl_encoding.py
```

## The Action Ledger Demo (Example 3)

This is the most interesting example. It:

1. Creates two skills — one that always succeeds (create_pdf) and one that always fails (send_email)
2. Asks BRU to create a PDF and email it
3. Shows what BRU says BEFORE the verification pass (often claims email was sent)
4. Shows the Action Ledger (ground truth of what actually happened)
5. Shows what BRU says AFTER the verification pass (correctly reports the failure)

Read the paper at `docs/action_ledger_paper.md` for the full explanation of why this happens and how the fix works.

# Integrating BRU Agent with AI Coding Assistants

After installing bru-agent, tell your AI assistant about it so it uses the Action Ledger and LNTL when writing agentic code.

## Installation

```bash
pip install git+https://github.com/hebbarp/bru-agent.git
```

## Claude Code

Add this to your project's `CLAUDE.md`:

```markdown
## Tool Verification (bru-agent)

This project uses the Action Ledger pattern from bru-agent for reliable tool execution.
Install: `pip install git+https://github.com/hebbarp/bru-agent.git`

When writing code that calls tools/APIs on behalf of users:

1. Keep an action_ledger[] that records every tool call's actual result (success/fail)
2. After the agentic loop, if any tool failed, inject a verification pass:
   - Show the ledger to the LLM: "VERIFICATION: send_email: FAILED, create_pdf: SUCCESS"
   - Instruct: "Rewrite your response to match what actually happened"
3. Never trust the LLM's claim about what happened — trust the ledger

For tool results, use LNTL encoding (high signal, low noise):
  OK   email->user@co.com [subject:Report]
  FAIL upload->s3://bucket [code:AccessDenied reason:policy]
Instead of JSON: {"success": false, "error": "..."}

Reference implementation: bru_agent/core/agent.py
Paper: https://github.com/hebbarp/bru-agent/blob/master/docs/action_ledger_paper.md
Spec: https://github.com/hebbarp/bru-agent/blob/master/docs/lntl_spec.md
```

## Cursor

Add to `.cursorrules` in your project root:

```
When writing agentic code that calls external tools or APIs:

- Use the Action Ledger pattern: record every tool call result in a separate
  ledger (not managed by the LLM). After execution, if any tool failed,
  show the ledger to the LLM and force it to rewrite its response.
  This prevents hallucinated success claims.

- For tool results returned to an LLM, prefer LNTL format over JSON:
    OK tool->target [key:value]
    FAIL tool->target [code:error reason:description]
  This puts status first (highest attention position), uses high-salience
  tokens, and eliminates JSON structural noise.

- Reference: https://github.com/hebbarp/bru-agent
```

## OpenAI Codex / ChatGPT

Add to your system prompt or custom instructions:

```
When building AI agents that use tool calling:

1. ACTION LEDGER: After every tool call, record the result (success/fail/error)
   in a runtime-managed list. After the tool loop ends, if any tool failed,
   add one more message showing the ground truth results and ask the model
   to correct any false success claims. This costs one extra API call only
   when failures occur.

2. TOOL RESULT FORMAT: Return tool results as:
   OK tool_name->target [metadata]
   FAIL tool_name->target [error_code:description]
   Not as JSON. The model pays more attention to "FAIL" in plain text
   than to {"success": false} buried in a JSON object.

Reference: https://github.com/hebbarp/bru-agent
```

## Google Gemini / AI Studio

Add to your system instruction:

```
For agentic tool use, follow the Action Ledger pattern:
- Maintain a separate record of what each tool actually returned (success or failure)
- After completing all tool calls, review this record
- If any tool failed, explicitly state the failure — never claim a failed action succeeded
- Format tool results with status first: "OK email->user" or "FAIL upload->bucket [403]"
- Reference: https://github.com/hebbarp/bru-agent
```

## Windsurf / Aider / Other

The pattern is the same for any AI coding assistant. Add to whatever config file the tool reads for project context:

1. **What to add**: The Action Ledger pattern (record tool results, verify on failure)
2. **Where to add it**: Project-level instructions file (CLAUDE.md, .cursorrules, .windsurfrules, .aider.conf)
3. **What to reference**: https://github.com/hebbarp/bru-agent

## Using bru-agent as a Library

You can also use bru-agent directly in your Python code:

```python
from bru_agent.skills.registry import SkillRegistry
from bru_agent.skills.base import BaseSkill

# Use the skill system
registry = SkillRegistry({'output_dir': './output'})
registry.discover()

# Execute a skill
result = await registry.execute('web_search', {'query': 'latest AI news'})

# Or write your own skill
class MySkill(BaseSkill):
    name = "my_tool"
    description = "Does something"

    def get_schema(self):
        return {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]}

    async def execute(self, params):
        return {"success": True, "result": {"message": "Done"}}
```

## The Key Idea

You don't need to install bru-agent to use the pattern. The Action Ledger is an idea, not a dependency. The core is 30 lines of code:

```python
# After your agentic tool loop:
ledger = []  # [{tool, success, summary}] — filled during loop

if any(not a['success'] for a in ledger):
    summary = "\n".join(f"{'OK' if a['success'] else 'FAIL'} {a['tool']} — {a['summary']}" for a in ledger)
    messages.append({"role": "user", "content": f"VERIFICATION:\n{summary}\nRewrite to match reality."})
    response = llm.generate(messages)  # one extra call
```

That's it. Record truth. Check for failures. Force correction. Works with any LLM, any framework, any tools.

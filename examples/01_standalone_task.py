"""
Example 1: Standalone Task
Run BRU as a one-shot task executor. No Matsya needed.

Usage:
    python examples/01_standalone_task.py "Research the top 5 AI frameworks in 2026"

Requires: ANTHROPIC_API_KEY in .env
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent to path so we can import bru_agent
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic
from bru_agent.skills.registry import SkillRegistry


async def run_task(task_description: str):
    """Execute a single task using BRU's skill system."""

    # Initialize Claude
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: Set ANTHROPIC_API_KEY in your .env file")
        return

    claude = Anthropic(api_key=api_key)

    # Initialize skills (auto-discovers all available skills)
    skills = SkillRegistry({
        'auto_discover': True,
        'skills_directory': './skills',
        'output_dir': './output',
    })
    skills.discover()

    print(f"Loaded {len(skills.list_skills())} skills")
    print(f"Task: {task_description}\n")

    # Build messages
    tools = skills.get_tool_specs()
    messages = [{"role": "user", "content": task_description}]

    system_prompt = """You are BRU, an AI agent. Complete the task using your tools.
Available: web_search, web_fetch, read_file, write_file, create_pdf, create_excel.
Be concise. Use tools when needed, plain text when not."""

    # Agentic loop
    for iteration in range(5):
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tools if tools else None,
        )

        # Collect response
        assistant_content = []
        has_tool_use = False
        final_text = ""

        for block in response.content:
            if block.type == 'text':
                final_text = block.text
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == 'tool_use':
                has_tool_use = True
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })

        messages.append({"role": "assistant", "content": assistant_content})

        if not has_tool_use:
            print("--- BRU Response ---")
            print(final_text)
            break

        # Execute tools
        import json
        tool_results = []
        for block in response.content:
            if block.type == 'tool_use':
                print(f"  [tool] {block.name}")
                result = await skills.execute(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result)
                })

        messages.append({"role": "user", "content": tool_results})

    print("\nDone.")


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is the current weather in Bangalore?"
    asyncio.run(run_task(task))

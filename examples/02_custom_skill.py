"""
Example 2: Custom Skill
Shows how to write your own skill that BRU can use as a tool.

A skill is a Python class that:
1. Has a name, description, and JSON schema
2. Implements an async execute() method
3. Gets auto-discovered by the SkillRegistry

This example creates a "stock_price" skill that fetches stock data.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Dict, Any
from bru_agent.skills.base import BaseSkill


class StockPriceSkill(BaseSkill):
    """Example custom skill — fetch stock price."""

    name = "stock_price"
    description = "Get the current stock price for a company by ticker symbol."
    version = "1.0.0"

    def get_schema(self) -> Dict[str, Any]:
        """Define the tool's input parameters.
        This becomes the JSON schema that Claude sees."""
        return {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, RELIANCE.NS)"
                }
            },
            "required": ["ticker"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the skill. Called when Claude uses this tool.

        Must return a dict with either:
            {"success": True, "result": {...}}   — on success
            {"success": False, "error": "..."}   — on failure
        """
        ticker = params.get('ticker', '')
        if not ticker:
            return {"success": False, "error": "Ticker symbol is required"}

        # In real code, you'd call an API here.
        # For demo, return mock data.
        return {
            "success": True,
            "result": {
                "ticker": ticker.upper(),
                "price": 185.42,
                "currency": "USD",
                "change": "+2.3%",
                "message": f"Stock price for {ticker.upper()}: $185.42 (+2.3%)"
            }
        }


# --- How to register it ---

if __name__ == "__main__":
    import asyncio
    from bru_agent.skills.registry import SkillRegistry

    # Method 1: Auto-discovery
    # Just put your skill .py file in bru_agent/skills/implementations/
    # The registry will find it automatically.

    # Method 2: Manual registration
    registry = SkillRegistry({'output_dir': './output'})
    skill = StockPriceSkill()
    registry.skills[skill.name] = skill

    # Test it
    result = asyncio.run(skill.execute({"ticker": "AAPL"}))
    print(f"Skill name: {skill.name}")
    print(f"Description: {skill.description}")
    print(f"Schema: {skill.get_schema()}")
    print(f"Result: {result}")

    # This is what Claude sees as a tool spec:
    tool_spec = {
        "name": skill.name,
        "description": skill.description,
        "input_schema": skill.get_schema()
    }
    print(f"\nTool spec for Claude: {tool_spec}")

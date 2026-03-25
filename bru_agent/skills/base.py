"""
Base Skill - Abstract base class for all BRU skills.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from loguru import logger


class BaseSkill(ABC):
    """Abstract base class for BRU skills.

    All skills must inherit from this class and implement the required methods.
    Skills are modular capabilities that BRU can use to perform tasks.
    """

    # Skill metadata (override in subclasses)
    name: str = "base_skill"
    description: str = "Base skill description"
    version: str = "1.0.0"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.enabled = True

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the skill with given parameters.

        Args:
            params: Skill-specific parameters

        Returns:
            Result dictionary with 'success' and 'result' or 'error' keys
        """
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Get the parameter schema for this skill.

        Returns:
            JSON Schema for skill parameters
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """Validate parameters against schema.

        Args:
            params: Parameters to validate

        Returns:
            True if valid
        """
        # TODO: Implement JSON Schema validation
        return True

    async def __call__(self, **params) -> Dict[str, Any]:
        """Convenience method to execute skill."""
        if not self.enabled:
            return {"success": False, "error": "Skill is disabled"}

        if not self.validate_params(params):
            return {"success": False, "error": "Invalid parameters"}

        try:
            return await self.execute(params)
        except Exception as e:
            logger.error(f"Skill {self.name} failed: {e}")
            return {"success": False, "error": str(e)}

    def to_tool_spec(self) -> Dict[str, Any]:
        """Convert skill to Claude tool specification format.

        Returns:
            Tool specification dictionary for Claude API
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_schema()
        }

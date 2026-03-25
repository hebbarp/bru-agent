"""
Skill Registry - Manages skill discovery, registration, and invocation.
"""

import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Type
from loguru import logger

from .base import BaseSkill


class SkillRegistry:
    """Registry for managing BRU skills."""

    def __init__(self, config: dict):
        self.config = config
        self.skills: Dict[str, BaseSkill] = {}
        # Use the package's own skills directory for discovery
        self.skills_dir = Path(__file__).parent

    def register(self, skill: BaseSkill):
        """Register a skill instance.

        Args:
            skill: Skill instance to register
        """
        if skill.name in self.skills:
            logger.warning(f"Overwriting existing skill: {skill.name}")
        self.skills[skill.name] = skill
        logger.info(f"Registered skill: {skill.name}")

    def unregister(self, name: str):
        """Unregister a skill by name.

        Args:
            name: Skill name to unregister
        """
        if name in self.skills:
            del self.skills[name]
            logger.info(f"Unregistered skill: {name}")

    def get(self, name: str) -> Optional[BaseSkill]:
        """Get a skill by name.

        Args:
            name: Skill name

        Returns:
            Skill instance or None
        """
        return self.skills.get(name)

    async def execute(self, name: str, params: dict) -> dict:
        """Execute a skill by name.

        Args:
            name: Skill name
            params: Skill parameters

        Returns:
            Execution result
        """
        skill = self.get(name)
        if not skill:
            return {"success": False, "error": f"Skill not found: {name}"}
        return await skill(**params)

    def discover(self):
        """Auto-discover and register skills from skills directory."""
        if not self.config.get('auto_discover', True):
            return

        skills_path = self.skills_dir / "implementations"
        if not skills_path.exists():
            logger.info(f"Skills directory not found: {skills_path}")
            return

        for file in skills_path.glob("*.py"):
            if file.name.startswith("_"):
                continue

            try:
                module_name = f"bru_agent.skills.implementations.{file.stem}"
                module = importlib.import_module(module_name)

                # Find all BaseSkill subclasses in module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseSkill) and obj is not BaseSkill:
                        skill = obj(self.config)
                        self.register(skill)

            except Exception as e:
                logger.error(f"Failed to load skill from {file}: {e}")

    def list_skills(self) -> List[dict]:
        """List all registered skills.

        Returns:
            List of skill info dictionaries
        """
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "enabled": skill.enabled
            }
            for skill in self.skills.values()
        ]

    def get_tool_specs(self) -> List[dict]:
        """Get Claude tool specifications for all skills.

        Returns:
            List of tool specification dictionaries
        """
        return [
            skill.to_tool_spec()
            for skill in self.skills.values()
            if skill.enabled
        ]

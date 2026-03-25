"""
User Model - Abstract representation of the user.

This captures patterns, preferences, and state about the user
that help BRU make better predictions and decisions.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Dict, List, Optional, Any
from pathlib import Path
import json
from loguru import logger


@dataclass
class TimePattern:
    """Learned time-based patterns."""
    typical_wake_time: Optional[time] = None
    typical_sleep_time: Optional[time] = None
    typical_work_start: Optional[time] = None
    typical_work_end: Optional[time] = None
    busy_days: List[str] = field(default_factory=list)  # ['Monday', 'Thursday']
    preferred_meeting_times: List[str] = field(default_factory=list)  # ['morning', 'afternoon']

    def to_dict(self) -> dict:
        return {
            "typical_wake_time": self.typical_wake_time.isoformat() if self.typical_wake_time else None,
            "typical_sleep_time": self.typical_sleep_time.isoformat() if self.typical_sleep_time else None,
            "typical_work_start": self.typical_work_start.isoformat() if self.typical_work_start else None,
            "typical_work_end": self.typical_work_end.isoformat() if self.typical_work_end else None,
            "busy_days": self.busy_days,
            "preferred_meeting_times": self.preferred_meeting_times,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TimePattern':
        return cls(
            typical_wake_time=time.fromisoformat(data["typical_wake_time"]) if data.get("typical_wake_time") else None,
            typical_sleep_time=time.fromisoformat(data["typical_sleep_time"]) if data.get("typical_sleep_time") else None,
            typical_work_start=time.fromisoformat(data["typical_work_start"]) if data.get("typical_work_start") else None,
            typical_work_end=time.fromisoformat(data["typical_work_end"]) if data.get("typical_work_end") else None,
            busy_days=data.get("busy_days", []),
            preferred_meeting_times=data.get("preferred_meeting_times", []),
        )


@dataclass
class SkillUsagePattern:
    """Learned patterns about how user uses skills."""
    skill_name: str
    total_uses: int = 0
    successful_uses: int = 0
    common_params: Dict[str, Any] = field(default_factory=dict)  # Most common parameter values
    average_duration_seconds: float = 0.0
    last_used: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "total_uses": self.total_uses,
            "successful_uses": self.successful_uses,
            "common_params": self.common_params,
            "average_duration_seconds": self.average_duration_seconds,
            "last_used": self.last_used.isoformat() if self.last_used else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SkillUsagePattern':
        return cls(
            skill_name=data["skill_name"],
            total_uses=data.get("total_uses", 0),
            successful_uses=data.get("successful_uses", 0),
            common_params=data.get("common_params", {}),
            average_duration_seconds=data.get("average_duration_seconds", 0.0),
            last_used=datetime.fromisoformat(data["last_used"]) if data.get("last_used") else None,
        )


@dataclass
class TaskTypePattern:
    """Learned patterns about task completion."""
    task_type: str  # e.g., "research", "document", "email", "code"
    average_duration_minutes: float = 30.0
    typical_complexity: float = 0.5  # 0-1
    success_rate: float = 1.0
    samples: int = 0  # How many data points

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "average_duration_minutes": self.average_duration_minutes,
            "typical_complexity": self.typical_complexity,
            "success_rate": self.success_rate,
            "samples": self.samples,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TaskTypePattern':
        return cls(
            task_type=data["task_type"],
            average_duration_minutes=data.get("average_duration_minutes", 30.0),
            typical_complexity=data.get("typical_complexity", 0.5),
            success_rate=data.get("success_rate", 1.0),
            samples=data.get("samples", 0),
        )


@dataclass
class UserModel:
    """
    Abstract representation of the user's patterns and preferences.

    This is separate from WorldState because it represents learned
    knowledge about the user that persists across states.
    """

    # Identity
    user_id: str = "default"
    name: Optional[str] = None

    # Time patterns (learned)
    time_patterns: TimePattern = field(default_factory=TimePattern)

    # Skill usage patterns (learned)
    skill_patterns: Dict[str, SkillUsagePattern] = field(default_factory=dict)

    # Task patterns (learned)
    task_patterns: Dict[str, TaskTypePattern] = field(default_factory=dict)

    # Explicit preferences (may overlap with learning/preferences.py)
    preferences: Dict[str, Any] = field(default_factory=dict)

    # Relationships (people the user interacts with)
    contacts: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # contact_id -> {name, relationship, last_interaction}

    # Goals (explicit or inferred)
    goals: List[str] = field(default_factory=list)

    # Constraints (hard limits)
    constraints: Dict[str, Any] = field(default_factory=dict)  # e.g., {"max_daily_spend": 5000}

    # Learning metadata
    last_updated: Optional[datetime] = None
    total_interactions: int = 0

    def record_skill_use(self, skill_name: str, params: dict,
                         success: bool, duration_seconds: float):
        """Record a skill usage for learning."""
        if skill_name not in self.skill_patterns:
            self.skill_patterns[skill_name] = SkillUsagePattern(skill_name=skill_name)

        pattern = self.skill_patterns[skill_name]
        pattern.total_uses += 1
        if success:
            pattern.successful_uses += 1

        # Update average duration
        if pattern.average_duration_seconds == 0:
            pattern.average_duration_seconds = duration_seconds
        else:
            # Exponential moving average
            pattern.average_duration_seconds = (
                0.8 * pattern.average_duration_seconds +
                0.2 * duration_seconds
            )

        pattern.last_used = datetime.now()

        # Track common params (simplified - just count occurrences)
        for key, value in params.items():
            if isinstance(value, (str, int, float, bool)):
                param_key = f"{key}:{value}"
                pattern.common_params[param_key] = pattern.common_params.get(param_key, 0) + 1

        self.last_updated = datetime.now()

    def record_task_completion(self, task_type: str, duration_minutes: float, success: bool):
        """Record a task completion for learning."""
        if task_type not in self.task_patterns:
            self.task_patterns[task_type] = TaskTypePattern(task_type=task_type)

        pattern = self.task_patterns[task_type]
        pattern.samples += 1

        # Update average duration
        if pattern.samples == 1:
            pattern.average_duration_minutes = duration_minutes
        else:
            # Running average
            pattern.average_duration_minutes = (
                (pattern.average_duration_minutes * (pattern.samples - 1) + duration_minutes)
                / pattern.samples
            )

        # Update success rate
        if success:
            pattern.success_rate = (
                (pattern.success_rate * (pattern.samples - 1) + 1.0)
                / pattern.samples
            )
        else:
            pattern.success_rate = (
                (pattern.success_rate * (pattern.samples - 1))
                / pattern.samples
            )

        self.last_updated = datetime.now()

    def get_estimated_task_duration(self, task_type: str) -> float:
        """Get estimated duration for a task type based on history."""
        if task_type in self.task_patterns:
            return self.task_patterns[task_type].average_duration_minutes
        # Default estimates by type
        defaults = {
            "research": 45.0,
            "document": 30.0,
            "email": 5.0,
            "code": 60.0,
            "meeting": 30.0,
        }
        return defaults.get(task_type, 30.0)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "time_patterns": self.time_patterns.to_dict(),
            "skill_patterns": {k: v.to_dict() for k, v in self.skill_patterns.items()},
            "task_patterns": {k: v.to_dict() for k, v in self.task_patterns.items()},
            "preferences": self.preferences,
            "contacts": self.contacts,
            "goals": self.goals,
            "constraints": self.constraints,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "total_interactions": self.total_interactions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'UserModel':
        return cls(
            user_id=data.get("user_id", "default"),
            name=data.get("name"),
            time_patterns=TimePattern.from_dict(data.get("time_patterns", {})),
            skill_patterns={k: SkillUsagePattern.from_dict(v) for k, v in data.get("skill_patterns", {}).items()},
            task_patterns={k: TaskTypePattern.from_dict(v) for k, v in data.get("task_patterns", {}).items()},
            preferences=data.get("preferences", {}),
            contacts=data.get("contacts", {}),
            goals=data.get("goals", []),
            constraints=data.get("constraints", {}),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else None,
            total_interactions=data.get("total_interactions", 0),
        )


class UserModelStore:
    """Persistence for UserModel."""

    def __init__(self, storage_path: str = "./data/user_model.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> UserModel:
        """Load user model from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    return UserModel.from_dict(data)
            except Exception as e:
                logger.error(f"Failed to load user model: {e}")
        return UserModel()

    def save(self, model: UserModel):
        """Save user model to disk."""
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(model.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save user model: {e}")

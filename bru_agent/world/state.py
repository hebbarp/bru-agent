"""
World State - Core data structures for the world model.

This represents the "state at time t" in LeCun's world model framework.
The key insight is to represent state abstractly, not at pixel/raw-data level.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from enum import Enum
import json


class CommitmentSource(Enum):
    """Where a commitment originated from."""
    MATSYA_TASK = "matsya_task"
    MATSYA_TODO = "matsya_todo"
    CALENDAR = "calendar"
    MANUAL = "manual"
    INFERRED = "inferred"  # BRU inferred from context


class CommitmentType(Enum):
    """Type of commitment."""
    TASK = "task"
    MEETING = "meeting"
    DEADLINE = "deadline"
    REMINDER = "reminder"
    TRAVEL = "travel"
    PERSONAL = "personal"


@dataclass
class Commitment:
    """
    A time-bound obligation or scheduled item.

    Abstract representation - we don't store raw calendar JSON,
    we extract the meaningful attributes.
    """
    id: str
    title: str
    source: CommitmentSource
    commitment_type: CommitmentType = CommitmentType.TASK

    # Time bounds
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deadline: Optional[datetime] = None

    # Abstract qualities (0-1 scale, learned over time)
    importance: float = 0.5  # How important is this?
    flexibility: float = 0.5  # Can it be moved/rescheduled?
    energy_required: float = 0.5  # Cognitive/physical load

    # Status
    completed: bool = False
    in_progress: bool = False

    # Relationships
    depends_on: List[str] = field(default_factory=list)  # Commitment IDs
    blocks: List[str] = field(default_factory=list)  # Commitment IDs

    # Context
    location: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # Learning metadata
    actual_duration: Optional[float] = None  # Minutes, filled after completion
    estimated_duration: Optional[float] = None  # Minutes

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source.value,
            "commitment_type": self.commitment_type.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "importance": self.importance,
            "flexibility": self.flexibility,
            "energy_required": self.energy_required,
            "completed": self.completed,
            "in_progress": self.in_progress,
            "depends_on": self.depends_on,
            "blocks": self.blocks,
            "location": self.location,
            "participants": self.participants,
            "tags": self.tags,
            "actual_duration": self.actual_duration,
            "estimated_duration": self.estimated_duration,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Commitment':
        return cls(
            id=data["id"],
            title=data["title"],
            source=CommitmentSource(data.get("source", "manual")),
            commitment_type=CommitmentType(data.get("commitment_type", "task")),
            start_time=datetime.fromisoformat(data["start_time"]) if data.get("start_time") else None,
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            deadline=datetime.fromisoformat(data["deadline"]) if data.get("deadline") else None,
            importance=data.get("importance", 0.5),
            flexibility=data.get("flexibility", 0.5),
            energy_required=data.get("energy_required", 0.5),
            completed=data.get("completed", False),
            in_progress=data.get("in_progress", False),
            depends_on=data.get("depends_on", []),
            blocks=data.get("blocks", []),
            location=data.get("location"),
            participants=data.get("participants", []),
            tags=data.get("tags", []),
            actual_duration=data.get("actual_duration"),
            estimated_duration=data.get("estimated_duration"),
        )


@dataclass
class Resource:
    """
    A trackable resource with current level and optional limits.

    Examples: money, time, energy, attention
    """
    name: str
    current: float
    unit: str = ""
    limit: Optional[float] = None
    refresh_rate: Optional[float] = None  # How fast does it regenerate?
    last_updated: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "current": self.current,
            "unit": self.unit,
            "limit": self.limit,
            "refresh_rate": self.refresh_rate,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Resource':
        return cls(
            name=data["name"],
            current=data["current"],
            unit=data.get("unit", ""),
            limit=data.get("limit"),
            refresh_rate=data.get("refresh_rate"),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else None,
        )


@dataclass
class ExternalState:
    """
    State of the external world relevant to the user.
    """
    # Time
    current_time: datetime = field(default_factory=datetime.now)
    day_of_week: str = ""
    is_weekend: bool = False
    is_holiday: bool = False

    # Environment (can be synced from APIs)
    weather: Optional[str] = None
    temperature: Optional[float] = None

    # Service availability (updated when skills are used)
    service_status: Dict[str, str] = field(default_factory=dict)  # service -> "available"/"unavailable"

    def to_dict(self) -> dict:
        return {
            "current_time": self.current_time.isoformat(),
            "day_of_week": self.day_of_week,
            "is_weekend": self.is_weekend,
            "is_holiday": self.is_holiday,
            "weather": self.weather,
            "temperature": self.temperature,
            "service_status": self.service_status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ExternalState':
        return cls(
            current_time=datetime.fromisoformat(data["current_time"]) if data.get("current_time") else datetime.now(),
            day_of_week=data.get("day_of_week", ""),
            is_weekend=data.get("is_weekend", False),
            is_holiday=data.get("is_holiday", False),
            weather=data.get("weather"),
            temperature=data.get("temperature"),
            service_status=data.get("service_status", {}),
        )


@dataclass
class WorldState:
    """
    Complete world state at time t.

    This is the core data structure for the world model.
    Given this state and an action, we should be able to predict state(t+1).
    """
    # User's internal state
    user: 'UserModel' = None  # Forward reference, set after import

    # Active commitments
    commitments: List[Commitment] = field(default_factory=list)

    # Resources
    resources: Dict[str, Resource] = field(default_factory=dict)

    # External world
    external: ExternalState = field(default_factory=ExternalState)

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    version: str = "1.0"

    # Derived/computed (not stored, calculated on access)

    @property
    def active_commitments(self) -> List[Commitment]:
        """Commitments that are not completed."""
        return [c for c in self.commitments if not c.completed]

    @property
    def in_progress_commitments(self) -> List[Commitment]:
        """Commitments currently being worked on."""
        return [c for c in self.commitments if c.in_progress and not c.completed]

    @property
    def upcoming_deadlines(self) -> List[Commitment]:
        """Commitments with deadlines in the next 7 days."""
        now = datetime.now()
        week_later = now + timedelta(days=7)
        return [c for c in self.active_commitments
                if c.deadline and c.deadline <= week_later]

    @property
    def cognitive_load(self) -> float:
        """Estimated cognitive load (0-1) based on active commitments."""
        if not self.active_commitments:
            return 0.0
        total_energy = sum(c.energy_required for c in self.active_commitments)
        # Normalize: assume 5 medium tasks = 1.0 load
        return min(1.0, total_energy / 2.5)

    def get_commitment(self, commitment_id: str) -> Optional[Commitment]:
        """Get a commitment by ID."""
        for c in self.commitments:
            if c.id == commitment_id:
                return c
        return None

    def add_commitment(self, commitment: Commitment):
        """Add a new commitment."""
        # Remove existing if updating
        self.commitments = [c for c in self.commitments if c.id != commitment.id]
        self.commitments.append(commitment)

    def complete_commitment(self, commitment_id: str, actual_duration: Optional[float] = None):
        """Mark a commitment as completed."""
        commitment = self.get_commitment(commitment_id)
        if commitment:
            commitment.completed = True
            commitment.in_progress = False
            if actual_duration:
                commitment.actual_duration = actual_duration

    def to_dict(self) -> dict:
        return {
            "commitments": [c.to_dict() for c in self.commitments],
            "resources": {k: v.to_dict() for k, v in self.resources.items()},
            "external": self.external.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            # User model stored separately
        }

    @classmethod
    def from_dict(cls, data: dict, user_model: 'UserModel' = None) -> 'WorldState':
        return cls(
            user=user_model,
            commitments=[Commitment.from_dict(c) for c in data.get("commitments", [])],
            resources={k: Resource.from_dict(v) for k, v in data.get("resources", {}).items()},
            external=ExternalState.from_dict(data.get("external", {})),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
            version=data.get("version", "1.0"),
        )

    def copy(self) -> 'WorldState':
        """Create a deep copy for simulation."""
        import copy
        return copy.deepcopy(self)

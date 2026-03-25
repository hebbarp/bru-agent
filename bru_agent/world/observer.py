"""
World Observer - Passively observes BRU's actions and updates the world model.

This is Phase 1: The observer watches what happens but doesn't change behavior.
It builds up the world state and learns patterns over time.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from loguru import logger

from .state import WorldState, Commitment, CommitmentSource, CommitmentType, Resource, ExternalState
from .user_model import UserModel, UserModelStore


class WorldObserver:
    """
    Observes BRU's task execution and updates the world model.

    Phase 1 Implementation:
    - Passively watches task starts, completions, and skill usage
    - Updates world state with commitments
    - Learns patterns in UserModel
    - Does NOT affect agent behavior (pure observation)
    """

    def __init__(self,
                 state_path: str = "./data/world_state.json",
                 user_model_path: str = "./data/user_model.json"):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # Load or create user model
        self.user_store = UserModelStore(user_model_path)
        self.user_model = self.user_store.load()

        # Load or create world state
        self.world_state = self._load_state()
        self.world_state.user = self.user_model

        # Track timing for tasks
        self._task_start_times: Dict[str, float] = {}
        self._skill_start_times: Dict[str, float] = {}

        logger.info("WorldObserver initialized")

    def _load_state(self) -> WorldState:
        """Load world state from disk."""
        if self.state_path.exists():
            try:
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                    return WorldState.from_dict(data, self.user_model)
            except Exception as e:
                logger.error(f"Failed to load world state: {e}")
        return WorldState(user=self.user_model)

    def _save_state(self):
        """Save world state to disk."""
        try:
            self.world_state.timestamp = datetime.now()
            with open(self.state_path, 'w') as f:
                json.dump(self.world_state.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save world state: {e}")

    def _save_user_model(self):
        """Save user model to disk."""
        self.user_store.save(self.user_model)

    # ============ Task Lifecycle Events ============

    async def on_task_started(self, task: Dict[str, Any]):
        """
        Called when BRU starts working on a task.

        Creates a Commitment in the world state.
        """
        task_id = str(task.get('id', 'unknown'))
        title = task.get('title', 'Untitled task')

        logger.debug(f"WorldObserver: Task started - #{task_id}: {title}")

        # Record start time for duration tracking
        self._task_start_times[task_id] = time.time()

        # Create commitment
        commitment = Commitment(
            id=f"task_{task_id}",
            title=title,
            source=CommitmentSource.MATSYA_TASK,
            commitment_type=self._classify_task_type(task),
            start_time=datetime.now(),
            importance=self._estimate_importance(task),
            flexibility=0.3,  # Tasks are generally less flexible
            energy_required=self._estimate_energy(task),
            in_progress=True,
            tags=self._extract_tags(task),
        )

        # Add deadline if task has one
        if task.get('due_date'):
            try:
                commitment.deadline = datetime.fromisoformat(task['due_date'])
            except:
                pass

        self.world_state.add_commitment(commitment)
        self._save_state()

        # Update user model
        self.user_model.total_interactions += 1
        self._save_user_model()

    async def on_task_completed(self, task: Dict[str, Any], result: str):
        """
        Called when BRU completes a task.

        Updates the Commitment and learns from the outcome.
        """
        task_id = str(task.get('id', 'unknown'))
        title = task.get('title', 'Untitled task')

        logger.debug(f"WorldObserver: Task completed - #{task_id}: {title}")

        # Calculate duration
        duration_minutes = None
        if task_id in self._task_start_times:
            duration_seconds = time.time() - self._task_start_times[task_id]
            duration_minutes = duration_seconds / 60.0
            del self._task_start_times[task_id]

        # Update commitment
        commitment_id = f"task_{task_id}"
        self.world_state.complete_commitment(commitment_id, duration_minutes)
        self._save_state()

        # Learn from this task
        task_type = self._classify_task_type_str(task)
        if duration_minutes:
            self.user_model.record_task_completion(
                task_type=task_type,
                duration_minutes=duration_minutes,
                success=True  # If we got here, it succeeded
            )
            self._save_user_model()
            logger.debug(f"WorldObserver: Learned - {task_type} task took {duration_minutes:.1f} minutes")

    async def on_task_failed(self, task: Dict[str, Any], error: str):
        """
        Called when a task fails.

        Updates commitment and learns from failure.
        """
        task_id = str(task.get('id', 'unknown'))

        logger.debug(f"WorldObserver: Task failed - #{task_id}: {error[:100]}")

        # Calculate duration
        duration_minutes = None
        if task_id in self._task_start_times:
            duration_seconds = time.time() - self._task_start_times[task_id]
            duration_minutes = duration_seconds / 60.0
            del self._task_start_times[task_id]

        # Mark commitment as not in progress (but not completed)
        commitment = self.world_state.get_commitment(f"task_{task_id}")
        if commitment:
            commitment.in_progress = False
        self._save_state()

        # Learn from failure
        task_type = self._classify_task_type_str(task)
        if duration_minutes:
            self.user_model.record_task_completion(
                task_type=task_type,
                duration_minutes=duration_minutes,
                success=False
            )
            self._save_user_model()

    # ============ Skill Usage Events ============

    async def on_skill_started(self, skill_name: str, params: Dict[str, Any]):
        """Called when a skill execution starts."""
        skill_key = f"{skill_name}_{time.time()}"
        self._skill_start_times[skill_name] = time.time()
        logger.debug(f"WorldObserver: Skill started - {skill_name}")

    async def on_skill_completed(self, skill_name: str, params: Dict[str, Any],
                                  result: Dict[str, Any], success: bool):
        """
        Called when a skill execution completes.

        Learns from skill usage patterns.
        """
        # Calculate duration
        duration_seconds = 0.0
        if skill_name in self._skill_start_times:
            duration_seconds = time.time() - self._skill_start_times[skill_name]
            del self._skill_start_times[skill_name]

        # Learn from this skill use
        self.user_model.record_skill_use(
            skill_name=skill_name,
            params=params,
            success=success,
            duration_seconds=duration_seconds
        )
        self._save_user_model()

        logger.debug(f"WorldObserver: Skill completed - {skill_name} ({'success' if success else 'failed'})")

        # Special handling for certain skills that affect world state
        await self._handle_skill_side_effects(skill_name, params, result, success)

    async def _handle_skill_side_effects(self, skill_name: str, params: Dict[str, Any],
                                          result: Dict[str, Any], success: bool):
        """Handle skills that have side effects on world state."""

        if not success:
            return

        # Email sent -> track communication
        if skill_name == "send_email":
            recipient = params.get('to', '')
            if recipient:
                self._record_contact_interaction(recipient, "email")

        # WhatsApp sent -> track communication
        elif skill_name == "send_whatsapp":
            recipient = params.get('to', '')
            if recipient:
                self._record_contact_interaction(recipient, "whatsapp")

        # Document created -> could track as resource/output
        elif skill_name in ["create_pdf", "create_excel"]:
            # Future: track generated documents
            pass

    def _record_contact_interaction(self, contact_id: str, channel: str):
        """Record an interaction with a contact."""
        if contact_id not in self.user_model.contacts:
            self.user_model.contacts[contact_id] = {
                "name": contact_id,  # Will be updated if we learn the name
                "interactions": 0,
            }

        self.user_model.contacts[contact_id]["interactions"] = \
            self.user_model.contacts[contact_id].get("interactions", 0) + 1
        self.user_model.contacts[contact_id]["last_interaction"] = datetime.now().isoformat()
        self.user_model.contacts[contact_id]["last_channel"] = channel

        self._save_user_model()

    # ============ Console/Chat Events ============

    async def on_console_message(self, message: str, user_name: str):
        """Called when a console message is received."""
        self.user_model.total_interactions += 1
        self._save_user_model()
        logger.debug(f"WorldObserver: Console message from {user_name}")

    async def on_mention(self, task_id: str, message: str, user_name: str):
        """Called when BRU is mentioned in a comment."""
        self.user_model.total_interactions += 1
        self._save_user_model()
        logger.debug(f"WorldObserver: Mention in task #{task_id} from {user_name}")

    # ============ Helper Methods ============

    def _classify_task_type(self, task: Dict[str, Any]) -> CommitmentType:
        """Classify task into commitment type."""
        title = task.get('title', '').lower()
        description = task.get('description', '').lower()
        task_type = task.get('task_type', '').lower()

        if task_type == 'meeting' or 'meeting' in title:
            return CommitmentType.MEETING
        elif 'deadline' in title or 'due' in title:
            return CommitmentType.DEADLINE
        elif 'reminder' in title:
            return CommitmentType.REMINDER
        else:
            return CommitmentType.TASK

    def _classify_task_type_str(self, task: Dict[str, Any]) -> str:
        """Classify task into string type for learning."""
        title = task.get('title', '').lower()
        description = task.get('description', '').lower()
        combined = f"{title} {description}"

        if any(kw in combined for kw in ['research', 'find', 'search', 'look up']):
            return "research"
        elif any(kw in combined for kw in ['document', 'report', 'pdf', 'write']):
            return "document"
        elif any(kw in combined for kw in ['email', 'send', 'message']):
            return "email"
        elif any(kw in combined for kw in ['code', 'fix', 'bug', 'implement', 'build']):
            return "code"
        elif any(kw in combined for kw in ['meeting', 'call', 'schedule']):
            return "meeting"
        else:
            return "general"

    def _estimate_importance(self, task: Dict[str, Any]) -> float:
        """Estimate task importance (0-1)."""
        priority = task.get('priority', 'medium').lower()
        priority_map = {
            'critical': 1.0,
            'high': 0.8,
            'medium': 0.5,
            'low': 0.3,
        }
        return priority_map.get(priority, 0.5)

    def _estimate_energy(self, task: Dict[str, Any]) -> float:
        """Estimate cognitive energy required (0-1)."""
        # Simple heuristic based on description length and type
        description = task.get('description', '')
        base_energy = 0.5

        # Longer descriptions = more complex
        if len(description) > 500:
            base_energy += 0.2
        elif len(description) > 200:
            base_energy += 0.1

        # Certain keywords suggest higher complexity
        complex_keywords = ['analyze', 'research', 'implement', 'design', 'architect']
        if any(kw in description.lower() for kw in complex_keywords):
            base_energy += 0.2

        return min(1.0, base_energy)

    def _extract_tags(self, task: Dict[str, Any]) -> List[str]:
        """Extract tags from task."""
        tags = []

        # From explicit tags field
        if task.get('tags'):
            if isinstance(task['tags'], list):
                tags.extend(task['tags'])
            elif isinstance(task['tags'], str):
                tags.extend(task['tags'].split(','))

        # From task type
        if task.get('task_type'):
            tags.append(task['task_type'])

        return [t.strip() for t in tags if t.strip()]

    # ============ State Access ============

    def get_current_state(self) -> WorldState:
        """Get the current world state."""
        # Refresh external state
        self.world_state.external.current_time = datetime.now()
        self.world_state.external.day_of_week = datetime.now().strftime("%A")
        self.world_state.external.is_weekend = datetime.now().weekday() >= 5

        return self.world_state

    def get_user_model(self) -> UserModel:
        """Get the user model."""
        return self.user_model

    def get_active_commitments(self) -> List[Commitment]:
        """Get all active (non-completed) commitments."""
        return self.world_state.active_commitments

    def get_cognitive_load(self) -> float:
        """Get current estimated cognitive load."""
        return self.world_state.cognitive_load

    def get_skill_stats(self) -> Dict[str, Any]:
        """Get skill usage statistics."""
        stats = {}
        for name, pattern in self.user_model.skill_patterns.items():
            stats[name] = {
                "total_uses": pattern.total_uses,
                "success_rate": pattern.successful_uses / max(1, pattern.total_uses),
                "avg_duration_seconds": pattern.average_duration_seconds,
            }
        return stats

    def get_task_stats(self) -> Dict[str, Any]:
        """Get task completion statistics."""
        stats = {}
        for name, pattern in self.user_model.task_patterns.items():
            stats[name] = {
                "samples": pattern.samples,
                "avg_duration_minutes": pattern.average_duration_minutes,
                "success_rate": pattern.success_rate,
            }
        return stats

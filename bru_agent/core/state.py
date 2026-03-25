"""
BRU State Management - Handles agent state persistence and recovery.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from loguru import logger


class StateManager:
    """Manages agent state persistence."""

    def __init__(self, state_file: str = "./data/state.json"):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
        return self._default_state()

    def _default_state(self) -> dict:
        """Return default state structure."""
        return {
            "last_run": None,
            "mode": "active",
            "processed_items": {
                "matsya_todos": [],
                "whatsapp_messages": [],
                "emails": []
            },
            "pending_actions": [],
            "error_count": 0,
            "last_error": None
        }

    def save(self):
        """Persist state to file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a state value."""
        return self.state.get(key, default)

    def set(self, key: str, value: Any):
        """Set a state value and persist."""
        self.state[key] = value
        self.state["last_updated"] = datetime.now().isoformat()
        self.save()

    def mark_processed(self, item_type: str, item_id: str):
        """Mark an item as processed."""
        if item_type in self.state["processed_items"]:
            if item_id not in self.state["processed_items"][item_type]:
                self.state["processed_items"][item_type].append(item_id)
                # Keep only last 1000 items per type
                self.state["processed_items"][item_type] = \
                    self.state["processed_items"][item_type][-1000:]
                self.save()

    def is_processed(self, item_type: str, item_id: str) -> bool:
        """Check if an item has been processed."""
        return item_id in self.state.get("processed_items", {}).get(item_type, [])

    def record_error(self, error: str):
        """Record an error."""
        self.state["error_count"] = self.state.get("error_count", 0) + 1
        self.state["last_error"] = {
            "message": str(error),
            "timestamp": datetime.now().isoformat()
        }
        self.save()

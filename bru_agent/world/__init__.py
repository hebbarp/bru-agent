"""
World Model - LeCun-inspired world model for BRU personal assistant.

This module maintains an abstract representation of the user's life state
and learns to predict outcomes of actions.

Phase 1: Passive observation and state tracking (current)
Phase 2: Advisory mode (coming)
Phase 3: Predictive planning (future)
"""

from .state import WorldState, Commitment, Resource, ExternalState
from .user_model import UserModel
from .observer import WorldObserver

__all__ = [
    'WorldState',
    'Commitment',
    'Resource',
    'ExternalState',
    'UserModel',
    'WorldObserver',
]

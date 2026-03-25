"""
Channels - Multi-channel interface for BRU.

Channels allow users to interact with BRU through different platforms:
- Telegram (implemented)
- WhatsApp (legacy, to be wrapped)
- Slack (planned)
- Cream app (planned)
- CLI (current default)

Each channel translates platform-specific messages to a unified format
that BRU's core can process.
"""

from .base import BaseChannel, IncomingMessage, OutgoingMessage, ConfirmationRequest
from .telegram import TelegramChannel
from .manager import ChannelManager
from .router import ChannelRouter

__all__ = [
    'BaseChannel',
    'IncomingMessage',
    'OutgoingMessage',
    'ConfirmationRequest',
    'TelegramChannel',
    'ChannelManager',
    'ChannelRouter',
]

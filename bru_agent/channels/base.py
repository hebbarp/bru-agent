"""
Base Channel - Abstract interface for all communication channels.

All channels (Telegram, WhatsApp, Slack, etc.) implement this interface
to provide a unified way for BRU to communicate with users.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable, Awaitable
from enum import Enum


class MessageType(Enum):
    """Type of incoming message."""
    TEXT = "text"
    COMMAND = "command"  # /start, /help, etc.
    CALLBACK = "callback"  # Button click
    DOCUMENT = "document"
    IMAGE = "image"
    VOICE = "voice"


@dataclass
class IncomingMessage:
    """
    Unified message format from any channel.

    All channels convert their native message format to this.
    """
    # Identity
    channel: str  # 'telegram', 'whatsapp', 'slack', etc.
    message_id: str

    # Sender
    sender_id: str
    sender_name: str
    sender_username: Optional[str] = None

    # Content
    message_type: MessageType = MessageType.TEXT
    text: str = ""

    # Timing
    timestamp: datetime = field(default_factory=datetime.now)

    # Attachments
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    # Context
    reply_to_message_id: Optional[str] = None
    conversation_id: Optional[str] = None  # For group chats or threads

    # Channel-specific metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # For callback/button responses
    callback_data: Optional[str] = None


@dataclass
class OutgoingMessage:
    """
    Unified response format to any channel.

    BRU creates these, channels convert to their native format.
    """
    # Content
    text: str

    # Target
    recipient_id: str
    conversation_id: Optional[str] = None
    reply_to_message_id: Optional[str] = None

    # Rich content
    attachments: List[Dict[str, Any]] = field(default_factory=list)  # {type, path/url, caption}

    # Interactive elements
    buttons: List[Dict[str, str]] = field(default_factory=list)  # [{label, callback_data}]
    inline_buttons: List[List[Dict[str, str]]] = field(default_factory=list)  # Grid of buttons

    # Formatting
    parse_mode: str = "Markdown"  # 'Markdown', 'HTML', 'Plain'

    # Behavior
    disable_notification: bool = False

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfirmationRequest:
    """
    Request for user confirmation before an action.

    Used for bookings, payments, sends, etc.
    """
    action_id: str
    action_type: str  # 'booking', 'payment', 'send_email', etc.
    description: str
    details: Dict[str, Any] = field(default_factory=dict)

    options: List[Dict[str, str]] = field(default_factory=list)  # [{id, label, description}]

    # Limits
    timeout_seconds: int = 300  # 5 minutes default
    max_amount: Optional[float] = None  # For payment confirmations

    # Callback
    on_confirm: Optional[str] = None  # Callback identifier
    on_cancel: Optional[str] = None


class BaseChannel(ABC):
    """
    Abstract base class for all communication channels.

    Implement this to add a new channel (Telegram, Slack, etc.)
    """

    name: str = "base"

    def __init__(self, config: Dict[str, Any], message_handler: Callable[[IncomingMessage], Awaitable[OutgoingMessage]]):
        """
        Initialize the channel.

        Args:
            config: Channel-specific configuration
            message_handler: Async function to process messages and return responses
        """
        self.config = config
        self.message_handler = message_handler
        self.running = False

        # Pending confirmations
        self._pending_confirmations: Dict[str, ConfirmationRequest] = {}

    @abstractmethod
    async def start(self):
        """Start the channel (connect, start polling/webhooks)."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop the channel gracefully."""
        pass

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> bool:
        """
        Send a message through this channel.

        Args:
            message: The message to send

        Returns:
            True if sent successfully
        """
        pass

    @abstractmethod
    async def send_confirmation(self,
                                recipient_id: str,
                                confirmation: ConfirmationRequest) -> Optional[str]:
        """
        Send a confirmation request and wait for response.

        Args:
            recipient_id: Who to send to
            confirmation: The confirmation request

        Returns:
            The selected option ID, or None if cancelled/timeout
        """
        pass

    async def handle_incoming(self, message: IncomingMessage) -> Optional[OutgoingMessage]:
        """
        Handle an incoming message.

        Routes to message_handler and returns response.
        Override for custom pre/post processing.
        """
        # Check if this is a confirmation response
        if message.callback_data and message.callback_data in self._pending_confirmations:
            return await self._handle_confirmation_response(message)

        # Route to main handler
        return await self.message_handler(message)

    async def _handle_confirmation_response(self, message: IncomingMessage) -> Optional[OutgoingMessage]:
        """Handle a response to a pending confirmation."""
        confirmation = self._pending_confirmations.pop(message.callback_data, None)
        if not confirmation:
            return None

        # The callback_data format: "confirm_{action_id}_{option_id}"
        parts = message.callback_data.split('_')
        if len(parts) >= 3:
            option_id = parts[-1]
            # Store result for retrieval
            confirmation.metadata['response'] = option_id

        return None  # Confirmation handled separately

    def get_channel_info(self) -> Dict[str, Any]:
        """Get information about this channel."""
        return {
            "name": self.name,
            "running": self.running,
            "config": {k: v for k, v in self.config.items() if k not in ['token', 'api_key', 'secret']}
        }

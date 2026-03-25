"""
Channel Manager - Manages multiple communication channels for BRU.

Handles:
- Starting/stopping channels
- Routing messages to BRU core
- Managing channel lifecycle
"""

import asyncio
from typing import Dict, Any, Optional, Callable, Awaitable, List
from loguru import logger

from .base import BaseChannel, IncomingMessage, OutgoingMessage
from .telegram import TelegramChannel, TELEGRAM_AVAILABLE


class ChannelManager:
    """
    Manages all communication channels for BRU.

    Provides a unified interface for:
    - Starting/stopping channels
    - Routing incoming messages to the BRU agent
    - Sending messages through specific channels
    """

    def __init__(self, config: Dict[str, Any], message_handler: Callable[[IncomingMessage], Awaitable[OutgoingMessage]]):
        """
        Initialize the channel manager.

        Args:
            config: Configuration dict with channel settings
            message_handler: Async function to process incoming messages
        """
        self.config = config
        self.message_handler = message_handler
        self.channels: Dict[str, BaseChannel] = {}
        self.running = False

        logger.info("ChannelManager initialized")

    def _init_channels(self):
        """Initialize configured channels."""
        channels_config = self.config.get('channels', {})

        # Telegram
        telegram_config = channels_config.get('telegram', {})
        telegram_token = telegram_config.get('bot_token') or self.config.get('TELEGRAM_BOT_TOKEN')

        if telegram_token and TELEGRAM_AVAILABLE:
            try:
                telegram_config['bot_token'] = telegram_token

                # Add allowed users/chats from config
                telegram_config['allowed_users'] = telegram_config.get('allowed_users', [])
                telegram_config['allowed_chats'] = telegram_config.get('allowed_chats', [])

                self.channels['telegram'] = TelegramChannel(
                    config=telegram_config,
                    message_handler=self.message_handler
                )
                logger.info("Telegram channel configured")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram channel: {e}")
        elif telegram_token and not TELEGRAM_AVAILABLE:
            logger.warning("Telegram token found but python-telegram-bot not installed")

        # Add other channels here as they're implemented
        # Slack, WhatsApp wrapper, etc.

    async def start(self):
        """Start all configured channels."""
        if self.running:
            return

        self._init_channels()

        logger.info(f"Starting {len(self.channels)} channel(s)...")

        for name, channel in self.channels.items():
            try:
                await channel.start()
                logger.info(f"Channel '{name}' started")
            except Exception as e:
                logger.error(f"Failed to start channel '{name}': {e}")

        self.running = True
        logger.info("ChannelManager started")

    async def stop(self):
        """Stop all channels."""
        if not self.running:
            return

        logger.info("Stopping channels...")

        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"Channel '{name}' stopped")
            except Exception as e:
                logger.error(f"Error stopping channel '{name}': {e}")

        self.running = False
        logger.info("ChannelManager stopped")

    async def send_message(self, channel: str, message: OutgoingMessage) -> bool:
        """
        Send a message through a specific channel.

        Args:
            channel: Channel name ('telegram', 'whatsapp', etc.)
            message: Message to send

        Returns:
            True if sent successfully
        """
        if channel not in self.channels:
            logger.warning(f"Channel '{channel}' not found")
            return False

        return await self.channels[channel].send_message(message)

    async def broadcast(self, message: OutgoingMessage, channels: List[str] = None) -> Dict[str, bool]:
        """
        Send a message through multiple channels.

        Args:
            message: Message to send
            channels: List of channel names (all if None)

        Returns:
            Dict of channel -> success status
        """
        target_channels = channels or list(self.channels.keys())
        results = {}

        for channel_name in target_channels:
            if channel_name in self.channels:
                results[channel_name] = await self.send_message(channel_name, message)

        return results

    def get_channel(self, name: str) -> Optional[BaseChannel]:
        """Get a specific channel by name."""
        return self.channels.get(name)

    def list_channels(self) -> List[Dict[str, Any]]:
        """List all channels and their status."""
        return [
            {
                "name": name,
                "running": channel.running,
                "type": channel.__class__.__name__
            }
            for name, channel in self.channels.items()
        ]

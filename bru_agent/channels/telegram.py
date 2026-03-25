"""
Telegram Channel - BRU interface via Telegram Bot.

Users can chat with BRU through Telegram, get responses,
and confirm actions via inline buttons.

Setup:
1. Create a bot via @BotFather on Telegram
2. Get the bot token
3. Add TELEGRAM_BOT_TOKEN to .env
4. Run BRU - it will start polling for messages
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable, Awaitable
from loguru import logger

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed. Run: pip install python-telegram-bot")

from .base import (
    BaseChannel,
    IncomingMessage,
    OutgoingMessage,
    ConfirmationRequest,
    MessageType
)


class TelegramChannel(BaseChannel):
    """
    Telegram bot channel for BRU.

    Features:
    - Text message handling
    - Command handling (/start, /help, /status)
    - Inline button confirmations
    - File/image receiving
    - Markdown formatting
    """

    name = "telegram"

    def __init__(self,
                 config: Dict[str, Any],
                 message_handler: Callable[[IncomingMessage], Awaitable[OutgoingMessage]]):
        super().__init__(config, message_handler)

        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot is required. Run: pip install python-telegram-bot")

        self.bot_token = config.get('bot_token') or config.get('TELEGRAM_BOT_TOKEN')
        if not self.bot_token:
            raise ValueError("Telegram bot token not configured. Set TELEGRAM_BOT_TOKEN in .env")

        # Allowed users (optional security)
        self.allowed_users = config.get('allowed_users', [])  # List of user IDs or usernames
        self.allowed_chats = config.get('allowed_chats', [])  # List of chat IDs

        # Application instance
        self.app: Optional[Application] = None

        # Conversation context (in-memory, could be persisted)
        self._conversations: Dict[str, List[Dict]] = {}  # chat_id -> message history
        self._max_context_messages = 10

        # Pending confirmations with asyncio Events
        self._confirmation_events: Dict[str, asyncio.Event] = {}
        self._confirmation_results: Dict[str, str] = {}

        logger.info("TelegramChannel initialized")

    async def start(self):
        """Start the Telegram bot."""
        if self.running:
            return

        logger.info("Starting Telegram bot...")

        # Build application
        self.app = Application.builder().token(self.bot_token).build()

        # Add handlers
        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(CommandHandler("status", self._handle_status))
        self.app.add_handler(CommandHandler("clear", self._handle_clear))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        self.app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        # Start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

        self.running = True
        logger.info("Telegram bot started successfully")

    async def stop(self):
        """Stop the Telegram bot."""
        if not self.running:
            return

        logger.info("Stopping Telegram bot...")

        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

        self.running = False
        logger.info("Telegram bot stopped")

    def _is_allowed(self, user_id: int, chat_id: int, username: str = None) -> bool:
        """Check if user/chat is allowed to use the bot."""
        # If no restrictions, allow all
        if not self.allowed_users and not self.allowed_chats:
            return True

        # Check user
        if self.allowed_users:
            if user_id in self.allowed_users:
                return True
            if username and username in self.allowed_users:
                return True

        # Check chat
        if self.allowed_chats:
            if chat_id in self.allowed_chats:
                return True

        return False

    def _get_conversation_context(self, chat_id: str) -> List[Dict]:
        """Get conversation history for context."""
        return self._conversations.get(chat_id, [])[-self._max_context_messages:]

    def _add_to_conversation(self, chat_id: str, role: str, content: str):
        """Add a message to conversation history."""
        if chat_id not in self._conversations:
            self._conversations[chat_id] = []

        self._conversations[chat_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

        # Trim to max length
        if len(self._conversations[chat_id]) > self._max_context_messages * 2:
            self._conversations[chat_id] = self._conversations[chat_id][-self._max_context_messages:]

    # ============ Command Handlers ============

    async def _handle_start(self, update: Update, context):
        """Handle /start command."""
        user = update.effective_user

        if not self._is_allowed(user.id, update.effective_chat.id, user.username):
            await update.message.reply_text("Sorry, you're not authorized to use this bot.")
            return

        welcome = f"""👋 Hi {user.first_name}! I'm BRU, your personal AI assistant.

I can help you with:
• Tasks and todos from Matsya
• Creating documents and reports
• Sending emails and messages
• Research and information lookup
• Booking tickets, flights, hotels (coming soon!)

Just send me a message with what you need.

Commands:
/help - Show available commands
/status - Check BRU status
/clear - Clear conversation history"""

        await update.message.reply_text(welcome)
        logger.info(f"Telegram: /start from {user.username or user.id}")

    async def _handle_help(self, update: Update, context):
        """Handle /help command."""
        help_text = """🤖 *BRU Commands*

/start - Start conversation
/help - Show this help
/status - Check BRU status
/clear - Clear conversation history

*What I can do:*
• "List my open tasks" - Show your Matsya tasks
• "Create a PDF report of..." - Generate documents
• "Send an email to..." - Compose and send emails
• "Search for..." - Research topics
• "Remind me to..." - Set reminders

Just describe what you need in natural language!"""

        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def _handle_status(self, update: Update, context):
        """Handle /status command."""
        chat_id = str(update.effective_chat.id)
        context_len = len(self._conversations.get(chat_id, []))

        status = f"""📊 *BRU Status*

• Channel: Telegram ✅
• Conversation context: {context_len} messages
• Your chat ID: `{chat_id}`
• Running: {'Yes' if self.running else 'No'}"""

        await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN)

    async def _handle_clear(self, update: Update, context):
        """Handle /clear command."""
        chat_id = str(update.effective_chat.id)
        self._conversations[chat_id] = []
        await update.message.reply_text("🧹 Conversation history cleared.")
        logger.info(f"Telegram: Cleared context for chat {chat_id}")

    # ============ Message Handlers ============

    async def _handle_message(self, update: Update, context):
        """Handle incoming text messages."""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)

        if not self._is_allowed(user.id, update.effective_chat.id, user.username):
            return

        text = update.message.text
        logger.info(f"Telegram: Message from {user.username or user.id}: {text[:50]}...")

        # Add to conversation context
        self._add_to_conversation(chat_id, "user", text)

        # Create unified message
        incoming = IncomingMessage(
            channel="telegram",
            message_id=str(update.message.message_id),
            sender_id=str(user.id),
            sender_name=user.full_name,
            sender_username=user.username,
            message_type=MessageType.TEXT,
            text=text,
            timestamp=update.message.date,
            conversation_id=chat_id,
            metadata={
                "chat_type": update.effective_chat.type,
                "context": self._get_conversation_context(chat_id)
            }
        )

        # Show typing indicator
        await update.effective_chat.send_action("typing")

        # Process message
        try:
            response = await self.handle_incoming(incoming)

            if response:
                # Add to conversation context
                self._add_to_conversation(chat_id, "assistant", response.text)

                # Send response
                await self._send_telegram_message(update.effective_chat.id, response)

        except Exception as e:
            logger.error(f"Telegram: Error processing message: {e}")
            await update.message.reply_text(
                "Sorry, I encountered an error processing your request. Please try again."
            )

    async def _handle_document(self, update: Update, context):
        """Handle incoming documents."""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)

        if not self._is_allowed(user.id, update.effective_chat.id, user.username):
            return

        document = update.message.document
        caption = update.message.caption or ""

        logger.info(f"Telegram: Document from {user.username or user.id}: {document.file_name}")

        # Create unified message
        incoming = IncomingMessage(
            channel="telegram",
            message_id=str(update.message.message_id),
            sender_id=str(user.id),
            sender_name=user.full_name,
            sender_username=user.username,
            message_type=MessageType.DOCUMENT,
            text=caption,
            timestamp=update.message.date,
            conversation_id=chat_id,
            attachments=[{
                "type": "document",
                "file_id": document.file_id,
                "file_name": document.file_name,
                "mime_type": document.mime_type,
                "file_size": document.file_size
            }],
            metadata={
                "chat_type": update.effective_chat.type,
                "context": self._get_conversation_context(chat_id)
            }
        )

        await update.effective_chat.send_action("typing")

        try:
            response = await self.handle_incoming(incoming)
            if response:
                self._add_to_conversation(chat_id, "assistant", response.text)
                await self._send_telegram_message(update.effective_chat.id, response)
        except Exception as e:
            logger.error(f"Telegram: Error processing document: {e}")
            await update.message.reply_text("Sorry, I couldn't process that document.")

    async def _handle_photo(self, update: Update, context):
        """Handle incoming photos."""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)

        if not self._is_allowed(user.id, update.effective_chat.id, user.username):
            return

        # Get largest photo
        photo = update.message.photo[-1]
        caption = update.message.caption or ""

        logger.info(f"Telegram: Photo from {user.username or user.id}")

        incoming = IncomingMessage(
            channel="telegram",
            message_id=str(update.message.message_id),
            sender_id=str(user.id),
            sender_name=user.full_name,
            sender_username=user.username,
            message_type=MessageType.IMAGE,
            text=caption,
            timestamp=update.message.date,
            conversation_id=chat_id,
            attachments=[{
                "type": "photo",
                "file_id": photo.file_id,
                "width": photo.width,
                "height": photo.height
            }],
            metadata={
                "chat_type": update.effective_chat.type,
                "context": self._get_conversation_context(chat_id)
            }
        )

        await update.effective_chat.send_action("typing")

        try:
            response = await self.handle_incoming(incoming)
            if response:
                self._add_to_conversation(chat_id, "assistant", response.text)
                await self._send_telegram_message(update.effective_chat.id, response)
        except Exception as e:
            logger.error(f"Telegram: Error processing photo: {e}")
            await update.message.reply_text("Sorry, I couldn't process that image.")

    async def _handle_callback(self, update: Update, context):
        """Handle callback queries (button clicks)."""
        query = update.callback_query
        await query.answer()  # Acknowledge the callback

        callback_data = query.data
        user = query.from_user
        chat_id = str(query.message.chat_id)

        logger.info(f"Telegram: Callback from {user.username or user.id}: {callback_data}")

        # Check if this is a confirmation response
        if callback_data.startswith("confirm_"):
            # Extract action_id and option
            parts = callback_data.split("_", 2)
            if len(parts) >= 3:
                action_id = parts[1]
                option = parts[2]

                # Store result and signal event
                if action_id in self._confirmation_events:
                    self._confirmation_results[action_id] = option
                    self._confirmation_events[action_id].set()

                    # Update message to show selection
                    await query.edit_message_text(
                        f"✅ Selected: {option}\n\n{query.message.text}",
                        reply_markup=None
                    )
                    return

        # Regular callback - treat as message
        incoming = IncomingMessage(
            channel="telegram",
            message_id=str(query.message.message_id),
            sender_id=str(user.id),
            sender_name=user.full_name,
            sender_username=user.username,
            message_type=MessageType.CALLBACK,
            text=callback_data,
            conversation_id=chat_id,
            callback_data=callback_data,
            metadata={
                "original_message": query.message.text
            }
        )

        try:
            response = await self.handle_incoming(incoming)
            if response:
                await self._send_telegram_message(int(chat_id), response)
        except Exception as e:
            logger.error(f"Telegram: Error processing callback: {e}")

    # ============ Sending Methods ============

    async def _send_telegram_message(self, chat_id: int, message: OutgoingMessage):
        """Send a message via Telegram."""
        if not self.app:
            return False

        try:
            # Build reply markup if buttons present
            reply_markup = None
            if message.inline_buttons:
                keyboard = []
                for row in message.inline_buttons:
                    keyboard.append([
                        InlineKeyboardButton(btn['label'], callback_data=btn.get('callback_data', btn['label']))
                        for btn in row
                    ])
                reply_markup = InlineKeyboardMarkup(keyboard)
            elif message.buttons:
                keyboard = [[
                    InlineKeyboardButton(btn['label'], callback_data=btn.get('callback_data', btn['label']))
                ] for btn in message.buttons]
                reply_markup = InlineKeyboardMarkup(keyboard)

            # Determine parse mode
            parse_mode = None
            if message.parse_mode == "Markdown":
                parse_mode = ParseMode.MARKDOWN
            elif message.parse_mode == "HTML":
                parse_mode = ParseMode.HTML

            # Send text message
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=message.text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_notification=message.disable_notification
            )

            # Send attachments if any
            for attachment in message.attachments:
                if attachment.get('type') == 'document' and attachment.get('path'):
                    with open(attachment['path'], 'rb') as f:
                        await self.app.bot.send_document(
                            chat_id=chat_id,
                            document=f,
                            caption=attachment.get('caption', '')
                        )
                elif attachment.get('type') == 'photo' and attachment.get('path'):
                    with open(attachment['path'], 'rb') as f:
                        await self.app.bot.send_photo(
                            chat_id=chat_id,
                            photo=f,
                            caption=attachment.get('caption', '')
                        )

            return True

        except Exception as e:
            logger.error(f"Telegram: Failed to send message: {e}")
            return False

    async def send_message(self, message: OutgoingMessage) -> bool:
        """Send a message through Telegram."""
        try:
            chat_id = int(message.recipient_id)
            return await self._send_telegram_message(chat_id, message)
        except ValueError:
            logger.error(f"Telegram: Invalid recipient_id: {message.recipient_id}")
            return False

    async def send_confirmation(self,
                                recipient_id: str,
                                confirmation: ConfirmationRequest) -> Optional[str]:
        """
        Send a confirmation request and wait for response.

        Creates inline buttons for each option and waits for user selection.
        """
        action_id = confirmation.action_id

        # Build confirmation message
        text = f"🔔 *Confirmation Required*\n\n"
        text += f"**{confirmation.action_type.title()}**\n"
        text += f"{confirmation.description}\n\n"

        if confirmation.details:
            for key, value in confirmation.details.items():
                text += f"• {key}: {value}\n"

        if confirmation.max_amount:
            text += f"\n💰 Amount: ₹{confirmation.max_amount:,.2f}\n"

        # Build buttons
        buttons = []
        for option in confirmation.options:
            buttons.append({
                'label': option['label'],
                'callback_data': f"confirm_{action_id}_{option['id']}"
            })

        # Add cancel button
        buttons.append({
            'label': "❌ Cancel",
            'callback_data': f"confirm_{action_id}_cancel"
        })

        # Create message
        message = OutgoingMessage(
            text=text,
            recipient_id=recipient_id,
            buttons=buttons,
            parse_mode="Markdown"
        )

        # Create event for waiting
        event = asyncio.Event()
        self._confirmation_events[action_id] = event

        # Send message
        await self.send_message(message)

        # Wait for response with timeout
        try:
            await asyncio.wait_for(event.wait(), timeout=confirmation.timeout_seconds)
            result = self._confirmation_results.pop(action_id, None)
            return result if result != "cancel" else None
        except asyncio.TimeoutError:
            logger.info(f"Telegram: Confirmation {action_id} timed out")
            return None
        finally:
            self._confirmation_events.pop(action_id, None)
            self._confirmation_results.pop(action_id, None)

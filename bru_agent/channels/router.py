"""
Channel Router - Routes channel messages to BRU's core processing.

This bridges the gap between the unified channel interface and
BRU's existing task/chat processing logic.
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from loguru import logger

from .base import IncomingMessage, OutgoingMessage, MessageType


class ChannelRouter:
    """
    Routes incoming channel messages to BRU's processing.

    Handles:
    - Converting channel messages to BRU context format
    - Calling Claude for processing
    - Converting responses back to channel format
    """

    def __init__(self, agent):
        """
        Initialize the router.

        Args:
            agent: BruAgent instance
        """
        self.agent = agent
        self.skill_registry = agent.skill_registry
        self.claude = agent.claude
        self.matsya_client = agent.matsya_client

        # World observer (if available)
        self.world_observer = getattr(agent, 'world_observer', None)

        logger.info("ChannelRouter initialized")

    async def route_message(self, message: IncomingMessage) -> OutgoingMessage:
        """
        Route an incoming message to BRU processing.

        Args:
            message: Unified incoming message from any channel

        Returns:
            Response message to send back
        """
        try:
            # Log to world observer
            if self.world_observer:
                try:
                    await self.world_observer.on_console_message(
                        message.text,
                        message.sender_name
                    )
                except Exception as e:
                    logger.debug(f"World observer error: {e}")

            # Handle based on message type
            if message.message_type == MessageType.COMMAND:
                return await self._handle_command(message)
            elif message.message_type == MessageType.CALLBACK:
                return await self._handle_callback(message)
            elif message.message_type in [MessageType.DOCUMENT, MessageType.IMAGE]:
                return await self._handle_attachment(message)
            else:
                return await self._handle_text(message)

        except Exception as e:
            logger.error(f"Error routing message: {e}")
            return OutgoingMessage(
                text="Sorry, I encountered an error processing your message. Please try again.",
                recipient_id=message.sender_id
            )

    async def _handle_text(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle a text message by processing with Claude."""
        if not self.claude:
            return OutgoingMessage(
                text="I'm not configured properly. Please check the API settings.",
                recipient_id=message.sender_id
            )

        # Build system prompt
        system_prompt = self._build_system_prompt(message)

        # Build messages with context
        messages = self._build_messages(message)

        # Get available tools
        tools = self.skill_registry.get_tool_specs() if self.skill_registry else []

        try:
            # Call Claude API
            api_params = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2048,
                "system": system_prompt,
                "messages": messages
            }

            if tools:
                api_params["tools"] = tools

            response = self.claude.messages.create(**api_params)

            # Handle tool use with agentic loop
            max_iterations = 5
            iteration = 0

            while response.stop_reason == "tool_use" and iteration < max_iterations:
                iteration += 1
                tool_results = []
                assistant_content = response.content

                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_use_id = block.id

                        logger.info(f"Channel: Executing tool {tool_name}")

                        # Execute skill
                        result = await self.skill_registry.execute(tool_name, tool_input)

                        # Log to world observer
                        if self.world_observer:
                            try:
                                success = result.get('status') != 'error' if isinstance(result, dict) else True
                                await self.world_observer.on_skill_completed(
                                    tool_name, tool_input, result, success
                                )
                            except Exception as e:
                                logger.debug(f"World observer error: {e}")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(result)
                        })

                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})

                api_params["messages"] = messages
                response = self.claude.messages.create(**api_params)

            # Extract final text
            final_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    final_text += block.text

            return OutgoingMessage(
                text=final_text or "I processed your request.",
                recipient_id=message.sender_id,
                conversation_id=message.conversation_id
            )

        except Exception as e:
            logger.error(f"Claude API error in channel: {e}")
            return OutgoingMessage(
                text=f"Sorry, I encountered an error: {str(e)[:100]}",
                recipient_id=message.sender_id
            )

    async def _handle_command(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle a command message."""
        # Commands are handled by the channel itself
        # This is for any custom command routing
        return await self._handle_text(message)

    async def _handle_callback(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle a callback (button click)."""
        # Treat callback data as a message
        text_message = IncomingMessage(
            channel=message.channel,
            message_id=message.message_id,
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            sender_username=message.sender_username,
            message_type=MessageType.TEXT,
            text=message.callback_data or message.text,
            conversation_id=message.conversation_id,
            metadata=message.metadata
        )
        return await self._handle_text(text_message)

    async def _handle_attachment(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle a message with attachment."""
        # For now, acknowledge and process caption
        attachment_types = [a.get('type', 'file') for a in message.attachments]

        if message.text:
            # Process caption as instruction
            enhanced_text = f"[User sent: {', '.join(attachment_types)}]\n\nUser's message: {message.text}"
            text_message = IncomingMessage(
                channel=message.channel,
                message_id=message.message_id,
                sender_id=message.sender_id,
                sender_name=message.sender_name,
                message_type=MessageType.TEXT,
                text=enhanced_text,
                conversation_id=message.conversation_id,
                metadata=message.metadata
            )
            return await self._handle_text(text_message)
        else:
            return OutgoingMessage(
                text=f"I received your {', '.join(attachment_types)}. What would you like me to do with it?",
                recipient_id=message.sender_id
            )

    def _build_system_prompt(self, message: IncomingMessage) -> str:
        """Build system prompt for channel chat."""
        channel_name = message.channel.title()

        return f"""You are BRU (Bot for Routine Undertakings), a helpful AI assistant.
You're chatting with {message.sender_name} via {channel_name}.

You can help with:
- Managing tasks and todos in Matsya
- Creating documents, PDFs, and reports
- Sending emails and messages
- Searching for information
- General questions and assistance

Available tools (use when needed):
- matsya_list_tasks: Get tasks from Matsya
- matsya_list_todos: Get daily todos
- matsya_search: Search Matsya
- create_pdf: Create PDF documents
- create_excel: Create spreadsheets
- send_email: Send emails
- web_search: Search the internet
- web_fetch: Fetch web pages

Be conversational, helpful, and concise. Use tools when the user asks you to do something actionable.
For simple questions, just answer directly.

Format responses nicely for {channel_name} (use markdown where appropriate)."""

    def _build_messages(self, message: IncomingMessage) -> List[Dict[str, Any]]:
        """Build message history for Claude."""
        messages = []

        # Add context from conversation history
        context = message.metadata.get('context', [])
        for ctx_msg in context[-5:]:  # Last 5 messages
            role = ctx_msg.get('role', 'user')
            content = ctx_msg.get('content', '')
            if role in ['user', 'assistant'] and content:
                messages.append({"role": role, "content": content})

        # Add current message
        messages.append({"role": "user", "content": message.text})

        return messages

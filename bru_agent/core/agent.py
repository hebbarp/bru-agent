"""
BRU Agent - Main agent loop that orchestrates all operations.
"""

import asyncio
import os
import json
import aiohttp
from loguru import logger
from typing import Optional, Dict, Any, List
from enum import Enum
from anthropic import Anthropic
from pathlib import Path

from bru_agent.matsya.client import MatsyaClient
from bru_agent.core.ledger import ActionLedger
from bru_agent.skills.registry import SkillRegistry

# World Model (Phase 1 - Passive Observer)
try:
    from bru_agent.world.observer import WorldObserver
    WORLD_MODEL_AVAILABLE = True
except ImportError:
    WORLD_MODEL_AVAILABLE = False

# Communication Channels
try:
    from bru_agent.channels.manager import ChannelManager
    from bru_agent.channels.router import ChannelRouter
    CHANNELS_AVAILABLE = True
except ImportError:
    CHANNELS_AVAILABLE = False


class AgentMode(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    LEARNING_ONLY = "learning_only"


class BruAgent:
    """Main BRU agent that coordinates all modules."""

    def __init__(self, config: dict):
        self.config = config
        self.mode = AgentMode.ACTIVE
        self.running = False
        self.current_task_id: Optional[int] = None

        # Module instances (initialized later)
        self.matsya_client: Optional[MatsyaClient] = None
        self.whatsapp_client = None
        self.email_client = None
        self.skill_registry: Optional[SkillRegistry] = None
        self.preference_learner = None

        # World Model Observer (Phase 1 - passive observation)
        self.world_observer = None
        if WORLD_MODEL_AVAILABLE:
            try:
                self.world_observer = WorldObserver()
                logger.info("World model observer initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize world observer: {e}")

        # Communication Channels (Telegram, Slack, etc.)
        self.channel_manager = None
        self.channel_router = None

        # Claude API client
        self.claude: Optional[Anthropic] = None

        # Output directory for generated files
        self.output_dir = Path(config.get('output_dir', './output'))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Autonomy level (from BRU_AUTONOMY env var or config)
        self.autonomy = os.getenv('BRU_AUTONOMY', 'supervised').strip("'\"").lower()
        if self.autonomy not in ('full', 'supervised', 'cautious'):
            self.autonomy = 'supervised'
        logger.info(f"Autonomy level: {self.autonomy}")

        # Timing
        self.heartbeat_interval = 60  # seconds
        self.poll_interval = config.get('matsya', {}).get('poll_interval_seconds', 60)
        self._last_heartbeat = 0

    async def initialize(self):
        """Initialize all modules."""
        logger.info("Initializing BRU agent...")

        # Initialize Matsya client
        matsya_config = self.config.get('matsya', {})
        if matsya_config.get('api_key'):
            self.matsya_client = MatsyaClient(matsya_config)
            logger.info("Matsya client initialized")
        else:
            logger.warning("Matsya API key not configured")

        # Initialize Claude API (direct mode with user's API key)
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if api_key:
            self.claude = Anthropic(api_key=api_key)
            logger.info("Claude API initialized")
        else:
            logger.warning("ANTHROPIC_API_KEY not set - task execution disabled")

        # Initialize skill registry
        skill_config = {
            'auto_discover': True,
            'skills_directory': './skills',
            'output_dir': str(self.output_dir),
            'email': self.config.get('email', {}),
            'whatsapp': self.config.get('whatsapp', {})
        }
        self.skill_registry = SkillRegistry(skill_config)
        self.skill_registry.discover()

        # Set Matsya client on upload skills if available
        if self.matsya_client:
            upload_skill = self.skill_registry.get('upload_to_task')
            if upload_skill:
                upload_skill.set_matsya_client(self.matsya_client)

            workspace_upload_skill = self.skill_registry.get('upload_to_workspace')
            if workspace_upload_skill:
                workspace_upload_skill.set_matsya_client(self.matsya_client)

        logger.info(f"Skills registered: {[s['name'] for s in self.skill_registry.list_skills()]}")

        # Initialize communication channels
        if CHANNELS_AVAILABLE:
            try:
                channels_config = self.config.get('channels', {})
                # Add env vars to config
                channels_config['TELEGRAM_BOT_TOKEN'] = os.getenv('TELEGRAM_BOT_TOKEN')

                if channels_config.get('enabled', True):
                    self.channel_router = ChannelRouter(self)
                    self.channel_manager = ChannelManager(
                        config=channels_config,
                        message_handler=self.channel_router.route_message
                    )
                    logger.info("Channel manager initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize channels: {e}")

        # Initialize email client
        email_config = self.config.get('email', {})
        email_address = os.getenv('BRU_EMAIL_ADDRESS', email_config.get('email_address', ''))
        email_password = os.getenv('BRU_EMAIL_PASSWORD', email_config.get('password', ''))
        imap_server = os.getenv('BRU_IMAP_SERVER', email_config.get('imap_server', ''))

        if email_address and email_password and imap_server:
            try:
                from bru_agent.mail_client.client import EmailClient
                import yaml

                # Load authorized senders
                authorized_senders = []
                authorized_domains = []
                try:
                    with open('authorized_senders.yaml', 'r') as f:
                        auth_config = yaml.safe_load(f) or {}
                        authorized_senders = auth_config.get('senders', []) or []
                        authorized_domains = auth_config.get('domains', []) or []
                except FileNotFoundError:
                    logger.warning("authorized_senders.yaml not found — all emails will be ignored")

                email_full_config = {
                    'imap_server': imap_server,
                    'imap_port': int(os.getenv('BRU_IMAP_PORT', email_config.get('imap_port', 993))),
                    'smtp_server': os.getenv('BRU_SMTP_SERVER', email_config.get('smtp_server', '')),
                    'smtp_port': int(os.getenv('BRU_SMTP_PORT', email_config.get('smtp_port', 587))),
                    'email_address': email_address,
                    'password': email_password,
                }
                self.email_client = EmailClient(email_full_config, authorized_senders, authorized_domains)
                connected = await self.email_client.connect()
                if connected:
                    logger.info(f"Email client initialized ({email_address}, {len(authorized_senders)} senders, {len(authorized_domains)} domains)")
                else:
                    logger.warning("Email client failed to connect — disabling email channel")
                    self.email_client = None
            except Exception as e:
                logger.warning(f"Failed to initialize email client: {e}")
                self.email_client = None
        else:
            if email_address or imap_server:
                logger.info("Email partially configured — set BRU_EMAIL_ADDRESS, BRU_EMAIL_PASSWORD, BRU_IMAP_SERVER")

        logger.info("BRU agent initialized")

    async def run(self):
        """Main agent loop."""
        self.running = True
        logger.info("BRU agent starting main loop")

        # Send initial heartbeat
        await self._send_heartbeat()

        # Start communication channels (Telegram, etc.)
        if self.channel_manager:
            try:
                await self.channel_manager.start()
                logger.info("Communication channels started")
            except Exception as e:
                logger.error(f"Failed to start channels: {e}")

        while self.running:
            try:
                # Send heartbeat periodically
                await self._send_heartbeat()

                # Check if paused via Matsya
                await self._check_pause_status()

                if self.mode == AgentMode.PAUSED:
                    logger.debug("Agent is paused, waiting...")
                    await asyncio.sleep(10)
                    continue

                # Check for BRU tasks from Matsya
                await self._check_bru_tasks()

                # Check BRU queue for documents and messages
                await self._check_bru_queue()

                # Check BRU Console for direct user messages
                await self._check_console_messages()

                # Check for @BRU mentions in task comments
                await self._check_comment_mentions()

                # Run other checks concurrently
                await asyncio.gather(
                    self._check_whatsapp(),
                    self._check_email(),
                )

                # Wait before next poll cycle
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(10)

    async def _send_heartbeat(self):
        """Send heartbeat to Matsya."""
        import time
        now = time.time()
        if now - self._last_heartbeat < self.heartbeat_interval:
            return

        if self.matsya_client:
            success = await self.matsya_client.send_heartbeat()
            if success:
                logger.debug("Heartbeat sent to Matsya")
                self._last_heartbeat = now
            else:
                logger.warning("Failed to send heartbeat")

    async def _check_pause_status(self):
        """Check Matsya for pause/resume commands."""
        if not self.matsya_client:
            return

        status = await self.matsya_client.get_agent_status()
        if status == "paused":
            if self.mode != AgentMode.PAUSED:
                self.mode = AgentMode.PAUSED
                logger.info("Agent paused via Matsya")
        elif status == "disabled":
            if self.mode != AgentMode.PAUSED:
                self.mode = AgentMode.PAUSED
                logger.info("Agent disabled via Matsya")
        else:
            if self.mode == AgentMode.PAUSED:
                self.mode = AgentMode.ACTIVE
                logger.info("Agent resumed via Matsya")

    async def _check_bru_tasks(self):
        """Check and process BRU-enabled tasks from Matsya."""
        if not self.matsya_client:
            return

        # Don't pick up new tasks if already working on one
        if self.current_task_id:
            return

        try:
            tasks = await self.matsya_client.get_pending_bru_tasks()
            if not tasks:
                return

            # Process highest priority task
            task = tasks[0]
            logger.info(f"Found BRU task: #{task['id']} - {task['title']}")
            await self._process_bru_task(task)

        except Exception as e:
            logger.error(f"Error checking BRU tasks: {e}")

    async def _process_bru_task(self, task: Dict[str, Any]):
        """Process a BRU task using Claude."""
        task_id = task['id']
        self.current_task_id = task_id

        try:
            # Mark task as started
            await self.matsya_client.bru_start_task(task_id)
            await self.matsya_client.log_agent_activity("started", f"Starting work on: {task['title']}", task_id)

            # World Model: Observe task start (non-blocking)
            if self.world_observer:
                try:
                    await self.world_observer.on_task_started(task)
                except Exception as e:
                    logger.debug(f"World observer error (task start): {e}")

            # Get full task details
            full_task = await self.matsya_client.get_task(task_id)
            if not full_task:
                raise Exception("Failed to get task details")

            # Get task attachments
            attachments = await self.matsya_client.get_task_attachments(task_id)
            full_task['attachments'] = attachments
            if attachments:
                logger.info(f"Task #{task_id} has {len(attachments)} attachment(s)")

            # Build context for Claude
            context = self._build_task_context(full_task)

            # Execute task with Claude
            logger.info(f"Calling Claude API for task #{task_id}...")
            result = await self._execute_with_claude(context, full_task)
            logger.info(f"Claude response received ({len(result)} chars)")
            logger.debug(f"Result preview: {result[:200]}...")

            # Mark task as completed
            logger.info(f"Marking task #{task_id} as completed...")
            complete_success = await self.matsya_client.bru_complete_task(task_id, result)
            logger.info(f"Complete task result: {complete_success}")

            await self.matsya_client.log_agent_activity("completed", result[:200] if result else "Task completed", task_id)

            # Add completion comment to task
            logger.info(f"Posting comment to task #{task_id}...")
            comment_id = await self.matsya_client.add_task_comment(task_id, f"[BRU] Task completed.\n\n{result}")
            logger.info(f"Comment posted, ID: {comment_id}")

            logger.info(f"BRU task #{task_id} completed successfully")

            # World Model: Observe task completion (non-blocking)
            if self.world_observer:
                try:
                    await self.world_observer.on_task_completed(full_task, result)
                except Exception as e:
                    logger.debug(f"World observer error (task complete): {e}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"BRU task #{task_id} failed: {error_msg}")

            if self.matsya_client:
                await self.matsya_client.bru_fail_task(task_id, error_msg)
                await self.matsya_client.log_agent_activity("failed", error_msg[:200], task_id)

            # World Model: Observe task failure (non-blocking)
            if self.world_observer:
                try:
                    await self.world_observer.on_task_failed(task, error_msg)
                except Exception as obs_e:
                    logger.debug(f"World observer error (task fail): {obs_e}")

        finally:
            self.current_task_id = None

    # ============ BRU QUEUE (Documents & Messages) ============

    async def _check_bru_queue(self):
        """Check and process items from BRU queue (documents, messages)."""
        if not self.matsya_client:
            return

        # Don't pick up new items if already working on something
        if self.current_task_id:
            return

        try:
            items = await self.matsya_client.get_pending_queue_items()
            if not items:
                return

            # Process first pending item
            item = items[0]
            item_type = item.get('item_type', 'unknown')
            queue_id = item.get('id')

            logger.info(f"Found BRU queue item: #{queue_id} - type: {item_type}")

            if item_type == 'document':
                await self._process_document_queue_item(item)
            elif item_type == 'message':
                await self._process_message_queue_item(item)
            elif item_type == 'task':
                # Check for specialized task types via reference_type
                reference_type = item.get('reference_type')

                if reference_type == 'mca_audit':
                    # MCA Audit - run audit rules
                    await self._process_mca_audit_item(item)
                else:
                    # Regular task queue items - get the task and process it
                    task_id = item.get('task_id')
                    if task_id:
                        task = await self.matsya_client.get_task(task_id)
                        if task:
                            await self._process_bru_task(task)
                            await self.matsya_client.complete_queue_item(queue_id, "Task processed")

        except Exception as e:
            logger.error(f"Error checking BRU queue: {e}")

    async def _process_document_queue_item(self, item: Dict[str, Any]):
        """Process a document queue item."""
        queue_id = item.get('id')
        document_id = item.get('document_id')
        instructions = item.get('instructions', '')
        document_title = item.get('document_title', 'Untitled')
        file_path = item.get('file_path', '')
        user_id = item.get('user_id')

        self.current_task_id = f"doc_{queue_id}"  # Use as lock

        try:
            # Mark as processing
            await self.matsya_client.update_queue_item(queue_id, "processing")
            logger.info(f"Processing document: {document_title} (ID: {document_id})")

            # Download the document to local temp path
            import tempfile
            import os
            from pathlib import Path

            # Get file extension from original path
            ext = Path(file_path).suffix if file_path else '.txt'
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            temp_path = temp_file.name
            temp_file.close()

            # Download the document
            download_success = await self.matsya_client.download_document(document_id, temp_path)

            if not download_success:
                raise Exception(f"Failed to download document {document_id}")

            # Read document content (for text-based files)
            document_content = ""
            try:
                with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
                    document_content = f.read()[:50000]  # Limit to 50k chars
            except Exception as e:
                logger.warning(f"Could not read document as text: {e}")
                document_content = f"[Binary file: {document_title}]"

            # Build context for Claude
            context = f"""Document: {document_title}
Document ID: {document_id}
File Path: {file_path}

Instructions from user:
{instructions if instructions else 'Please analyze this document and provide insights.'}

Document Content:
{document_content}
"""

            # Execute with Claude
            result = await self._execute_document_with_claude(context, item)

            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

            # Mark as completed
            await self.matsya_client.complete_queue_item(queue_id, result)
            logger.info(f"Document queue item #{queue_id} completed")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Document queue item #{queue_id} failed: {error_msg}")
            await self.matsya_client.fail_queue_item(queue_id, error_msg)

        finally:
            self.current_task_id = None

    async def _process_mca_audit_item(self, item: Dict[str, Any]):
        """Process an MCA audit queue item - run audit rules against trial balance."""
        queue_id = item.get('id')
        reference_id = item.get('reference_id')  # This is the audit_id
        content = item.get('content', '{}')
        user_id = item.get('user_id')
        title = item.get('title', 'MCA Audit')

        self.current_task_id = f"mca_audit_{queue_id}"

        try:
            # Parse content for audit details
            import json
            audit_info = json.loads(content) if isinstance(content, str) else content
            audit_id = audit_info.get('audit_id') or reference_id

            if not audit_id:
                raise ValueError("No audit_id found in queue item")

            logger.info(f"Starting MCA audit #{audit_id} from queue item #{queue_id}")

            # Mark as processing
            await self.matsya_client.update_queue_item(queue_id, "processing", None)

            # Execute the MCA audit skill
            result = await self.skill_registry.execute("mca_audit_run", {
                "audit_id": audit_id
            })

            if result.get("success"):
                summary = result.get("summary", "Audit completed")
                findings_count = result.get("findings_count", 0)

                # Complete the queue item
                await self.matsya_client.complete_queue_item(queue_id, summary)

                # Send notification to user
                if user_id:
                    await self.matsya_client.send_direct_message(
                        user_id,
                        f"**MCA Audit Complete**\n\n{summary}"
                    )

                logger.info(f"MCA audit #{audit_id} completed with {findings_count} findings")
            else:
                error = result.get("error", "Unknown error")
                await self.matsya_client.fail_queue_item(queue_id, error)
                logger.error(f"MCA audit #{audit_id} failed: {error}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"MCA audit queue item #{queue_id} failed: {error_msg}")
            await self.matsya_client.fail_queue_item(queue_id, error_msg)

        finally:
            self.current_task_id = None

    async def _process_message_queue_item(self, item: Dict[str, Any]):
        """Process a message queue item (direct chat with BRU)."""
        queue_id = item.get('id')
        message_content = item.get('message_content', '')
        instructions = item.get('instructions', '')  # May contain conversation history
        user_id = item.get('user_id')

        self.current_task_id = f"msg_{queue_id}"  # Use as lock

        try:
            # Mark as processing
            await self.matsya_client.update_queue_item(queue_id, "processing")
            logger.info(f"Processing message from user {user_id}")

            # Build context - instructions may contain conversation history
            context = instructions if instructions else message_content

            # Execute with Claude
            result = await self._execute_message_with_claude(context, item)

            # Mark as completed - this will send the response back as a direct message
            await self.matsya_client.complete_queue_item(queue_id, result)
            logger.info(f"Message queue item #{queue_id} completed")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Message queue item #{queue_id} failed: {error_msg}")
            await self.matsya_client.fail_queue_item(queue_id, error_msg)

        finally:
            self.current_task_id = None

    async def _execute_document_with_claude(self, context: str, item: Dict[str, Any]) -> str:
        """Execute document analysis with Claude."""
        if not self.claude:
            return "Claude API not configured - set ANTHROPIC_API_KEY"

        system_prompt = """You are BRU, an autonomous AI agent analyzing documents for users.

Your job is to:
1. Read and understand the document content provided
2. Follow the user's instructions about what to do with the document
3. Provide helpful analysis, summaries, or perform requested tasks

If asked to create a new document or modify content, you have access to tools:
- create_pdf: Create a PDF from text/markdown content (PREFERRED - fast Typst engine)
- convert_document: Convert between document formats
- upload_to_workspace: Upload generated files to the workspace

Be helpful, thorough, and directly address what the user asked for."""

        user_message = context

        # Get tools from skill registry
        tools = self.skill_registry.get_tool_specs() if self.skill_registry else []

        messages = [{"role": "user", "content": user_message}]

        try:
            # Simplified execution - just get a response (can add agentic loop if needed)
            api_params = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
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

                        logger.info(f"Executing tool: {tool_name}")
                        result = await self.skill_registry.execute(tool_name, tool_input)
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

            return final_text if final_text else "Document processed successfully."

        except Exception as e:
            logger.error(f"Claude API error for document: {e}")
            raise

    async def _execute_message_with_claude(self, context: str, item: Dict[str, Any]) -> str:
        """Execute message response with Claude."""
        if not self.claude:
            return "Claude API not configured - set ANTHROPIC_API_KEY"

        system_prompt = """You are BRU, a helpful AI assistant. The user is chatting with you directly.

Be conversational, helpful, and friendly. Answer questions, help with tasks, and provide useful information.

You have access to tools if needed:
- matsya_list_tasks: Get tasks from Matsya
- matsya_search: Search for information
- send_email: Send emails
- create_pdf: Create PDFs
- And more...

But for simple conversations, just respond naturally without using tools."""

        user_message = context

        # Get tools (but don't force their use for messages)
        tools = self.skill_registry.get_tool_specs() if self.skill_registry else []

        messages = [{"role": "user", "content": user_message}]

        try:
            api_params = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": messages
            }

            if tools:
                api_params["tools"] = tools

            response = self.claude.messages.create(**api_params)

            # Handle tool use if needed
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

                        logger.info(f"Executing tool: {tool_name}")
                        result = await self.skill_registry.execute(tool_name, tool_input)
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

            return final_text if final_text else "I'm here to help!"

        except Exception as e:
            logger.error(f"Claude API error for message: {e}")
            raise

    # ============ TASK CONTEXT BUILDING ============

    def _build_task_context(self, task: Dict[str, Any]) -> str:
        """Build context string for Claude from task details."""
        context_parts = [
            f"Task: {task.get('title', 'Untitled')}",
            f"Task ID: {task.get('id')}",
            f"Workspace ID: {task.get('workspace_id')}",
            f"Type: {task.get('task_type', 'task')}",
            f"Priority: {task.get('priority', 'medium')}",
        ]

        if task.get('description'):
            context_parts.append(f"\nDescription:\n{task['description']}")

        if task.get('comments'):
            context_parts.append("\nComments:")
            for comment in task['comments'][-5:]:  # Last 5 comments
                context_parts.append(f"- {comment.get('user_name', 'User')}: {comment.get('comment', '')}")

        if task.get('subtasks'):
            context_parts.append("\nSubtasks:")
            for subtask in task['subtasks']:
                status = "[x]" if subtask.get('is_completed') else "[ ]"
                context_parts.append(f"  {status} {subtask.get('title', '')}")

        if task.get('attachments'):
            context_parts.append("\nAttachments:")
            for att in task['attachments']:
                size = self._format_file_size(att.get('file_size', 0))
                context_parts.append(f"  - {att.get('file_name', 'Unknown')} ({size}) [ID: {att.get('id')}]")
            context_parts.append("\n(Use the read_attachment tool with the attachment ID to read contents)")

        return "\n".join(context_parts)

    def _format_file_size(self, size: int) -> str:
        """Format file size in human readable form."""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

    # ============ AUTONOMY CONTROL ============

    # Tools that are always safe (read-only, no side effects)
    READONLY_TOOLS = {
        'read_file', 'glob_search', 'grep_search', 'list_directory',
        'web_search', 'web_fetch', 'read_attachment',
        'matsya_list_tasks', 'matsya_search',
        'list_workspace_documents', 'read_workspace_document',
    }

    # Tools that have external side effects (supervised gates these)
    EXTERNAL_TOOLS = {
        'send_email', 'send_whatsapp',
        'bash_execute', 'run_command',
        'upload_to_workspace', 'upload_to_task',
        'git',  # push/commit could be destructive
    }

    def _check_autonomy(self, tool_name: str, tool_input: Dict[str, Any]) -> tuple:
        """Check if tool execution is allowed under current autonomy level.

        Returns:
            (allowed: bool, reason: str or None)
        """
        if self.autonomy == 'full':
            return True, None

        if self.autonomy == 'cautious':
            # Only allow read-only tools without gating
            if tool_name in self.READONLY_TOOLS:
                return True, None
            return False, f"Cautious mode: '{tool_name}' requires approval"

        # supervised (default)
        if tool_name in self.EXTERNAL_TOOLS:
            # Special case: git read-only commands are OK
            if tool_name == 'git':
                subcmd = tool_input.get('command', tool_input.get('action', '')).lower()
                if subcmd in ('status', 'diff', 'log', 'show', 'branch'):
                    return True, None
            return False, f"Supervised mode: '{tool_name}' requires approval"

        return True, None

    async def _handle_gated_tool(self, tool_name: str, tool_input: Dict, task_id) -> Dict:
        """Handle a tool that needs approval under current autonomy level.

        Posts an approval request to Matsya and polls for user response.
        User approves/rejects via matsyaai.com UI.
        """
        logger.warning(f"AUTONOMY GATE: '{tool_name}' requires approval (autonomy={self.autonomy})")

        # Build a human-readable context string
        context = f"BRU wants to execute '{tool_name}'"
        if tool_name == 'send_email':
            context = f"Send email to {tool_input.get('to', '?')}: {tool_input.get('subject', '')}"
        elif tool_name == 'bash_execute':
            context = f"Run shell command: {str(tool_input.get('command', ''))[:200]}"
        elif tool_name == 'git':
            context = f"Git: {tool_input.get('command', tool_input.get('action', ''))}"
        elif tool_name in ('upload_to_workspace', 'upload_to_task'):
            context = f"Upload file: {tool_input.get('filepath', tool_input.get('filename', '?'))}"
        elif tool_name == 'send_whatsapp':
            context = f"Send WhatsApp to {tool_input.get('to', '?')}"
        elif tool_name == 'write_file':
            context = f"Write file: {tool_input.get('filepath', tool_input.get('path', '?'))}"
        elif tool_name == 'edit_file':
            context = f"Edit file: {tool_input.get('filepath', tool_input.get('path', '?'))}"

        # If no Matsya client, just block
        if not self.matsya_client:
            logger.warning(f"No Matsya client — blocking '{tool_name}'")
            return {
                "status": "blocked",
                "message": f"Tool '{tool_name}' blocked by {self.autonomy} mode. No Matsya connection to request approval."
            }

        # Post approval request to Matsya
        task_id_int = task_id if isinstance(task_id, int) else None
        approval = await self.matsya_client.request_approval(
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            task_id=task_id_int,
            autonomy_level=self.autonomy,
            timeout_seconds=120
        )

        if not approval:
            logger.error("Failed to create approval request")
            return {
                "status": "blocked",
                "message": f"Tool '{tool_name}' blocked — failed to create approval request."
            }

        approval_id = approval['id']
        logger.info(f"Approval #{approval_id} created for '{tool_name}', waiting for user response...")

        if self.matsya_client and task_id_int:
            await self.matsya_client.bru_log_progress(
                task_id_int,
                f"Waiting for approval: {context}"
            )

        # Poll for response (check every 5 seconds, up to 120s)
        import time
        poll_interval = 5
        max_wait = 120
        waited = 0

        while waited < max_wait:
            await asyncio.sleep(poll_interval)
            waited += poll_interval

            status = await self.matsya_client.check_approval(approval_id)
            if status == 'approved':
                logger.info(f"Approval #{approval_id} APPROVED — executing '{tool_name}'")
                if self.matsya_client and task_id_int:
                    await self.matsya_client.bru_log_progress(task_id_int, f"Approved: {tool_name}")
                return {"status": "approved"}
            elif status == 'rejected':
                logger.info(f"Approval #{approval_id} REJECTED — skipping '{tool_name}'")
                return {
                    "status": "blocked",
                    "message": f"User rejected '{tool_name}'. Do not retry this tool — provide a text response instead."
                }
            elif status == 'expired':
                break
            # else still 'pending', keep polling

        logger.warning(f"Approval #{approval_id} expired for '{tool_name}'")
        return {
            "status": "blocked",
            "message": f"Approval timed out for '{tool_name}'. User did not respond within {max_wait}s. Provide a text response instead."
        }

    def _classify_task_type(self, context: str, task: Dict[str, Any]) -> str:
        """Classify task to determine output format.

        Returns:
            'research'    - Research/analysis/investigation -> text result only, NO files
            'writing'     - Content writing/drafting -> clean text, maybe save as note
            'deliverable' - Final document/report/file -> PDF/Excel/file creation
            'action'      - Code changes, emails, commands -> execute and report
        """
        title = task.get('title', '').lower()
        desc = task.get('description', '').lower()
        combined = f"{title} {desc} {context.lower()}"

        # Check if this is a project sub-task (enriched description marker)
        is_project_task = 'BRU PROJECT TASK' in task.get('description', '')

        # Deliverable keywords - explicitly asks for a file/document
        deliverable_kw = [
            'create pdf', 'generate pdf', 'create report', 'generate report',
            'create document', 'generate document', 'create excel', 'generate excel',
            'create spreadsheet', 'final report', 'final document', 'final deliverable',
            'produce a pdf', 'make a pdf', 'write a report', 'compile report',
            'create presentation', 'create letter', 'draft letter'
        ]

        # Research keywords - gathering info, analyzing, investigating
        research_kw = [
            'research', 'investigate', 'analyze', 'find out', 'look into',
            'gather information', 'collect data', 'study', 'explore',
            'what is', 'how does', 'compare', 'evaluate', 'assess',
            'identify', 'list the', 'summarize existing', 'review',
            'understand', 'determine', 'figure out', 'check if',
            'find examples', 'search for', 'discover'
        ]

        # Writing keywords - drafting content (not yet a final file)
        writing_kw = [
            'write content', 'draft', 'outline', 'write section',
            'write copy', 'write text', 'compose', 'prepare content',
            'write article', 'write blog', 'write post'
        ]

        # Action keywords - doing something (code, email, command)
        action_kw = [
            'send email', 'send message', 'run command', 'execute',
            'deploy', 'install', 'build', 'fix bug', 'update code',
            'modify', 'change', 'edit file', 'commit', 'push'
        ]

        # Score each category
        scores = {'deliverable': 0, 'research': 0, 'writing': 0, 'action': 0}

        for kw in deliverable_kw:
            if kw in combined:
                scores['deliverable'] += 2
        for kw in research_kw:
            if kw in combined:
                scores['research'] += 2
        for kw in writing_kw:
            if kw in combined:
                scores['writing'] += 2
        for kw in action_kw:
            if kw in combined:
                scores['action'] += 2

        # For project sub-tasks, check task position hints
        if is_project_task:
            # Early tasks in a project are usually research/planning
            if any(x in combined for x in ['step 1', 'phase 1', 'first task', 'gather', 'collect']):
                scores['research'] += 3
            # Final tasks are usually deliverables
            if any(x in combined for x in ['final', 'compile', 'produce', 'deliver', 'publish']):
                scores['deliverable'] += 3

        # Pick highest score, default to 'action' (general task)
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            if any(ext in combined for ext in ['.pdf', '.xlsx', '.docx', '.csv']):
                best = 'deliverable'
            else:
                best = 'action'

        logger.info(f"Task classified as '{best}' (scores: {scores})")
        return best

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Strip AI thinking/reasoning artifacts from output text.

        Removes:
        - <thinking>...</thinking> blocks
        - <antThinking>...</antThinking> blocks
        - Leading chain-of-thought lines before actual content
        """
        import re

        if not text:
            return text

        # Remove XML-style thinking blocks
        text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
        text = re.sub(r'<antThinking>.*?</antThinking>', '', text, flags=re.DOTALL)
        text = re.sub(r'<reflection>.*?</reflection>', '', text, flags=re.DOTALL)

        # Remove common chain-of-thought prefixes (leading lines only)
        lines = text.split('\n')
        cleaned = []
        skip_cot = True

        cot_patterns = [
            r"^(Let me |I need to |I'll |I should |First,? I|Now,? I|Okay,? |So,? |Hmm|Alright)",
            r"^(Looking at |Thinking about |Considering |To do this|To complete this)",
            r"^(My approach|My plan|Step \d+:)",
        ]
        cot_re = re.compile('|'.join(cot_patterns), re.IGNORECASE)

        for line in lines:
            stripped = line.strip()
            if skip_cot and (not stripped or cot_re.match(stripped)):
                continue
            else:
                skip_cot = False
                cleaned.append(line)

        result = '\n'.join(cleaned).strip()
        return result if result else text.strip()

    def _get_system_prompt(self, task_type: str) -> str:
        """Get task-type-appropriate system prompt for Claude."""

        tools_section = """Available tools:

FILE OPERATIONS:
- read_file: Read contents of any file
- write_file: Create or overwrite a file with new content
- edit_file: Smart find & replace editing (PREFERRED for modifying existing files)
- glob_search: Find files by pattern (e.g., "**/*.py" for all Python files)
- grep_search: Search file contents with regex
- list_directory: List files and folders in a directory

MATSYA INTEGRATION:
- matsya_list_tasks: Get tasks from Matsya (use status="open" for open tasks)
- matsya_search: Search for tasks, todos, or other items in Matsya
- read_attachment: Read task attachment contents
- matsya_add_comment: Add a comment to a task
- list_workspace_documents: List all documents in a workspace
- read_workspace_document: Read contents of a workspace document by ID

DOCUMENT GENERATION:
- create_excel: Create Excel spreadsheet from table data
- create_pdf: Create a PDF from text/markdown content
- convert_document: Convert documents between formats

FILE UPLOAD:
- upload_to_workspace: Upload a file to workspace Documents (returns URL)
- upload_to_task: Upload a file as a task attachment

COMMUNICATION:
- send_email: Send an email
- send_whatsapp: Send a WhatsApp message

SHELL EXECUTION:
- bash_execute: Run ANY shell command
- git: Git operations (status, diff, add, commit, push, pull, etc.)

WEB:
- web_search: Search the web using DuckDuckGo
- web_fetch: Fetch and parse any URL

MEDIA:
- process_image: Process images with ImageMagick
- process_media: Process audio/video with FFmpeg"""

        if task_type == 'research':
            return f"""You are BRU, an autonomous AI agent. You are performing a RESEARCH task.

YOUR OUTPUT RULES FOR THIS TASK:
- DO NOT create PDFs, Excel files, or any documents
- DO NOT use create_pdf, create_excel, or convert_document tools
- Your text response IS the deliverable - write clear, well-structured text
- Use web_search and web_fetch to gather information
- Use read_file, glob_search, grep_search to examine local files
- Synthesize your findings into a clear, concise summary
- Use markdown formatting in your text response for readability

{tools_section}

Be thorough in your research. Return a clean, well-organized text summary. NO files."""

        elif task_type == 'writing':
            return f"""You are BRU, an autonomous AI agent. You are performing a WRITING task.

YOUR OUTPUT RULES FOR THIS TASK:
- DO NOT create PDFs or documents unless explicitly asked
- Write polished, publication-ready content as your text response
- Your text response IS the deliverable - make it clean and professional
- No chain-of-thought or reasoning in your output - just the finished content
- If prior research tasks produced findings, weave them into polished prose

{tools_section}

Write clean, polished content. Your text response is the final output."""

        elif task_type == 'deliverable':
            return f"""You are BRU, an autonomous AI agent. You MUST use your tools to create the final deliverable.

CRITICAL: This task requires producing a FILE (PDF, Excel, etc.). USE the appropriate tool.

{tools_section}

WORKFLOW:
1. Gather any needed data (from Matsya, files, web, or prior task context)
2. Compose the content - clean, polished, professional. NO reasoning or thinking in the content.
3. Choose the right format:
   - For TABLES/DATA: use create_excel
   - For formatted REPORTS/DOCUMENTS: use create_pdf
4. Upload using upload_to_workspace or upload_to_task
5. Post a link via matsya_add_comment if applicable
6. Provide a brief summary

CONTENT QUALITY:
- Write professional, publication-ready content
- NO chain-of-thought, reasoning steps, or "Let me think..." in the document
- NO meta-commentary about the task - just the actual deliverable content
- If using prior task results, integrate them smoothly

Be autonomous. Create a polished deliverable."""

        else:  # 'action'
            return f"""You are BRU, an autonomous AI agent. You MUST use your tools to complete tasks - do not just describe what you would do, actually DO IT.

{tools_section}

IMPORTANT RULES:
- ALWAYS use tools when the task requires action
- NEVER say "I need access" or "please provide data" - use your tools to get the data
- After creating a file, upload it using upload_to_task or upload_to_workspace
- Only create PDFs/documents if the task EXPLICITLY asks for a document/report
- For simple tasks, just do the work and report back in text

Be autonomous. Take action. Complete the task fully."""

    async def _execute_with_claude(self, context: str, task: Dict[str, Any]) -> str:
        """Execute task using Claude API with tools."""
        if not self.claude:
            return "Claude API not configured - set ANTHROPIC_API_KEY"

        # Classify task to determine behavior
        task_type = self._classify_task_type(context, task)
        system_prompt = self._get_system_prompt(task_type)

        user_message = f"""Please help complete this task:

{context}

Task ID: {task['id']}

Provide your response that completes or addresses this task. Use the available tools when appropriate."""

        # Get tools from skill registry
        tools = self.skill_registry.get_tool_specs() if self.skill_registry else []
        logger.info(f"Available tools: {[t['name'] for t in tools]}")

        messages = [{"role": "user", "content": user_message}]

        try:
            # Log task type and that we're calling Claude
            logger.info(f"Task #{task['id']} classified as '{task_type}'")
            if self.matsya_client:
                await self.matsya_client.bru_log_progress(task['id'], f"Analyzing task ({task_type} mode)...")

            # Agentic loop - keep calling Claude until we get a final response
            max_iterations = 10
            iteration = 0

            # Action Ledger — persistent ground truth record of every tool execution
            action_ledger = []
            ledger = ActionLedger(storage_dir=str(self.output_dir.parent / 'data' / 'ledger'))
            ledger.start_session(task.get('title', 'unnamed'), model="claude-sonnet-4-20250514")

            while iteration < max_iterations:
                iteration += 1

                # Build API call parameters
                api_params = {
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": messages
                }

                # Add tools if available
                if tools:
                    api_params["tools"] = tools

                # Force tool use on first iteration for deliverable/action tasks only
                # Research and writing tasks should NOT be forced to use tools
                if iteration == 1 and tools and task_type in ('deliverable', 'action'):
                    task_lower = context.lower()
                    action_keywords = ['create', 'generate', 'make', 'send', 'upload', 'compile', 'convert', 'process', 'list', 'get', 'fetch', 'report', 'pdf', 'table', 'excel', 'spreadsheet', 'find', 'search', 'edit', 'modify', 'update', 'change', 'read', 'write', 'file', 'code', 'run', 'execute', 'build', 'test', 'install', 'git', 'commit', 'push', 'pull', 'deploy']
                    if any(kw in task_lower for kw in action_keywords):
                        api_params["tool_choice"] = {"type": "any"}
                        logger.info(f"Forcing tool use for {task_type} task")

                logger.info(f"Calling AI API (iteration {iteration}), tools: {len(tools)}, tool_choice: {api_params.get('tool_choice', 'auto')}")

                # Call Claude API
                response = self.claude.messages.create(**api_params)

                logger.info(f"AI response - stop_reason: {response.stop_reason}, content_types: {[b.type for b in response.content]}")

                # Check if we need to handle tool calls
                if response.stop_reason == "tool_use":
                    # Process all tool calls in the response
                    tool_results = []
                    assistant_content = response.content

                    for block in response.content:
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_input = block.input
                            tool_use_id = block.id

                            logger.info(f"Executing tool: {tool_name} with input: {tool_input}")

                            # Autonomy gate check
                            allowed, gate_reason = self._check_autonomy(tool_name, tool_input)
                            if not allowed:
                                gate_result = await self._handle_gated_tool(tool_name, tool_input, task['id'])
                                if gate_result.get('status') != 'approved':
                                    # Blocked or timed out — send blocked message to Claude
                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": tool_use_id,
                                        "content": json.dumps(gate_result)
                                    })
                                    continue
                                # Approved — fall through to execute the tool

                            if self.matsya_client:
                                await self.matsya_client.bru_log_progress(
                                    task['id'],
                                    f"Executing: {tool_name}..."
                                )

                            # World Model: Observe skill start (non-blocking)
                            if self.world_observer:
                                try:
                                    await self.world_observer.on_skill_started(tool_name, tool_input)
                                except Exception as obs_e:
                                    logger.debug(f"World observer error (skill start): {obs_e}")

                            # Execute the skill
                            result = await self.skill_registry.execute(tool_name, tool_input)
                            skill_success = result.get('status') != 'error' if isinstance(result, dict) else True

                            # World Model: Observe skill completion (non-blocking)
                            if self.world_observer:
                                try:
                                    await self.world_observer.on_skill_completed(
                                        tool_name, tool_input, result, skill_success
                                    )
                                except Exception as obs_e:
                                    logger.debug(f"World observer error (skill complete): {obs_e}")

                            logger.info(f"Tool {tool_name} result: {result}")

                            # Record in Action Ledger (ground truth)
                            tool_success = result.get('success', skill_success) if isinstance(result, dict) else skill_success
                            tool_error = result.get('error', '') if isinstance(result, dict) else ''
                            tool_msg = result.get('result', {}).get('message', '') if isinstance(result, dict) and tool_success else tool_error
                            action_ledger.append({
                                'tool': tool_name,
                                'input_summary': str(tool_input)[:150],
                                'success': tool_success,
                                'result_summary': str(tool_msg)[:200],
                            })

                            # Persist to file-based ledger
                            target = str(tool_input)[:80] if isinstance(tool_input, str) else str(tool_input.get('to', tool_input.get('filepath', tool_input.get('query', ''))))[:80]
                            ledger.record(tool_name, target, tool_success, str(tool_msg)[:200])

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps(result)
                            })

                    # Add assistant message and tool results to conversation
                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append({"role": "user", "content": tool_results})

                else:
                    # No more tool calls - extract final text response
                    final_text = ""
                    for block in response.content:
                        if hasattr(block, 'text'):
                            final_text += block.text

                    # ---- Verification Pass ----
                    # If any tool failed, force Claude to reconcile claims with ground truth
                    has_failures = any(not a['success'] for a in action_ledger)
                    if action_ledger and has_failures:
                        logger.info(f"Verification Pass: {len(action_ledger)} actions, "
                                    f"{sum(1 for a in action_ledger if not a['success'])} failures")

                        ledger_lines = []
                        for entry in action_ledger:
                            status = "SUCCESS" if entry['success'] else "FAILED"
                            line = f"- {entry['tool']}({entry['input_summary'][:80]}): {status}"
                            if not entry['success']:
                                line += f" -- {entry['result_summary']}"
                            ledger_lines.append(line)

                        verify_msg = (
                            "VERIFICATION REQUIRED -- Review the actual results of your actions:\n\n"
                            + "\n".join(ledger_lines)
                            + "\n\nFor FAILED actions, report the failure honestly. "
                            "Do NOT claim they succeeded. Rewrite your response."
                        )

                        messages.append({"role": "assistant", "content": [{"type": "text", "text": final_text}]})
                        messages.append({"role": "user", "content": verify_msg})

                        try:
                            verify_resp = self.claude.messages.create(
                                model="claude-sonnet-4-20250514",
                                max_tokens=2048,
                                system=system_prompt,
                                messages=messages,
                            )
                            for vblock in verify_resp.content:
                                if hasattr(vblock, 'text'):
                                    final_text = vblock.text
                                    break
                            logger.info("Verification Pass: response corrected")
                            ledger.record_verification(True, "corrected")
                        except Exception as ve:
                            logger.error(f"Verification Pass failed: {ve}")
                            failed_names = [a['tool'] for a in action_ledger if not a['success']]
                            final_text += f"\n\nNote: These actions failed: {', '.join(failed_names)}"
                            ledger.record_verification(True, "fallback warning appended")
                    else:
                        ledger.record_verification(False)

                    # Strip thinking/reasoning artifacts from output
                    final_text = self._strip_thinking(final_text)

                    # Save ledger to disk for audit
                    ledger.close()

                    return final_text if final_text else "Task completed successfully."

            ledger.close()
            return "Task processing exceeded maximum iterations."

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            import traceback
            traceback.print_exc()
            raise Exception(f"Claude API error: {e}")

    async def _check_whatsapp(self):
        """Check and respond to WhatsApp messages."""
        if not self.whatsapp_client:
            return

        # TODO: Implement when WhatsApp client is ready
        pass

    async def _check_email(self):
        """Check and respond to emails from authorized senders."""
        if not self.email_client:
            return

        # Don't process emails if already working on something
        if self.current_task_id:
            return

        try:
            emails = await self.email_client.get_new_emails()
            if not emails:
                return

            # Process first unread email
            email = emails[0]
            sender = email.get('sender', '')
            subject = email.get('subject', '')
            body = email.get('body', '')

            logger.info(f"New email from {sender}: {subject}")
            self.current_task_id = f"email_{email.get('id', 'unknown')}"

            # World Model: Observe email (non-blocking)
            if self.world_observer:
                try:
                    await self.world_observer.on_console_message(
                        f"Email from {sender}: {subject}", sender
                    )
                except Exception as obs_e:
                    logger.debug(f"World observer error (email): {obs_e}")

            # Build context for Claude
            context = f"""You received an email from {sender}.

Subject: {subject}

Body:
{body[:10000]}

Respond helpfully. If it's a task request, use your tools to complete it.
If it asks a question, answer it. If it's informational, acknowledge it.
Your response will be sent back as an email reply."""

            # Execute with Claude (reuse the message handler)
            fake_item = {
                'user_id': None,
                'user_name': sender,
                'tenant_name': 'Email'
            }
            response = await self._execute_message_with_claude(context, fake_item)

            # Strip thinking from response
            response = self._strip_thinking(response)

            # Send reply
            reply_subject = f"Re: {subject}" if not subject.startswith('Re:') else subject
            sent = await self.email_client.send_email(
                to=sender,
                subject=reply_subject,
                body=response,
                reply_to_id=email.get('id')
            )

            if sent:
                logger.info(f"Email reply sent to {sender}")
            else:
                logger.error(f"Failed to send email reply to {sender}")

            # Log to Matsya if connected
            if self.matsya_client:
                await self.matsya_client.log_agent_activity(
                    "email_processed",
                    f"From: {sender}, Subject: {subject}"
                )

        except Exception as e:
            logger.error(f"Error processing email: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if str(self.current_task_id).startswith('email_'):
                self.current_task_id = None

    # ============ BRU CONSOLE (Direct User Chat) ============

    async def _check_console_messages(self):
        """Check and respond to BRU Console messages from users."""
        if not self.matsya_client:
            return

        # Don't pick up new messages if already working on something
        if self.current_task_id:
            return

        try:
            messages = await self.matsya_client.get_pending_console_messages()
            if not messages:
                return

            # Process first pending message
            msg = messages[0]
            message_id = msg.get('id')
            session_id = msg.get('session_id')
            user_message = msg.get('message', '')
            user_name = msg.get('user_name', 'User')
            context = msg.get('conversation_context', [])

            logger.info(f"Console message from {user_name}: {user_message[:100]}...")
            self.current_task_id = f"console_{message_id}"

            # World Model: Observe console message (non-blocking)
            if self.world_observer:
                try:
                    await self.world_observer.on_console_message(user_message, user_name)
                except Exception as obs_e:
                    logger.debug(f"World observer error (console): {obs_e}")

            # Build conversation history for Claude
            conversation = self._build_console_context(context, user_message)

            # Execute with Claude
            response = await self._execute_console_chat(conversation, msg)

            # Send response back
            success = await self.matsya_client.respond_to_console_message(
                message_id, session_id, response
            )

            if success:
                logger.info(f"Console message {message_id} responded")
            else:
                logger.error(f"Failed to post console response for message {message_id}")

        except Exception as e:
            logger.error(f"Error checking console messages: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if str(self.current_task_id).startswith('console_'):
                self.current_task_id = None

    def _build_console_context(self, context: List[Dict], current_message: str) -> List[Dict]:
        """Build conversation history for Claude from console context."""
        messages = []

        # Add previous messages from context
        for msg in context:
            role = msg.get('role', 'user')
            content = msg.get('message', '')
            if role == 'assistant' or msg.get('is_bru'):
                messages.append({"role": "assistant", "content": content})
            else:
                messages.append({"role": "user", "content": content})

        # Add current message
        messages.append({"role": "user", "content": current_message})

        return messages

    async def _execute_console_chat(self, conversation: List[Dict], msg_info: Dict) -> str:
        """Execute console chat with Claude."""
        if not self.claude:
            return "Claude API not configured - set ANTHROPIC_API_KEY"

        user_name = msg_info.get('user_name', 'User')
        tenant_name = msg_info.get('tenant_name', 'Organization')

        system_prompt = f"""You are BRU (Bot for Routine Undertakings), an AI teammate helping {user_name} at {tenant_name}.

You're having a direct conversation through the BRU Console. Be helpful, conversational, and proactive.

You can help with:
- Answering questions about work, projects, and tasks
- Creating documents, reports, and PDFs
- Searching for information
- Managing tasks in Matsya
- Sending emails and messages
- General productivity assistance

Available tools (use when needed):
- matsya_list_tasks: Get tasks from Matsya
- matsya_search: Search across Matsya
- create_pdf: Create PDF documents
- send_email: Send emails
- And more...

Be concise but helpful. If you need to take action, use your tools. If it's just a question, answer directly."""

        # Get tools from skill registry
        tools = self.skill_registry.get_tool_specs() if self.skill_registry else []

        try:
            api_params = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": conversation
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

                        logger.info(f"Console chat: executing tool {tool_name}")
                        result = await self.skill_registry.execute(tool_name, tool_input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(result)
                        })

                conversation.append({"role": "assistant", "content": assistant_content})
                conversation.append({"role": "user", "content": tool_results})

                api_params["messages"] = conversation
                response = self.claude.messages.create(**api_params)

            # Extract final text
            final_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    final_text += block.text

            return final_text if final_text else "I'm here to help! What would you like to work on?"

        except Exception as e:
            logger.error(f"Claude API error for console chat: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    # ============ @BRU MENTIONS (Task Comments) ============

    async def _check_comment_mentions(self):
        """Check and respond to @BRU mentions in task comments."""
        if not self.matsya_client:
            return

        # Don't pick up new mentions if already working on something
        if self.current_task_id:
            return

        try:
            mentions = await self.matsya_client.get_pending_comment_mentions()
            if not mentions:
                return

            # Process first pending mention
            mention = mentions[0]
            queue_id = mention.get('queue_id')
            task_id = mention.get('task_id')
            task_title = mention.get('task_title', 'Task')
            user_message = mention.get('user_message', '')
            user_name = mention.get('user_name', 'User')
            context = mention.get('conversation_context', [])

            logger.info(f"@BRU mention in task #{task_id} from {user_name}: {user_message[:100]}...")
            self.current_task_id = f"mention_{queue_id}"

            # World Model: Observe @mention (non-blocking)
            if self.world_observer:
                try:
                    await self.world_observer.on_mention(task_id, user_message, user_name)
                except Exception as obs_e:
                    logger.debug(f"World observer error (mention): {obs_e}")

            # Build context for Claude
            full_context = self._build_mention_context(mention, context)

            # Execute with Claude
            response = await self._execute_mention_response(full_context, mention)

            # Send response back
            success = await self.matsya_client.respond_to_comment_mention(queue_id, response)

            if success:
                logger.info(f"@BRU mention {queue_id} responded")
            else:
                logger.error(f"Failed to post mention response for queue {queue_id}")

        except Exception as e:
            logger.error(f"Error checking comment mentions: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if str(self.current_task_id).startswith('mention_'):
                self.current_task_id = None

    def _build_mention_context(self, mention: Dict, context: List[Dict]) -> str:
        """Build context string for @BRU mention response."""
        parts = [
            f"Task: {mention.get('task_title', 'Unknown')}",
            f"Task ID: {mention.get('task_id')}",
            f"Workspace ID: {mention.get('workspace_id')}",
            f"Status: {mention.get('task_status', 'unknown')}",
            f"Priority: {mention.get('priority', 'medium')}",
        ]

        if mention.get('task_description'):
            parts.append(f"\nTask Description:\n{mention['task_description'][:1000]}")

        # Add recent conversation context
        if context:
            parts.append("\nRecent comments:")
            for msg in context[-5:]:  # Last 5 messages
                author = msg.get('user_name', 'User')
                comment = msg.get('comment', '')[:500]
                parts.append(f"- {author}: {comment}")

        # Add the current mention
        parts.append(f"\n{mention.get('user_name', 'User')} mentioned you:")
        parts.append(mention.get('user_message', ''))

        return "\n".join(parts)

    async def _execute_mention_response(self, context: str, mention: Dict) -> str:
        """Execute @BRU mention response with Claude."""
        if not self.claude:
            return "Claude API not configured - set ANTHROPIC_API_KEY"

        user_name = mention.get('user_name', 'User')
        task_title = mention.get('task_title', 'this task')

        system_prompt = f"""You are BRU (Bot for Routine Undertakings), an AI teammate. {user_name} has @mentioned you in a task comment.

Your job is to:
1. Understand what they're asking about regarding "{task_title}"
2. Provide a helpful, concise response
3. Use tools if you need to take action (create documents, send messages, etc.)

Available tools:
- matsya_list_tasks: Get tasks from Matsya
- matsya_search: Search across Matsya
- list_workspace_documents: List documents in a workspace (get document IDs)
- read_workspace_document: Read a workspace document's contents
- read_attachment: Read task attachment contents
- create_pdf: Create PDF documents
- upload_to_workspace: Upload files to workspace
- upload_to_task: Attach files to tasks
- send_email: Send emails
- And more...

IMPORTANT: If the user mentions "documents in this workspace" or refers to files they've uploaded, use list_workspace_documents with the workspace_id from the task context to find them, then read_workspace_document to access them.

Keep responses focused and actionable. You're responding in a task comment thread, so be professional but conversational."""

        user_message = f"""Task context and @mention:

{context}

Please respond to help with what they asked."""

        # Get tools from skill registry
        tools = self.skill_registry.get_tool_specs() if self.skill_registry else []

        messages = [{"role": "user", "content": user_message}]

        try:
            api_params = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2048,  # Shorter for comments
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

                        logger.info(f"@mention response: executing tool {tool_name}")
                        result = await self.skill_registry.execute(tool_name, tool_input)
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

            return final_text if final_text else "I'm looking into this!"

        except Exception as e:
            logger.error(f"Claude API error for @mention: {e}")
            return f"Sorry, I encountered an error while processing this: {str(e)}"

    def stop(self):
        """Stop the agent."""
        self.running = False
        logger.info("BRU agent stopping")

    async def cleanup(self):
        """Cleanup resources."""
        # Stop communication channels
        if self.channel_manager:
            try:
                await self.channel_manager.stop()
                logger.info("Communication channels stopped")
            except Exception as e:
                logger.error(f"Error stopping channels: {e}")

        # Close email client
        if self.email_client:
            try:
                await self.email_client.close()
                logger.info("Email client closed")
            except Exception as e:
                logger.error(f"Error closing email client: {e}")

        if self.matsya_client:
            await self.matsya_client.close()
        logger.info("BRU agent cleanup complete")

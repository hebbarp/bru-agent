"""
Matsya Client - Interface to KnoblyCRM Matsya system.

Based on Matsya API at D:\\matsya:
- Tasks: Workspace-scoped tasks with comments/subtasks
- Daily Todos: Personal user-scoped todos
- Authentication: Bearer token or X-API-Key
"""

import httpx
from typing import List, Dict, Optional, Any
from datetime import date, datetime
from pathlib import Path
from loguru import logger


class MatsyaClient:
    """Client for interacting with Matsya at matsyaai.com.

    API Response Format:
    {
        "status": "success|error",
        "message": "Human-readable message",
        "data": { ... },
        "timestamp": "ISO datetime"
    }
    """

    def __init__(self, config: dict):
        self.base_url = config.get('base_url', 'https://matsyaai.com').rstrip('/')
        self.api_key = config.get('api_key')
        self.username = config.get('username')
        self.password = config.get('password')
        self.user_id = config.get('user_id')
        self.tenant_id = config.get('tenant_id')
        self.default_workspace_id = config.get('default_workspace_id')

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=30.0
        )

    def _get_headers(self) -> dict:
        """Get request headers with authentication."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BRU-Agent/0.1",
            "Accept": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        return headers

    def _get_auth_headers(self) -> dict:
        """Get auth headers only (for multipart uploads - no Content-Type)."""
        headers = {
            "User-Agent": "BRU-Agent/0.1",
            "Accept": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        return headers

    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """Parse and validate API response."""
        try:
            data = response.json()
            if data.get('status') == 'error':
                logger.warning(f"Matsya API error: {data.get('message')}")
            return data
        except Exception as e:
            logger.error(f"Failed to parse response: {e}")
            return {"status": "error", "message": str(e)}

    # ============ DAILY TODOS (Personal) ============

    async def get_daily_todos(
        self,
        date_filter: Optional[str] = None,
        status: Optional[str] = None,
        show_all: bool = False
    ) -> Dict[str, Any]:
        """Fetch daily todos from Matsya.

        Args:
            date_filter: Date in YYYY-MM-DD format (default: today)
            status: Filter by status (pending, in_progress, completed)
            show_all: If True, show todos from all dates

        Returns:
            {
                "todos": [...],
                "stats": {"total": N, "completed": N, ...},
                "date": "YYYY-MM-DD"
            }
        """
        try:
            params = {}
            if date_filter:
                params['date'] = date_filter
            if status:
                params['status'] = status
            if show_all:
                params['all'] = '1'

            response = await self.client.get("/api/daily-todos.php", params=params)
            response.raise_for_status()
            return self._handle_response(response)

        except Exception as e:
            logger.error(f"Failed to fetch daily todos: {e}")
            return {"status": "error", "message": str(e), "todos": []}

    async def get_daily_todo(self, todo_id: int) -> Optional[Dict]:
        """Get a single daily todo by ID."""
        try:
            response = await self.client.get(
                "/api/daily-todos.php",
                params={"id": todo_id}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data') if data.get('status') == 'success' else None
        except Exception as e:
            logger.error(f"Failed to get todo {todo_id}: {e}")
            return None

    async def create_daily_todo(
        self,
        title: str,
        description: str = "",
        due_date: Optional[str] = None,
        priority: str = "medium"
    ) -> Optional[Dict]:
        """Create a new daily todo.

        Args:
            title: Todo title (required)
            description: Optional description
            due_date: Optional due date (YYYY-MM-DD)
            priority: low, medium, or high

        Returns:
            Created todo object or None
        """
        try:
            payload = {
                "title": title,
                "priority": priority
            }
            if description:
                payload["description"] = description
            if due_date:
                payload["due_date"] = due_date

            response = await self.client.post("/api/daily-todos.php", json=payload)
            response.raise_for_status()
            data = self._handle_response(response)

            if data.get('status') == 'success':
                logger.info(f"Created daily todo: {title}")
                return data.get('data')
            return None

        except Exception as e:
            logger.error(f"Failed to create daily todo: {e}")
            return None

    async def update_daily_todo(self, todo_id: int, updates: dict) -> bool:
        """Update a daily todo.

        Args:
            todo_id: Todo ID
            updates: Fields to update (title, description, status, priority)

        Returns:
            True if successful
        """
        try:
            response = await self.client.put(
                "/api/daily-todos.php",
                params={"id": todo_id},
                json=updates
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'

        except Exception as e:
            logger.error(f"Failed to update todo {todo_id}: {e}")
            return False

    async def toggle_daily_todo(self, todo_id: int) -> bool:
        """Toggle daily todo completion status.

        Args:
            todo_id: Todo ID

        Returns:
            True if successful
        """
        try:
            response = await self.client.put(
                "/api/daily-todos.php",
                params={"id": todo_id, "action": "toggle"}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'

        except Exception as e:
            logger.error(f"Failed to toggle todo {todo_id}: {e}")
            return False

    async def complete_daily_todo(self, todo_id: int) -> bool:
        """Mark a daily todo as completed."""
        return await self.update_daily_todo(todo_id, {"status": "completed"})

    async def delete_daily_todo(self, todo_id: int) -> bool:
        """Delete a daily todo."""
        try:
            response = await self.client.delete(
                "/api/daily-todos.php",
                params={"id": todo_id}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'

        except Exception as e:
            logger.error(f"Failed to delete todo {todo_id}: {e}")
            return False

    # ============ TASKS (Workspace-scoped) ============

    async def get_tasks(
        self,
        workspace_id: Optional[int] = None,
        status: Optional[str] = None,
        assignee_id: Optional[int] = None,
        my_tasks: bool = False,
        milestone_id: Optional[int] = None,
        priority: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """Fetch workspace tasks.

        Args:
            workspace_id: Filter by workspace
            status: Comma-separated statuses (open,in_progress,review,blocked,done,cancelled)
            assignee_id: Filter by assignee
            my_tasks: If True, only show tasks assigned to current user
            milestone_id: Filter by milestone
            priority: Filter by priority (low,medium,high,critical)
            limit: Max results (max 100)
            offset: Pagination offset

        Returns:
            List of task objects
        """
        try:
            params = {"limit": min(limit, 100), "offset": offset}

            if workspace_id:
                params['workspace_id'] = workspace_id
            elif self.default_workspace_id:
                params['workspace_id'] = self.default_workspace_id

            if status:
                params['status'] = status
            if assignee_id:
                params['assignee_id'] = assignee_id
            if my_tasks:
                params['my_tasks'] = '1'
            if milestone_id:
                params['milestone_id'] = milestone_id
            if priority:
                params['priority'] = priority

            response = await self.client.get("/api/tasks.php", params=params)
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data', []) if data.get('status') == 'success' else []

        except Exception as e:
            logger.error(f"Failed to fetch tasks: {e}")
            return []

    async def get_task(self, task_id: int) -> Optional[Dict]:
        """Get a single task with full details (comments, subtasks, etc.)."""
        try:
            response = await self.client.get(
                "/api/tasks.php",
                params={"id": task_id}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data') if data.get('status') == 'success' else None

        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None

    async def create_task(
        self,
        title: str,
        workspace_id: Optional[int] = None,
        description: str = "",
        status: str = "open",
        priority: str = "medium",
        task_type: str = "task",
        assignee_id: Optional[int] = None,
        due_date: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        milestone_id: Optional[int] = None,
        parent_task_id: Optional[int] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[int]:
        """Create a new workspace task.

        Args:
            title: Task title (required)
            workspace_id: Workspace ID (required, uses default if not provided)
            description: Task description
            status: open, in_progress, review, blocked, done, cancelled
            priority: low, medium, high, critical
            task_type: task, bug, feature, improvement, question
            assignee_id: User ID to assign to
            due_date: Due date (YYYY-MM-DD)
            estimated_hours: Estimated hours
            milestone_id: Milestone ID
            parent_task_id: Parent task ID (for subtasks)
            tags: List of tag strings

        Returns:
            New task ID or None
        """
        try:
            ws_id = workspace_id or self.default_workspace_id
            if not ws_id:
                logger.error("workspace_id is required for task creation")
                return None

            payload = {
                "workspace_id": ws_id,
                "title": title,
                "status": status,
                "priority": priority,
                "task_type": task_type
            }

            if description:
                payload["description"] = description
            if assignee_id:
                payload["assignee_id"] = assignee_id
            if due_date:
                payload["due_date"] = due_date
            if estimated_hours:
                payload["estimated_hours"] = estimated_hours
            if milestone_id:
                payload["milestone_id"] = milestone_id
            if parent_task_id:
                payload["parent_task_id"] = parent_task_id
            if tags:
                payload["tags"] = tags

            response = await self.client.post("/api/tasks.php", json=payload)
            response.raise_for_status()
            data = self._handle_response(response)

            if data.get('status') == 'success':
                task_id = data.get('data', {}).get('id')
                logger.info(f"Created task #{task_id}: {title}")
                return task_id
            return None

        except Exception as e:
            logger.error(f"Failed to create task: {e}")
            return None

    async def update_task(self, task_id: int, updates: dict) -> bool:
        """Update a task.

        Args:
            task_id: Task ID
            updates: Fields to update

        Returns:
            True if successful
        """
        try:
            response = await self.client.put(
                "/api/tasks.php",
                params={"id": task_id},
                json=updates
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'

        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            return False

    async def complete_task(self, task_id: int) -> bool:
        """Mark a task as done."""
        return await self.update_task(task_id, {"status": "done"})

    async def add_task_comment(self, task_id: int, comment: str) -> Optional[int]:
        """Add a comment to a task.

        Args:
            task_id: Task ID
            comment: Comment text

        Returns:
            Comment ID or None
        """
        try:
            response = await self.client.post(
                "/api/tasks.php",
                params={"id": task_id, "action": "comment"},
                json={"comment": comment}
            )
            response.raise_for_status()
            data = self._handle_response(response)

            if data.get('status') == 'success':
                return data.get('data', {}).get('id')
            return None

        except Exception as e:
            logger.error(f"Failed to add comment to task {task_id}: {e}")
            return None

    async def delete_task(self, task_id: int) -> bool:
        """Delete (cancel) a task."""
        try:
            response = await self.client.delete(
                "/api/tasks.php",
                params={"id": task_id}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'

        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            return False

    # ============ WORKSPACES ============

    async def get_workspaces(self) -> List[Dict]:
        """Get all accessible workspaces."""
        try:
            response = await self.client.get("/api/workspaces.php")
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data', []) if data.get('status') == 'success' else []

        except Exception as e:
            logger.error(f"Failed to fetch workspaces: {e}")
            return []

    # ============ BRU AGENT STATUS ============

    async def get_bru_status(self) -> Dict[str, Any]:
        """Get BRU agent status from Matsya.

        Returns:
            {
                "config": {"is_enabled": bool, "is_paused": bool, ...},
                "stats": {"total": N, "working": N, ...},
                "active_tasks": [...],
                "recent_activity": [...]
            }
        """
        try:
            response = await self.client.get("/api/bru-status.php")
            response.raise_for_status()
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to get BRU status: {e}")
            return {"status": "error", "message": str(e)}

    async def get_agent_status(self) -> str:
        """Get BRU agent status from Matsya (active/paused).

        Returns:
            Agent status string ('active' or 'paused')
        """
        try:
            result = await self.get_bru_status()
            if result.get('status') == 'success':
                config = result.get('data', {}).get('config', {})
                if config.get('is_paused'):
                    return 'paused'
                if not config.get('is_enabled'):
                    return 'disabled'
            return 'active'
        except Exception as e:
            logger.error(f"Failed to get agent status: {e}")
            return 'active'

    async def send_heartbeat(self) -> bool:
        """Send heartbeat to Matsya to indicate BRU is online.

        Returns:
            True if successful
        """
        try:
            response = await self.client.post(
                "/api/bru-status.php",
                params={"action": "heartbeat"}
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
            return False

    async def get_pending_bru_tasks(self) -> List[Dict]:
        """Get tasks pending for BRU to work on.

        Returns:
            List of tasks with bru_status='pending'
        """
        try:
            response = await self.client.get(
                "/api/tasks.php",
                params={"bru_tasks": "1", "bru_status": "pending"}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data', []) if data.get('status') == 'success' else []
        except Exception as e:
            logger.error(f"Failed to get pending BRU tasks: {e}")
            return []

    async def bru_start_task(self, task_id: int) -> bool:
        """Mark that BRU is starting work on a task.

        Args:
            task_id: Task ID

        Returns:
            True if successful
        """
        try:
            response = await self.client.put(
                "/api/tasks.php",
                params={"id": task_id, "action": "bru_start"}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'
        except Exception as e:
            logger.error(f"Failed to start BRU task {task_id}: {e}")
            return False

    async def bru_complete_task(self, task_id: int, result: Optional[str] = None) -> bool:
        """Mark that BRU has completed a task.

        Args:
            task_id: Task ID
            result: Optional result/output description

        Returns:
            True if successful
        """
        try:
            payload = {}
            if result:
                payload["result"] = result

            response = await self.client.put(
                "/api/tasks.php",
                params={"id": task_id, "action": "bru_complete"},
                json=payload
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'
        except Exception as e:
            logger.error(f"Failed to complete BRU task {task_id}: {e}")
            return False

    async def bru_fail_task(self, task_id: int, error: str) -> bool:
        """Mark that BRU failed on a task.

        Args:
            task_id: Task ID
            error: Error message

        Returns:
            True if successful
        """
        try:
            response = await self.client.put(
                "/api/tasks.php",
                params={"id": task_id, "action": "bru_fail"},
                json={"error": error}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'
        except Exception as e:
            logger.error(f"Failed to mark BRU task {task_id} as failed: {e}")
            return False

    async def bru_log_progress(self, task_id: int, message: str) -> bool:
        """Log progress on a BRU task.

        Args:
            task_id: Task ID
            message: Progress message

        Returns:
            True if successful
        """
        try:
            response = await self.client.put(
                "/api/tasks.php",
                params={"id": task_id, "action": "bru_log"},
                json={"message": message}
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to log BRU progress: {e}")
            return False

    async def log_agent_activity(self, activity: str, details: Optional[str] = None, task_id: Optional[int] = None) -> bool:
        """Log BRU agent activity to Matsya.

        Args:
            activity: Action name
            details: Optional details
            task_id: Optional task ID

        Returns:
            True if logged successfully
        """
        try:
            payload = {
                "action": activity,
                "details": details
            }
            if task_id:
                payload["task_id"] = task_id

            response = await self.client.post(
                "/api/bru-status.php",
                params={"action": "log"},
                json=payload
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to log agent activity: {e}")
            return False

    # ============ APPROVALS ============

    async def request_approval(self, tool_name: str, tool_input: dict,
                                context: str, task_id: Optional[int] = None,
                                autonomy_level: str = 'supervised',
                                timeout_seconds: int = 120) -> Optional[Dict]:
        """Request user approval for a gated tool execution.

        Returns:
            Dict with 'id' and 'status' on success, None on failure
        """
        try:
            payload = {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "context": context,
                "autonomy_level": autonomy_level,
                "timeout_seconds": timeout_seconds
            }
            if task_id:
                payload["task_id"] = task_id

            response = await self.client.post(
                "/api/bru-approvals.php",
                params={"action": "request"},
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'success':
                return data.get('data')
            return None
        except Exception as e:
            logger.error(f"Failed to request approval: {e}")
            return None

    async def check_approval(self, approval_id: int) -> Optional[str]:
        """Check the status of an approval request.

        Returns:
            Status string ('pending', 'approved', 'rejected', 'expired') or None on error
        """
        try:
            response = await self.client.get(
                "/api/bru-approvals.php",
                params={"action": "check", "id": approval_id}
            )
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'success':
                return data['data'].get('status')
            return None
        except Exception as e:
            logger.error(f"Failed to check approval: {e}")
            return None

    # ============ SEARCH ============

    async def search(self, query: str) -> Dict[str, Any]:
        """Global search across Matsya.

        Args:
            query: Search query

        Returns:
            Search results
        """
        try:
            response = await self.client.get(
                "/api/search.php",
                params={"q": query}
            )
            response.raise_for_status()
            return self._handle_response(response)

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {"status": "error", "message": str(e)}

    # ============ AI ASSISTANT ============

    async def ai_query(self, prompt: str, context: Optional[str] = None) -> Optional[str]:
        """Query Matsya's AI assistant.

        Args:
            prompt: User query
            context: Optional context

        Returns:
            AI response or None
        """
        try:
            payload = {"prompt": prompt}
            if context:
                payload["context"] = context

            response = await self.client.post("/api/ai-assistant.php", json=payload)
            response.raise_for_status()
            data = self._handle_response(response)

            if data.get('status') == 'success':
                return data.get('data', {}).get('response')
            return None

        except Exception as e:
            logger.error(f"AI query failed: {e}")
            return None

    # ============ FILE UPLOADS ============

    async def upload_task_attachment(
        self,
        task_id: int,
        filepath: str,
        description: Optional[str] = None
    ) -> Optional[Dict]:
        """Upload a file attachment to a task.

        Args:
            task_id: Task ID
            filepath: Path to file to upload
            description: Optional description

        Returns:
            Attachment info or None
        """
        import os
        from pathlib import Path

        path = Path(filepath)
        if not path.exists():
            logger.error(f"File not found: {filepath}")
            return None

        try:
            # Create a new client for multipart upload (different content-type)
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "X-API-Key": self.api_key
                },
                timeout=60.0
            ) as upload_client:
                with open(path, 'rb') as f:
                    files = {'file': (path.name, f, self._get_mime_type(path))}
                    data = {'task_id': str(task_id)}
                    if description:
                        data['description'] = description

                    response = await upload_client.post(
                        "/api/task-attachments.php",
                        files=files,
                        data=data
                    )
                    response.raise_for_status()
                    result = response.json()

                    if result.get('status') == 'success':
                        logger.info(f"Uploaded {path.name} to task #{task_id}")
                        return result.get('data')
                    else:
                        logger.error(f"Upload failed: {result.get('message')}")
                        return None

        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            return None

    def _get_mime_type(self, path: Path) -> str:
        """Get MIME type for a file."""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(str(path))
        return mime_type or 'application/octet-stream'

    async def get_task_attachments(self, task_id: int) -> List[Dict]:
        """Get attachments for a task.

        Args:
            task_id: Task ID

        Returns:
            List of attachment info dicts
        """
        try:
            response = await self.client.get(
                "/api/task-attachments.php",
                params={"task_id": task_id}
            )
            response.raise_for_status()
            result = response.json()

            if result.get('status') == 'success':
                return result.get('data', {}).get('attachments', [])
            return []

        except Exception as e:
            logger.error(f"Failed to get task attachments: {e}")
            return []

    async def download_attachment(self, attachment_id: int, save_path: str) -> bool:
        """Download an attachment to a local file.

        Args:
            attachment_id: Attachment ID
            save_path: Path to save the file

        Returns:
            True if successful
        """
        try:
            response = await self.client.get(
                "/api/task-attachments.php",
                params={"action": "download", "id": attachment_id}
            )
            response.raise_for_status()

            with open(save_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"Downloaded attachment #{attachment_id} to {save_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download attachment: {e}")
            return False

    async def upload_workspace_document(
        self,
        workspace_id: int,
        filepath: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[int] = None
    ) -> Optional[Dict]:
        """Upload a document to a workspace's documents section.

        Args:
            workspace_id: The workspace to upload to
            filepath: Path to the file to upload
            title: Optional title (defaults to filename)
            description: Optional description
            parent_id: Optional parent folder ID

        Returns:
            Document info dict with id, file_path, file_size or None on failure
        """
        path = Path(filepath)
        if not path.exists():
            logger.error(f"File not found: {filepath}")
            return None

        try:
            mime_type = self._get_mime_type(path)

            async with httpx.AsyncClient(timeout=120.0) as upload_client:
                with open(path, 'rb') as f:
                    files = {'file': (path.name, f, mime_type)}
                    data = {
                        'workspace_id': str(workspace_id),
                    }
                    if title:
                        data['title'] = title
                    if description:
                        data['description'] = description
                    if parent_id:
                        data['parent_id'] = str(parent_id)

                    response = await upload_client.post(
                        f"{self.base_url}/api/documents.php",
                        files=files,
                        data=data,
                        headers=self._get_auth_headers()
                    )
                    response.raise_for_status()
                    result = response.json()

                    if result.get('status') == 'success':
                        doc_data = result.get('data', {})
                        doc_id = doc_data.get('id')
                        logger.info(f"Uploaded {path.name} to workspace #{workspace_id}, document ID: {doc_id}")
                        # Return document URL
                        doc_data['url'] = f"{self.base_url}/workspace.php?id={workspace_id}&tab=documents&doc={doc_id}"
                        return doc_data
                    else:
                        logger.error(f"Upload failed: {result.get('message')}")
                        return None

        except Exception as e:
            logger.error(f"Failed to upload document: {e}")
            return None

    # ============ BRU QUEUE (Documents & Messages) ============

    async def get_pending_queue_items(self) -> List[Dict]:
        """Get pending items from BRU queue (documents, messages, tasks).

        Returns:
            List of queue items with item_type, document/message details
        """
        try:
            response = await self.client.get("/api/bru-queue.php")
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data', []) if data.get('status') == 'success' else []
        except Exception as e:
            logger.error(f"Failed to get pending queue items: {e}")
            return []

    async def get_queue_item(self, queue_id: int) -> Optional[Dict]:
        """Get a single queue item by ID.

        Args:
            queue_id: Queue item ID

        Returns:
            Queue item details or None
        """
        try:
            response = await self.client.get(
                "/api/bru-queue.php",
                params={"id": queue_id}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data') if data.get('status') == 'success' else None
        except Exception as e:
            logger.error(f"Failed to get queue item {queue_id}: {e}")
            return None

    async def update_queue_item(
        self,
        queue_id: int,
        status: str,
        result: Optional[str] = None
    ) -> bool:
        """Update a queue item status and result.

        Args:
            queue_id: Queue item ID
            status: New status (processing, completed, failed)
            result: Optional result text

        Returns:
            True if successful
        """
        try:
            payload = {"status": status}
            if result:
                payload["result"] = result

            response = await self.client.put(
                "/api/bru-queue.php",
                params={"id": queue_id},
                json=payload
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('status') == 'success'
        except Exception as e:
            logger.error(f"Failed to update queue item {queue_id}: {e}")
            return False

    async def complete_queue_item(self, queue_id: int, result: str) -> bool:
        """Mark a queue item as completed with result.

        Args:
            queue_id: Queue item ID
            result: Result/response text

        Returns:
            True if successful
        """
        return await self.update_queue_item(queue_id, "completed", result)

    async def fail_queue_item(self, queue_id: int, error: str) -> bool:
        """Mark a queue item as failed.

        Args:
            queue_id: Queue item ID
            error: Error message

        Returns:
            True if successful
        """
        return await self.update_queue_item(queue_id, "failed", error)

    async def get_document(self, document_id: int) -> Optional[Dict]:
        """Get document details including file path.

        Args:
            document_id: Document ID

        Returns:
            Document details or None
        """
        try:
            response = await self.client.get(
                "/api/documents.php",
                params={"id": document_id}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('data') if data.get('status') == 'success' else None
        except Exception as e:
            logger.error(f"Failed to get document {document_id}: {e}")
            return None

    async def download_document(self, document_id: int, save_path: str) -> bool:
        """Download a document file to local path.

        Args:
            document_id: Document ID
            save_path: Local path to save the file

        Returns:
            True if successful
        """
        try:
            response = await self.client.get(
                "/api/documents.php",
                params={"id": document_id, "download": "1"}
            )
            response.raise_for_status()

            # Save the file content
            with open(save_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"Downloaded document {document_id} to {save_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to download document {document_id}: {e}")
            return False

    async def list_workspace_documents(self, workspace_id: int, parent_id: Optional[int] = None) -> List[Dict]:
        """List all documents in a workspace.

        Args:
            workspace_id: Workspace ID to list documents from
            parent_id: Optional parent folder ID to list documents within a specific folder

        Returns:
            List of document metadata (id, title, file_name, file_type, file_size, is_folder, etc.)
        """
        try:
            params = {"workspace_id": workspace_id}
            if parent_id is not None:
                params["parent_id"] = parent_id

            response = await self.client.get(
                "/api/documents.php",
                params=params
            )
            response.raise_for_status()
            data = self._handle_response(response)
            if data.get('status') == 'success':
                return data.get('documents', data.get('data', []))
            return []
        except Exception as e:
            logger.error(f"Failed to list workspace documents for workspace {workspace_id}: {e}")
            return []

    # ============ BRU CONSOLE (Direct User Chat) ============

    async def get_pending_console_messages(self) -> List[Dict]:
        """Get pending console messages that need BRU response.

        These are messages from users in their BRU Console sessions
        that are waiting for BRU to respond.

        Returns:
            List of messages with session info, user message, context
        """
        try:
            response = await self.client.get(
                "/api/bru-console.php",
                params={"action": "pending_for_bru"}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('messages', []) if data.get('status') == 'success' else []
        except Exception as e:
            logger.error(f"Failed to get pending console messages: {e}")
            return []

    async def respond_to_console_message(
        self,
        message_id: int,
        session_id: int,
        response: str
    ) -> bool:
        """Post BRU's response to a console message.

        Args:
            message_id: The message ID to respond to
            session_id: The session ID
            response: BRU's response text

        Returns:
            True if successful
        """
        try:
            payload = {
                "action": "bru_response",
                "message_id": message_id,
                "session_id": session_id,
                "response": response
            }
            resp = await self.client.post("/api/bru-console.php", json=payload)
            resp.raise_for_status()
            data = self._handle_response(resp)
            if data.get('status') == 'success':
                logger.info(f"Responded to console message {message_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to respond to console message {message_id}: {e}")
            return False

    # ============ BRU @MENTIONS (Task Comments) ============

    async def get_pending_comment_mentions(self) -> List[Dict]:
        """Get pending @BRU mentions in task comments.

        Users can @mention BRU in task comments to ask questions
        or request help. This returns those pending mentions.

        Returns:
            List of comment mentions with task info, user message, context
        """
        try:
            response = await self.client.get(
                "/api/bru-tasks.php",
                params={"action": "pending_comments"}
            )
            response.raise_for_status()
            data = self._handle_response(response)
            return data.get('comments', []) if data.get('status') == 'success' else []
        except Exception as e:
            logger.error(f"Failed to get pending comment mentions: {e}")
            return []

    async def respond_to_comment_mention(
        self,
        queue_id: int,
        response: str
    ) -> bool:
        """Post BRU's response to a @BRU mention in task comments.

        Args:
            queue_id: The queue ID from bru_task_comments table
            response: BRU's response text

        Returns:
            True if successful
        """
        try:
            payload = {
                "queue_id": queue_id,
                "response": response
            }
            resp = await self.client.post(
                "/api/bru-tasks.php",
                params={"action": "respond_comment"},
                json=payload
            )
            resp.raise_for_status()
            data = self._handle_response(resp)
            if data.get('status') == 'success':
                logger.info(f"Responded to comment mention {queue_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to respond to comment mention {queue_id}: {e}")
            return False

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

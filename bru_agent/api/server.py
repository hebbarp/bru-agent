"""
BRU HTTP API Server

Exposes BRU skills and world model via REST API for integration with C9AI and other clients.

Endpoints:
    GET  /api/health          - Health check
    GET  /api/status          - BRU status and metrics
    GET  /api/skills          - List available skills
    GET  /api/skills/{name}   - Get skill details and schema
    POST /api/skill/{name}    - Execute a skill
    GET  /api/jobs/{job_id}   - Get async job status/result
    GET  /api/world/state     - Get current world state
    GET  /api/world/commitments - Get active commitments
    POST /api/chat            - Chat with BRU (uses Claude)
"""

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from loguru import logger

# Load environment - check BRU_HOME, then ~/.bru/, then project root
_bru_home = Path(os.getenv("BRU_HOME", "")) if os.getenv("BRU_HOME") else Path.home() / ".bru"
_env_candidates = [_bru_home / ".env", Path(__file__).parent.parent.parent / ".env"]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path)
        break

# Import BRU components
from bru_agent.skills.registry import SkillRegistry
from bru_agent.skills.base import BaseSkill

# Try to import world model components
try:
    from bru_agent.world.state import WorldState
    from bru_agent.world.observer import WorldObserver
    WORLD_MODEL_AVAILABLE = True
except ImportError:
    WORLD_MODEL_AVAILABLE = False
    WorldState = None
    WorldObserver = None


# ============================================================================
# Request/Response Models
# ============================================================================

class SkillExecuteRequest(BaseModel):
    """Request body for skill execution."""
    params: Dict[str, Any] = Field(default_factory=dict, description="Skill parameters")
    async_mode: bool = Field(default=False, description="Run in background and return job ID")
    confirm: bool = Field(default=False, description="Confirm action (for skills requiring confirmation)")


class SkillExecuteResponse(BaseModel):
    """Response from skill execution."""
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    job_id: Optional[str] = None  # For async execution
    confirmation_required: bool = False
    confirmation_message: Optional[str] = None


class JobStatus(BaseModel):
    """Status of an async job."""
    job_id: str
    skill: str
    status: str  # pending, running, completed, failed
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None


class ChatRequest(BaseModel):
    """Request for chat endpoint."""
    message: str
    context: Optional[Dict[str, Any]] = None  # Additional context


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    response: str
    tool_calls: List[Dict[str, Any]] = []
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
    version: str
    world_model_enabled: bool


class StatusResponse(BaseModel):
    """BRU status response."""
    running: bool
    uptime_seconds: float
    skills_loaded: int
    jobs_pending: int
    jobs_completed: int
    world_model: Optional[Dict[str, Any]] = None


# ============================================================================
# Global State
# ============================================================================

class BruAPIState:
    """Global state for the API server."""

    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.skill_registry: Optional[SkillRegistry] = None
        self.world_state: Optional[WorldState] = None
        self.world_observer: Optional[WorldObserver] = None
        self.jobs: Dict[str, JobStatus] = {}
        self.start_time: datetime = datetime.now()
        self.initialized: bool = False

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from config.yaml."""
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        return {}

    async def initialize(self):
        """Initialize BRU components."""
        if self.initialized:
            return

        logger.info("Initializing BRU API...")

        # Load config
        self.config = self.load_config()

        # Initialize skill registry
        self.skill_registry = SkillRegistry(self.config.get('skills', {}))
        self.skill_registry.discover()
        logger.info(f"Loaded {len(self.skill_registry.skills)} skills")

        # Initialize world model if available
        if WORLD_MODEL_AVAILABLE and self.config.get('world_model', {}).get('enabled', False):
            try:
                data_dir = Path(__file__).parent.parent / "data"
                data_dir.mkdir(exist_ok=True)

                state_file = str(data_dir / "world_state.json")
                user_model_file = str(data_dir / "user_model.json")

                # Create observer (it handles loading state and user model)
                self.world_observer = WorldObserver(
                    state_path=state_file,
                    user_model_path=user_model_file
                )

                # Get references to state for API access
                self.world_state = self.world_observer.get_current_state()

                logger.info("World model initialized")
            except Exception as e:
                logger.error(f"Failed to initialize world model: {e}")

        self.initialized = True
        logger.info("BRU API initialized successfully")

    async def cleanup(self):
        """Cleanup resources."""
        # Save world state via observer (it handles persistence)
        if self.world_observer:
            try:
                self.world_observer._save_state()
                self.world_observer._save_user_model()
                logger.info("World state and user model saved")
            except Exception as e:
                logger.error(f"Failed to save world state: {e}")


# Global state instance
state = BruAPIState()


# ============================================================================
# Lifespan Management
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    await state.initialize()
    yield
    await state.cleanup()


# ============================================================================
# Create FastAPI App
# ============================================================================

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="BRU API",
        description="HTTP API for BRU - Bot for Routine Undertakings",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json"
    )

    # CORS middleware for C9AI integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to C9AI origin
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ========================================================================
    # Health & Status Endpoints
    # ========================================================================

    @app.get("/api/health", response_model=HealthResponse, tags=["System"])
    async def health_check():
        """Health check endpoint."""
        return HealthResponse(
            status="healthy" if state.initialized else "initializing",
            timestamp=datetime.now().isoformat(),
            version=state.config.get('system', {}).get('version', '0.1.0'),
            world_model_enabled=state.world_state is not None
        )

    @app.get("/api/status", response_model=StatusResponse, tags=["System"])
    async def get_status():
        """Get BRU status and metrics."""
        uptime = (datetime.now() - state.start_time).total_seconds()

        # Count jobs
        pending = sum(1 for j in state.jobs.values() if j.status in ['pending', 'running'])
        completed = sum(1 for j in state.jobs.values() if j.status in ['completed', 'failed'])

        # World model summary
        world_summary = None
        if state.world_state:
            world_summary = {
                "active_commitments": len(state.world_state.active_commitments),
                "in_progress": len(state.world_state.in_progress_commitments),
                "cognitive_load": round(state.world_state.cognitive_load, 2),
                "upcoming_deadlines": len(state.world_state.upcoming_deadlines)
            }

        return StatusResponse(
            running=state.initialized,
            uptime_seconds=uptime,
            skills_loaded=len(state.skill_registry.skills) if state.skill_registry else 0,
            jobs_pending=pending,
            jobs_completed=completed,
            world_model=world_summary
        )

    # ========================================================================
    # Skills Endpoints
    # ========================================================================

    @app.get("/api/skills", tags=["Skills"])
    async def list_skills():
        """List all available skills."""
        if not state.skill_registry:
            raise HTTPException(status_code=503, detail="Skills not initialized")

        return {
            "skills": state.skill_registry.list_skills(),
            "count": len(state.skill_registry.skills)
        }

    @app.get("/api/skills/tools", tags=["Skills"])
    async def get_tool_specs():
        """Get Claude-compatible tool specifications for all skills.

        This endpoint returns tool specs that can be used directly with
        Claude's tool_use feature or registered with C9AI.
        """
        if not state.skill_registry:
            raise HTTPException(status_code=503, detail="Skills not initialized")

        return {
            "tools": state.skill_registry.get_tool_specs(),
            "count": len(state.skill_registry.get_tool_specs())
        }

    @app.get("/api/skills/{skill_name}", tags=["Skills"])
    async def get_skill_details(skill_name: str):
        """Get details and schema for a specific skill."""
        if not state.skill_registry:
            raise HTTPException(status_code=503, detail="Skills not initialized")

        skill = state.skill_registry.get(skill_name)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

        return {
            "name": skill.name,
            "description": skill.description,
            "version": skill.version,
            "enabled": skill.enabled,
            "schema": skill.get_schema(),
            "tool_spec": skill.to_tool_spec(),
            "requires_confirmation": getattr(skill, 'requires_confirmation', False)
        }

    @app.post("/api/skill/{skill_name}", response_model=SkillExecuteResponse, tags=["Skills"])
    async def execute_skill(
        skill_name: str,
        request: SkillExecuteRequest,
        background_tasks: BackgroundTasks
    ):
        """Execute a skill with given parameters."""
        if not state.skill_registry:
            raise HTTPException(status_code=503, detail="Skills not initialized")

        skill = state.skill_registry.get(skill_name)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

        # Check if confirmation is required
        requires_confirmation = getattr(skill, 'requires_confirmation', False)
        if requires_confirmation and not request.confirm:
            # Return confirmation request
            return SkillExecuteResponse(
                success=False,
                confirmation_required=True,
                confirmation_message=f"Skill '{skill_name}' requires confirmation before execution. Set 'confirm: true' to proceed."
            )

        # Add confirm to params if needed
        params = request.params.copy()
        if request.confirm:
            params['confirm'] = True

        # Execute async or sync
        if request.async_mode:
            # Create job and execute in background
            job_id = str(uuid.uuid4())[:8]
            job = JobStatus(
                job_id=job_id,
                skill=skill_name,
                status="pending",
                created_at=datetime.now().isoformat()
            )
            state.jobs[job_id] = job

            async def run_skill():
                job.status = "running"
                try:
                    result = await state.skill_registry.execute(skill_name, params)
                    job.status = "completed" if result.get('success') else "failed"
                    job.result = result.get('result')
                    job.error = result.get('error')

                    # Notify world observer
                    if state.world_observer:
                        await state.world_observer.on_skill_completed(
                            skill_name, params, result, result.get('success', False)
                        )
                except Exception as e:
                    job.status = "failed"
                    job.error = str(e)
                finally:
                    job.completed_at = datetime.now().isoformat()

            background_tasks.add_task(run_skill)

            return SkillExecuteResponse(
                success=True,
                job_id=job_id,
                result={"message": f"Job {job_id} started"}
            )
        else:
            # Execute synchronously
            try:
                # Notify world observer - skill started
                if state.world_observer:
                    await state.world_observer.on_skill_started(skill_name, params)

                result = await state.skill_registry.execute(skill_name, params)

                # Notify world observer - skill completed
                if state.world_observer:
                    await state.world_observer.on_skill_completed(
                        skill_name, params, result, result.get('success', False)
                    )

                # Check if skill returned confirmation_required
                if result.get('status') == 'confirmation_required':
                    return SkillExecuteResponse(
                        success=False,
                        confirmation_required=True,
                        confirmation_message=result.get('message', 'Confirmation required'),
                        result=result
                    )

                return SkillExecuteResponse(
                    success=result.get('success', False),
                    result=result.get('result'),
                    error=result.get('error')
                )
            except Exception as e:
                logger.error(f"Skill execution failed: {e}")
                return SkillExecuteResponse(
                    success=False,
                    error=str(e)
                )

    @app.get("/api/jobs/{job_id}", response_model=JobStatus, tags=["Jobs"])
    async def get_job_status(job_id: str):
        """Get status of an async job."""
        if job_id not in state.jobs:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        return state.jobs[job_id]

    @app.get("/api/jobs", tags=["Jobs"])
    async def list_jobs(status: Optional[str] = None, limit: int = 50):
        """List async jobs, optionally filtered by status."""
        jobs = list(state.jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        jobs = sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]
        return {"jobs": jobs, "count": len(jobs)}

    # ========================================================================
    # World Model Endpoints
    # ========================================================================

    @app.get("/api/world/state", tags=["World Model"])
    async def get_world_state():
        """Get current world state."""
        if not state.world_state:
            raise HTTPException(
                status_code=503,
                detail="World model not enabled or not initialized"
            )

        return {
            "state": state.world_state.to_dict(),
            "summary": {
                "active_commitments": len(state.world_state.active_commitments),
                "in_progress": len(state.world_state.in_progress_commitments),
                "cognitive_load": round(state.world_state.cognitive_load, 2),
                "upcoming_deadlines": len(state.world_state.upcoming_deadlines)
            }
        }

    @app.get("/api/world/commitments", tags=["World Model"])
    async def get_commitments(
        active_only: bool = True,
        include_completed: bool = False
    ):
        """Get commitments from world state."""
        if not state.world_state:
            raise HTTPException(
                status_code=503,
                detail="World model not enabled or not initialized"
            )

        if active_only:
            commitments = state.world_state.active_commitments
        elif include_completed:
            commitments = state.world_state.commitments
        else:
            commitments = [c for c in state.world_state.commitments if not c.completed]

        return {
            "commitments": [c.to_dict() for c in commitments],
            "count": len(commitments)
        }

    @app.get("/api/world/resources", tags=["World Model"])
    async def get_resources():
        """Get tracked resources from world state."""
        if not state.world_state:
            raise HTTPException(
                status_code=503,
                detail="World model not enabled or not initialized"
            )

        return {
            "resources": {k: v.to_dict() for k, v in state.world_state.resources.items()}
        }

    # ========================================================================
    # DeepLit Training Endpoints
    # ========================================================================

    @app.get("/api/training/projects", tags=["Training"])
    async def list_training_projects():
        """List all DeepLit training projects."""
        deeplit_skill = state.skill_registry.get("deeplit") if state.skill_registry else None
        if not deeplit_skill:
            raise HTTPException(status_code=503, detail="DeepLit skill not available")

        result = await deeplit_skill.execute({"action": "list_projects"})
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
        return result.get("result")

    @app.get("/api/training/stats", tags=["Training"])
    async def get_training_stats(project: Optional[str] = None):
        """Get training data statistics."""
        deeplit_skill = state.skill_registry.get("deeplit") if state.skill_registry else None
        if not deeplit_skill:
            raise HTTPException(status_code=503, detail="DeepLit skill not available")

        params = {"action": "get_stats"}
        if project:
            params["project"] = project

        result = await deeplit_skill.execute(params)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
        return result.get("result")

    @app.post("/api/training/process", tags=["Training"])
    async def process_documents(
        path: str,
        project: str = "default",
        task: str = "qa",
        format: str = "alpaca",
        domain: Optional[str] = None,
        recursive: bool = True,
        background_tasks: BackgroundTasks = None
    ):
        """Process documents into training data.

        Args:
            path: File or directory path to process
            project: Project name for organizing output
            task: qa, instruct, summarize, or extract
            format: alpaca, sharegpt, or openai
            domain: Domain context for better generation
            recursive: Process subdirectories
        """
        deeplit_skill = state.skill_registry.get("deeplit") if state.skill_registry else None
        if not deeplit_skill:
            raise HTTPException(status_code=503, detail="DeepLit skill not available")

        from pathlib import Path as P
        path_obj = P(path)

        if path_obj.is_file():
            action = "process_file"
        elif path_obj.is_dir():
            action = "process_directory"
        else:
            raise HTTPException(status_code=400, detail=f"Path not found: {path}")

        params = {
            "action": action,
            "path": path,
            "project": project,
            "task": task,
            "format": format,
            "recursive": recursive
        }
        if domain:
            params["domain"] = domain

        result = await deeplit_skill.execute(params)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
        return result.get("result")

    @app.post("/api/training/scrape", tags=["Training"])
    async def scrape_for_training(
        url: Optional[str] = None,
        urls: Optional[List[str]] = None,
        project: str = "web_scrape",
        task: str = "qa",
        format: str = "alpaca",
        domain: Optional[str] = None,
        max_depth: int = 2,
        max_pages: int = 50
    ):
        """Scrape web content and convert to training data.

        Args:
            url: Single URL to scrape
            urls: List of URLs to scrape
            project: Project name for organizing output
            task: qa, instruct, summarize, or extract
            format: alpaca, sharegpt, or openai
            domain: Domain context for better generation
            max_depth: Maximum crawl depth
            max_pages: Maximum pages to scrape
        """
        deeplit_skill = state.skill_registry.get("deeplit") if state.skill_registry else None
        if not deeplit_skill:
            raise HTTPException(status_code=503, detail="DeepLit skill not available")

        if not url and not urls:
            raise HTTPException(status_code=400, detail="url or urls is required")

        params = {
            "action": "scrape_url",
            "project": project,
            "task": task,
            "format": format,
            "max_depth": max_depth,
            "max_pages": max_pages
        }
        if url:
            params["url"] = url
        if urls:
            params["urls"] = urls
        if domain:
            params["domain"] = domain

        result = await deeplit_skill.execute(params)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
        return result.get("result")

    @app.post("/api/training/conversations", tags=["Training"])
    async def convert_conversations(
        conversations: List[Dict[str, Any]],
        project: str = "conversations",
        format: str = "alpaca"
    ):
        """Convert conversation history to training data.

        Args:
            conversations: List of conversation objects with 'messages' arrays
            project: Project name for organizing output
            format: alpaca, sharegpt, or openai
        """
        deeplit_skill = state.skill_registry.get("deeplit") if state.skill_registry else None
        if not deeplit_skill:
            raise HTTPException(status_code=503, detail="DeepLit skill not available")

        result = await deeplit_skill.execute({
            "action": "process_conversations",
            "conversations": conversations,
            "project": project,
            "format": format
        })
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
        return result.get("result")

    @app.post("/api/training/export-interactions", tags=["Training"])
    async def export_bru_interactions(
        project: str = "bru_interactions",
        format: str = "alpaca",
        days: int = 30
    ):
        """Export BRU interaction history as training data.

        This exports successful task completions and skill usages
        from BRU's world model as training examples.
        """
        deeplit_skill = state.skill_registry.get("deeplit") if state.skill_registry else None
        if not deeplit_skill:
            raise HTTPException(status_code=503, detail="DeepLit skill not available")

        result = await deeplit_skill.execute({
            "action": "export_interactions",
            "project": project,
            "format": format,
            "days": days
        })
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error"))
        return result.get("result")

    # ========================================================================
    # Chat Endpoint (for direct interaction)
    # ========================================================================

    @app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
    async def chat(request: ChatRequest):
        """Chat with BRU using Claude."""
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

            # Build system prompt with available skills
            skills_info = ""
            if state.skill_registry:
                skills_list = state.skill_registry.list_skills()
                skills_info = "Available skills:\n" + "\n".join(
                    f"- {s['name']}: {s['description']}"
                    for s in skills_list
                )

            # Add world state context
            world_context = ""
            if state.world_state:
                active = state.world_state.active_commitments
                if active:
                    world_context = f"\n\nUser has {len(active)} active commitments. Cognitive load: {state.world_state.cognitive_load:.0%}"

            system_prompt = f"""You are BRU, a helpful AI assistant with access to real-world skills.

{skills_info}
{world_context}

When the user asks you to do something, use the appropriate skill. Be concise and helpful."""

            # Get tool specs
            tools = state.skill_registry.get_tool_specs() if state.skill_registry else []

            # Call Claude
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": request.message}],
                tools=tools if tools else None
            )

            # Process response
            text_response = ""
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    text_response += block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "tool": block.name,
                        "params": block.input,
                        "id": block.id
                    })

            # Execute tool calls if any
            if tool_calls and response.stop_reason == "tool_use":
                for tc in tool_calls:
                    result = await state.skill_registry.execute(tc['tool'], tc['params'])
                    tc['result'] = result

                # Could continue conversation with tool results here
                # For now, just return the tool calls

            return ChatResponse(
                response=text_response,
                tool_calls=tool_calls
            )

        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return ChatResponse(
                response="",
                error=str(e)
            )

    return app


# ============================================================================
# Run Server
# ============================================================================

def run_server(host: str = "0.0.0.0", port: int = 5050):
    """Run the API server."""
    import uvicorn

    app = create_app()

    logger.info(f"Starting BRU API server on {host}:{port}")
    logger.info(f"API docs available at http://{host}:{port}/api/docs")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()

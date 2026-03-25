"""
Shell Command Skill - Executes system commands.

Provides:
- bash_execute: Powerful shell execution (like Claude Code's Bash tool)
- run_command: Legacy restricted command execution
- compile_latex: LaTeX compilation helper
"""

import asyncio
import subprocess
import shutil
import re
import os
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple
from loguru import logger

from ..base import BaseSkill


class BashExecuteSkill(BaseSkill):
    """Powerful shell execution skill - like Claude Code's Bash tool."""

    name = "bash_execute"
    description = """Execute a shell/bash command. Use this for:
- Git operations (git status, git diff, git add, git commit, git push, etc.)
- Running builds (npm run build, python setup.py, cargo build, etc.)
- Running tests (pytest, npm test, cargo test, etc.)
- Package management (pip install, npm install, etc.)
- File operations (mkdir, cp, mv, ls, etc.)
- Any command-line tool

SAFETY: Dangerous commands (rm -rf, format, etc.) will be blocked or warned.
The command runs in the specified working_dir or current directory."""
    version = "1.0.0"

    # Patterns that indicate dangerous commands
    DANGEROUS_PATTERNS = [
        (r'\brm\s+(-[rf]+\s+)*[/\\]($|\s)', 'Deleting root directory'),
        (r'\brm\s+-rf?\s+\*', 'Recursive delete with wildcard'),
        (r'\bformat\s+[a-zA-Z]:', 'Formatting drive'),
        (r'\bmkfs\.', 'Creating filesystem'),
        (r'\bdd\s+.*of=/dev/', 'Writing directly to device'),
        (r'>\s*/dev/[sh]d[a-z]', 'Redirecting to raw device'),
        (r'\bchmod\s+(-R\s+)?777\s+/', 'Chmod 777 on root'),
        (r'\bchown\s+.*\s+/', 'Changing ownership of root'),
        (r':(){ :|:& };:', 'Fork bomb'),
        (r'\bsudo\s+rm\s+-rf\s+/', 'Sudo rm -rf root'),
    ]

    # Commands that should trigger a warning but not be blocked
    WARN_PATTERNS = [
        (r'\brm\s+-rf?\b', 'Recursive delete - make sure path is correct'),
        (r'\bgit\s+push\s+.*--force', 'Force push - may overwrite remote history'),
        (r'\bgit\s+reset\s+--hard', 'Hard reset - uncommitted changes will be lost'),
        (r'\bdrop\s+database', 'Dropping database'),
        (r'\btruncate\s+table', 'Truncating table'),
    ]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.default_timeout = 120  # 2 minutes default
        self.max_timeout = 600  # 10 minutes max

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command (default: current directory)"
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout in seconds (default: {self.default_timeout}, max: {self.max_timeout})"
                },
                "env": {
                    "type": "object",
                    "description": "Additional environment variables to set",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["command"]
        }

    def _check_dangerous(self, command: str) -> Tuple[bool, Optional[str]]:
        """Check if command matches dangerous patterns."""
        cmd_lower = command.lower()

        for pattern, reason in self.DANGEROUS_PATTERNS:
            if re.search(pattern, cmd_lower, re.IGNORECASE):
                return True, f"BLOCKED: {reason}"

        return False, None

    def _check_warnings(self, command: str) -> List[str]:
        """Check if command should trigger warnings."""
        warnings = []
        cmd_lower = command.lower()

        for pattern, reason in self.WARN_PATTERNS:
            if re.search(pattern, cmd_lower, re.IGNORECASE):
                warnings.append(reason)

        return warnings

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a shell command."""
        command = params.get('command', '').strip()
        working_dir = params.get('working_dir', '.')
        timeout = min(params.get('timeout', self.default_timeout), self.max_timeout)
        extra_env = params.get('env', {})

        if not command:
            return {"success": False, "error": "No command provided"}

        # Check for dangerous commands
        is_dangerous, danger_reason = self._check_dangerous(command)
        if is_dangerous:
            logger.warning(f"Blocked dangerous command: {command}")
            return {"success": False, "error": danger_reason}

        # Check for warnings
        warnings = self._check_warnings(command)

        # Resolve working directory
        work_path = Path(working_dir).resolve()
        if not work_path.exists():
            return {"success": False, "error": f"Working directory does not exist: {working_dir}"}

        # Prepare environment
        env = os.environ.copy()
        env.update(extra_env)

        try:
            logger.info(f"Executing: {command}")
            logger.info(f"Working dir: {work_path}")

            # Run command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_path),
                env=env
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "success": False,
                    "error": f"Command timed out after {timeout} seconds",
                    "hint": "Increase timeout parameter if this command needs more time"
                }

            # Decode output
            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""
            exit_code = process.returncode

            # Truncate very long output
            max_output = 30000
            stdout_truncated = len(stdout_text) > max_output
            stderr_truncated = len(stderr_text) > max_output

            if stdout_truncated:
                stdout_text = stdout_text[:max_output] + f"\n... (truncated, {len(stdout_text)} total chars)"
            if stderr_truncated:
                stderr_text = stderr_text[:max_output] + f"\n... (truncated, {len(stderr_text)} total chars)"

            result = {
                "success": exit_code == 0,
                "result": {
                    "exit_code": exit_code,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "working_dir": str(work_path),
                }
            }

            if warnings:
                result["result"]["warnings"] = warnings

            if exit_code != 0:
                result["error"] = f"Command exited with code {exit_code}"

            logger.info(f"Command completed: exit_code={exit_code}, stdout={len(stdout_text)} chars, stderr={len(stderr_text)} chars")
            return result

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return {"success": False, "error": f"Execution failed: {str(e)}"}


class GitSkill(BaseSkill):
    """Convenience skill for common Git operations."""

    name = "git"
    description = """Execute Git commands. Shorthand for common git operations:
- git("status") → git status
- git("diff") → git diff
- git("log", args="--oneline -10") → git log --oneline -10
- git("add", args=".") → git add .
- git("commit", args="-m 'message'") → git commit -m 'message'
- git("push") → git push
- git("pull") → git pull

Use bash_execute for complex git commands."""
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Git operation: status, diff, log, add, commit, push, pull, branch, checkout, merge, fetch, stash, etc."
                },
                "args": {
                    "type": "string",
                    "description": "Additional arguments for the git command"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Repository directory (default: current directory)"
                }
            },
            "required": ["operation"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a git command."""
        operation = params.get('operation', '').strip()
        args = params.get('args', '').strip()
        working_dir = params.get('working_dir', '.')

        if not operation:
            return {"success": False, "error": "No git operation specified"}

        # Check if git is installed
        if not shutil.which('git'):
            return {"success": False, "error": "Git is not installed or not in PATH"}

        # Build command
        command = f"git {operation}"
        if args:
            command += f" {args}"

        # Check for dangerous operations
        dangerous_ops = ['push --force', 'reset --hard', 'clean -fd']
        for dangerous in dangerous_ops:
            if dangerous in command.lower():
                logger.warning(f"Potentially dangerous git command: {command}")

        work_path = Path(working_dir).resolve()
        if not work_path.exists():
            return {"success": False, "error": f"Directory does not exist: {working_dir}"}

        try:
            logger.info(f"Executing: {command} in {work_path}")

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_path)
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=60
            )

            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""
            exit_code = process.returncode

            result = {
                "success": exit_code == 0,
                "result": {
                    "output": stdout_text if stdout_text else stderr_text,
                    "exit_code": exit_code,
                    "command": command
                }
            }

            if exit_code != 0 and stderr_text:
                result["error"] = stderr_text[:500]

            return result

        except asyncio.TimeoutError:
            return {"success": False, "error": "Git command timed out"}
        except Exception as e:
            return {"success": False, "error": f"Git command failed: {str(e)}"}


class ShellCommandSkill(BaseSkill):
    """Skill for executing shell commands to leverage system tools."""

    name = "run_command"
    description = """Execute a shell command to use system tools. Use this when you need to:
- Compile LaTeX documents (pdflatex, xelatex, lualatex)
- Convert documents with Pandoc (pandoc)
- Process images with ImageMagick (magick, convert)
- Process audio/video with FFmpeg (ffmpeg, ffprobe)
- Run any other installed command-line tool

The command runs in the output directory. Always use the full command with arguments."""
    version = "1.0.0"

    # Allowed commands for safety (can be extended)
    ALLOWED_COMMANDS = {
        # LaTeX
        'pdflatex', 'xelatex', 'lualatex', 'latex', 'bibtex', 'biber', 'makeindex',
        # Typst (modern typesetting)
        'typst',
        # Pandoc
        'pandoc',
        # ImageMagick
        'magick', 'convert', 'identify', 'mogrify', 'composite',
        # FFmpeg
        'ffmpeg', 'ffprobe',
        # Common utilities
        'curl', 'wget',
        # Python
        'python', 'python3', 'py',
        # Node
        'node', 'npm', 'npx',
    }

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = 300  # 5 minute timeout for long-running commands

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The full command to execute (e.g., 'pdflatex document.tex', 'pandoc input.md -o output.pdf', 'ffmpeg -i input.mp4 output.mp3')"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory. Defaults to the output directory."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Optional timeout in seconds. Default is 300 (5 minutes)."
                },
                "input_content": {
                    "type": "string",
                    "description": "Optional content to write to an input file before running the command. Useful for LaTeX/Pandoc where you need to create the source file first."
                },
                "input_filename": {
                    "type": "string",
                    "description": "Filename for input_content. Required if input_content is provided."
                }
            },
            "required": ["command"]
        }

    def _check_command_allowed(self, command: str) -> tuple[bool, str]:
        """Check if the command is in the allowed list."""
        # Extract the base command (first word)
        parts = command.strip().split()
        if not parts:
            return False, "Empty command"

        base_cmd = parts[0].lower()
        # Remove .exe extension if present (Windows)
        if base_cmd.endswith('.exe'):
            base_cmd = base_cmd[:-4]
        # Get just the command name without path
        base_cmd = Path(base_cmd).name

        if base_cmd in self.ALLOWED_COMMANDS:
            return True, base_cmd

        return False, f"Command '{base_cmd}' is not in the allowed list. Allowed: {', '.join(sorted(self.ALLOWED_COMMANDS))}"

    def _check_tool_installed(self, tool: str) -> bool:
        """Check if a tool is installed and available."""
        return shutil.which(tool) is not None

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a shell command."""
        command = params.get('command', '').strip()
        working_dir = params.get('working_dir', str(self.output_dir))
        timeout = params.get('timeout', self.timeout)
        input_content = params.get('input_content')
        input_filename = params.get('input_filename')

        if not command:
            return {"success": False, "error": "No command provided"}

        # Check if command is allowed
        allowed, result = self._check_command_allowed(command)
        if not allowed:
            return {"success": False, "error": result}

        base_cmd = result

        # Check if tool is installed
        if not self._check_tool_installed(base_cmd):
            return {
                "success": False,
                "error": f"Tool '{base_cmd}' is not installed or not in PATH"
            }

        # Create working directory if needed
        work_path = Path(working_dir)
        work_path.mkdir(parents=True, exist_ok=True)

        # Write input file if provided
        if input_content and input_filename:
            input_path = work_path / input_filename
            input_path.write_text(input_content, encoding='utf-8')
            logger.info(f"Created input file: {input_path}")

        try:
            logger.info(f"Executing command: {command}")
            logger.info(f"Working directory: {work_path}")

            # Run command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_path),
                shell=True
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "error": f"Command timed out after {timeout} seconds"
                }

            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""
            exit_code = process.returncode

            # List output files
            output_files = [f.name for f in work_path.iterdir() if f.is_file()]

            result = {
                "success": exit_code == 0,
                "result": {
                    "exit_code": exit_code,
                    "stdout": stdout_text[:5000] if stdout_text else "",  # Limit output size
                    "stderr": stderr_text[:2000] if stderr_text else "",
                    "working_directory": str(work_path),
                    "output_files": output_files
                }
            }

            if exit_code != 0:
                result["error"] = f"Command exited with code {exit_code}"
                if stderr_text:
                    result["error"] += f": {stderr_text[:500]}"

            logger.info(f"Command completed with exit code {exit_code}")
            return result

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return {"success": False, "error": f"Command execution failed: {str(e)}"}


class LaTeXSkill(BaseSkill):
    """Convenience skill specifically for LaTeX compilation."""

    name = "compile_latex"
    description = """Compile a LaTeX document to PDF. Provide the LaTeX source code and this will:
1. Create the .tex file
2. Run pdflatex (twice for references)
3. Return the path to the generated PDF

Use this when asked to create documents with LaTeX formatting, mathematical equations, or professional typesetting."""
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "latex_source": {
                    "type": "string",
                    "description": "The complete LaTeX source code including \\documentclass, \\begin{document}, etc."
                },
                "filename": {
                    "type": "string",
                    "description": "Base filename for the document (without extension). Default: 'document'"
                },
                "compiler": {
                    "type": "string",
                    "description": "LaTeX compiler to use: 'pdflatex', 'xelatex', or 'lualatex'. Default: 'pdflatex'"
                }
            },
            "required": ["latex_source"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Compile LaTeX to PDF."""
        latex_source = params.get('latex_source', '')
        filename = params.get('filename', 'document')
        compiler = params.get('compiler', 'pdflatex')

        if not latex_source:
            return {"success": False, "error": "No LaTeX source provided"}

        # Check if compiler is installed
        if not shutil.which(compiler):
            return {
                "success": False,
                "error": f"LaTeX compiler '{compiler}' is not installed. Please install a LaTeX distribution (e.g., MiKTeX or TeX Live)."
            }

        # Create safe filename
        safe_filename = "".join(c for c in filename if c.isalnum() or c in '-_').strip() or 'document'
        tex_file = self.output_dir / f"{safe_filename}.tex"
        pdf_file = self.output_dir / f"{safe_filename}.pdf"

        try:
            # Write LaTeX source
            tex_file.write_text(latex_source, encoding='utf-8')
            logger.info(f"Created LaTeX file: {tex_file}")

            # Compile (run twice for references)
            for run in range(2):
                process = await asyncio.create_subprocess_exec(
                    compiler,
                    '-interaction=nonstopmode',
                    '-output-directory', str(self.output_dir),
                    str(tex_file),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.output_dir)
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=120
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return {"success": False, "error": "LaTeX compilation timed out"}

                if process.returncode != 0 and run == 1:
                    log_file = self.output_dir / f"{safe_filename}.log"
                    log_content = ""
                    if log_file.exists():
                        log_content = log_file.read_text(errors='replace')[-2000:]
                    return {
                        "success": False,
                        "error": f"LaTeX compilation failed. Check the log:\n{log_content}"
                    }

            if pdf_file.exists():
                logger.info(f"PDF created: {pdf_file}")
                return {
                    "success": True,
                    "result": {
                        "message": f"LaTeX document compiled successfully",
                        "pdf_path": str(pdf_file),
                        "filename": f"{safe_filename}.pdf",
                        "size_bytes": pdf_file.stat().st_size
                    }
                }
            else:
                return {"success": False, "error": "PDF was not created"}

        except Exception as e:
            logger.error(f"LaTeX compilation failed: {e}")
            return {"success": False, "error": f"LaTeX compilation failed: {str(e)}"}


## PandocSkill removed - use DocumentConverterSkill in pdf_generator.py instead

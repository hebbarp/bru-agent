"""
File Operations Skill - Read, write, edit, search, and manipulate files.

Provides Claude Code-like file capabilities:
- read_file: Read file contents
- write_file: Write/create files
- edit_file: Smart find & replace editing
- glob_search: Find files by pattern
- grep_search: Search file contents with regex
- list_directory: List directory contents
"""

import re
import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger
from ..base import BaseSkill


class ReadFileSkill(BaseSkill):
    """Skill to read file contents."""

    name = "read_file"
    description = "Read the contents of a file"
    version = "1.0.0"

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read a file.

        Args:
            params: Must contain 'path' key

        Returns:
            File contents or error
        """
        file_path = params.get('path')
        if not file_path:
            return {"success": False, "error": "Missing 'path' parameter"}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}

            content = path.read_text(encoding='utf-8')
            return {
                "success": True,
                "result": content,
                "path": str(path.absolute())
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read"
                }
            },
            "required": ["path"]
        }


class WriteFileSkill(BaseSkill):
    """Skill to write file contents."""

    name = "write_file"
    description = "Write content to a file"
    version = "1.0.0"

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Write to a file.

        Args:
            params: Must contain 'path' and 'content' keys

        Returns:
            Success status
        """
        file_path = params.get('path')
        content = params.get('content')

        if not file_path:
            return {"success": False, "error": "Missing 'path' parameter"}
        if content is None:
            return {"success": False, "error": "Missing 'content' parameter"}

        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')

            return {
                "success": True,
                "result": f"Written {len(content)} bytes to {file_path}",
                "path": str(path.absolute())
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["path", "content"]
        }


class ListDirectorySkill(BaseSkill):
    """Skill to list directory contents."""

    name = "list_directory"
    description = "List files and folders in a directory"
    version = "1.0.0"

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List directory contents.

        Args:
            params: Must contain 'path' key

        Returns:
            List of files and directories
        """
        dir_path = params.get('path', '.')

        try:
            path = Path(dir_path)
            if not path.exists():
                return {"success": False, "error": f"Directory not found: {dir_path}"}
            if not path.is_dir():
                return {"success": False, "error": f"Not a directory: {dir_path}"}

            items = []
            for item in path.iterdir():
                items.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })

            return {
                "success": True,
                "result": items,
                "path": str(path.absolute()),
                "count": len(items)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to list",
                    "default": "."
                }
            }
        }


class EditFileSkill(BaseSkill):
    """Skill to edit files using find & replace - like Claude Code's Edit tool."""

    name = "edit_file"
    description = """Edit a file by replacing a specific string with new content.
This is the PREFERRED way to modify existing files - safer than rewriting the whole file.
The old_string must match EXACTLY (including whitespace/indentation).
Use replace_all=true to replace ALL occurrences, otherwise only the first match is replaced.
TIP: Include enough context in old_string to make it unique in the file."""
    version = "1.0.0"

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Edit a file using find & replace.

        Args:
            params: Must contain 'path', 'old_string', 'new_string'
                   Optional: 'replace_all' (default False)

        Returns:
            Success status with details
        """
        file_path = params.get('path')
        old_string = params.get('old_string')
        new_string = params.get('new_string')
        replace_all = params.get('replace_all', False)

        if not file_path:
            return {"success": False, "error": "Missing 'path' parameter"}
        if old_string is None:
            return {"success": False, "error": "Missing 'old_string' parameter"}
        if new_string is None:
            return {"success": False, "error": "Missing 'new_string' parameter"}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}

            content = path.read_text(encoding='utf-8')

            # Check if old_string exists
            count = content.count(old_string)
            if count == 0:
                return {
                    "success": False,
                    "error": f"String not found in file. Make sure old_string matches exactly (including whitespace).",
                    "hint": "Try reading the file first to see the exact content."
                }

            # Check for ambiguity
            if count > 1 and not replace_all:
                return {
                    "success": False,
                    "error": f"String found {count} times. Either use replace_all=true or provide more context to make it unique.",
                    "occurrences": count
                }

            # Perform replacement
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements = count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements = 1

            # Write back
            path.write_text(new_content, encoding='utf-8')

            logger.info(f"Edited {file_path}: {replacements} replacement(s)")

            return {
                "success": True,
                "result": f"Successfully edited {file_path}",
                "replacements": replacements,
                "path": str(path.absolute())
            }

        except Exception as e:
            logger.error(f"Edit failed: {e}")
            return {"success": False, "error": str(e)}

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit"
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace (must match exactly including whitespace)"
                },
                "new_string": {
                    "type": "string",
                    "description": "The string to replace it with"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replace ALL occurrences. If false (default), replace only first occurrence.",
                    "default": False
                }
            },
            "required": ["path", "old_string", "new_string"]
        }


class GlobSearchSkill(BaseSkill):
    """Skill to find files by pattern - like Claude Code's Glob tool."""

    name = "glob_search"
    description = """Find files matching a glob pattern.
Examples:
- "*.py" - all Python files in current directory
- "**/*.py" - all Python files recursively
- "src/**/*.ts" - all TypeScript files under src/
- "*.{js,ts}" - all .js and .ts files
Returns list of matching file paths sorted by modification time (newest first)."""
    version = "1.0.0"

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find files matching a glob pattern.

        Args:
            params: Must contain 'pattern', optionally 'path' (search root)

        Returns:
            List of matching file paths
        """
        pattern = params.get('pattern')
        search_path = params.get('path', '.')
        limit = params.get('limit', 100)

        if not pattern:
            return {"success": False, "error": "Missing 'pattern' parameter"}

        try:
            root = Path(search_path).resolve()
            if not root.exists():
                return {"success": False, "error": f"Path not found: {search_path}"}

            # Use glob to find matches
            if '**' in pattern:
                matches = list(root.glob(pattern))
            else:
                matches = list(root.glob(pattern))

            # Filter to files only and sort by modification time
            files = [f for f in matches if f.is_file()]
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

            # Apply limit
            files = files[:limit]

            # Convert to relative paths for cleaner output
            results = []
            for f in files:
                try:
                    rel_path = f.relative_to(root)
                    results.append(str(rel_path))
                except ValueError:
                    results.append(str(f))

            logger.info(f"Glob '{pattern}' found {len(results)} files")

            return {
                "success": True,
                "result": results,
                "count": len(results),
                "pattern": pattern,
                "search_path": str(root),
                "truncated": len(matches) > limit
            }

        except Exception as e:
            logger.error(f"Glob search failed: {e}")
            return {"success": False, "error": str(e)}

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match (e.g., '**/*.py', 'src/*.js')"
                },
                "path": {
                    "type": "string",
                    "description": "Root directory to search in (default: current directory)",
                    "default": "."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 100)",
                    "default": 100
                }
            },
            "required": ["pattern"]
        }


class GrepSearchSkill(BaseSkill):
    """Skill to search file contents with regex - like Claude Code's Grep tool."""

    name = "grep_search"
    description = """Search for a pattern in file contents using regex.
Examples:
- pattern="def.*init" - find function definitions containing 'init'
- pattern="import.*pandas" - find pandas imports
- pattern="TODO|FIXME" - find todo comments
Use 'glob' parameter to filter which files to search (e.g., "*.py").
Returns matching lines with file paths and line numbers."""
    version = "1.0.0"

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search file contents with regex.

        Args:
            params: Must contain 'pattern'
                   Optional: 'path', 'glob', 'case_sensitive', 'limit', 'context_lines'

        Returns:
            List of matches with file, line number, and content
        """
        pattern = params.get('pattern')
        search_path = params.get('path', '.')
        file_glob = params.get('glob', '**/*')
        case_sensitive = params.get('case_sensitive', True)
        limit = params.get('limit', 50)
        context_lines = params.get('context_lines', 0)

        if not pattern:
            return {"success": False, "error": "Missing 'pattern' parameter"}

        try:
            # Compile regex
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return {"success": False, "error": f"Invalid regex pattern: {e}"}

            root = Path(search_path).resolve()
            if not root.exists():
                return {"success": False, "error": f"Path not found: {search_path}"}

            matches = []
            files_searched = 0
            files_with_matches = set()

            # Find files to search
            if root.is_file():
                files_to_search = [root]
            else:
                files_to_search = [f for f in root.glob(file_glob) if f.is_file()]

            # Search each file
            for file_path in files_to_search:
                if len(matches) >= limit:
                    break

                # Skip binary files
                try:
                    content = file_path.read_text(encoding='utf-8')
                except (UnicodeDecodeError, PermissionError):
                    continue

                files_searched += 1
                lines = content.split('\n')

                for line_num, line in enumerate(lines, 1):
                    if regex.search(line):
                        if len(matches) >= limit:
                            break

                        try:
                            rel_path = str(file_path.relative_to(root))
                        except ValueError:
                            rel_path = str(file_path)

                        match_info = {
                            "file": rel_path,
                            "line": line_num,
                            "content": line.strip()
                        }

                        # Add context lines if requested
                        if context_lines > 0:
                            start = max(0, line_num - 1 - context_lines)
                            end = min(len(lines), line_num + context_lines)
                            match_info["context"] = lines[start:end]

                        matches.append(match_info)
                        files_with_matches.add(rel_path)

            logger.info(f"Grep '{pattern}' found {len(matches)} matches in {len(files_with_matches)} files")

            return {
                "success": True,
                "result": matches,
                "match_count": len(matches),
                "files_with_matches": len(files_with_matches),
                "files_searched": files_searched,
                "pattern": pattern,
                "truncated": len(matches) >= limit
            }

        except Exception as e:
            logger.error(f"Grep search failed: {e}")
            return {"success": False, "error": str(e)}

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for"
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in (default: current directory)",
                    "default": "."
                },
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '**/*.py' for Python files)",
                    "default": "**/*"
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether search is case-sensitive (default: true)",
                    "default": True
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 50)",
                    "default": 50
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines to include before/after match (default: 0)",
                    "default": 0
                }
            },
            "required": ["pattern"]
        }

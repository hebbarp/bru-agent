"""
SSH Operations Skill - Remote server management via SSH/SFTP.

Provides:
- ssh_execute: Run commands on remote servers
- sftp_upload: Upload files to remote servers
- sftp_download: Download files from remote servers
- sftp_list: List remote directory contents
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from ..base import BaseSkill

# Try to import paramiko
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    logger.warning("paramiko not installed - SSH skills will not work")


class SSHExecuteSkill(BaseSkill):
    """Execute commands on remote servers via SSH."""

    name = "ssh_execute"
    description = """Execute a command on a remote server via SSH.
Use this to:
- Run commands on remote servers
- Deploy code
- Restart services
- Check server status

Returns stdout, stderr, and exit code.
Supports password and key-based authentication."""
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.default_timeout = 60

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote server hostname or IP"
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute on the remote server"
                },
                "username": {
                    "type": "string",
                    "description": "SSH username"
                },
                "password": {
                    "type": "string",
                    "description": "SSH password (or use key_path for key-based auth)"
                },
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key file (alternative to password)"
                },
                "port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22
                },
                "timeout": {
                    "type": "integer",
                    "description": "Command timeout in seconds (default: 60)",
                    "default": 60
                },
                "sudo": {
                    "type": "boolean",
                    "description": "Run command with sudo (requires password)",
                    "default": False
                }
            },
            "required": ["host", "command", "username"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a command on remote server via SSH."""
        if not PARAMIKO_AVAILABLE:
            return {"success": False, "error": "paramiko not installed. Run: pip install paramiko"}

        host = params.get('host', '').strip()
        command = params.get('command', '').strip()
        username = params.get('username', '').strip()
        password = params.get('password')
        key_path = params.get('key_path')
        port = params.get('port', 22)
        timeout = params.get('timeout', self.default_timeout)
        use_sudo = params.get('sudo', False)

        if not host or not command or not username:
            return {"success": False, "error": "host, command, and username are required"}

        if not password and not key_path:
            return {"success": False, "error": "Either password or key_path must be provided"}

        try:
            logger.info(f"SSH connecting to {username}@{host}:{port}")

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect
            connect_kwargs = {
                'hostname': host,
                'port': port,
                'username': username,
                'timeout': 30,
                'look_for_keys': False,
                'allow_agent': False
            }

            if key_path:
                key_path = Path(key_path).expanduser()
                if not key_path.exists():
                    return {"success": False, "error": f"Key file not found: {key_path}"}
                connect_kwargs['key_filename'] = str(key_path)
            else:
                connect_kwargs['password'] = password

            ssh.connect(**connect_kwargs)
            logger.info(f"SSH connected to {host}")

            # Prepare command
            if use_sudo and password:
                command = f"echo '{password}' | sudo -S {command}"

            # Execute command
            logger.info(f"Executing: {command[:100]}...")
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)

            # Read output
            stdout_text = stdout.read().decode('utf-8', errors='replace')
            stderr_text = stderr.read().decode('utf-8', errors='replace')
            exit_code = stdout.channel.recv_exit_status()

            ssh.close()

            # Truncate long output
            max_len = 30000
            stdout_truncated = len(stdout_text) > max_len
            stderr_truncated = len(stderr_text) > max_len

            if stdout_truncated:
                stdout_text = stdout_text[:max_len] + "\n... (truncated)"
            if stderr_truncated:
                stderr_text = stderr_text[:max_len] + "\n... (truncated)"

            logger.info(f"SSH command completed: exit_code={exit_code}")

            return {
                "success": exit_code == 0,
                "result": {
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "exit_code": exit_code,
                    "host": host
                },
                "error": f"Command exited with code {exit_code}" if exit_code != 0 else None
            }

        except paramiko.AuthenticationException:
            return {"success": False, "error": "SSH authentication failed - check username/password/key"}
        except paramiko.SSHException as e:
            return {"success": False, "error": f"SSH error: {str(e)}"}
        except TimeoutError:
            return {"success": False, "error": f"SSH command timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"SSH execute failed: {e}")
            return {"success": False, "error": f"SSH failed: {str(e)}"}


class SFTPUploadSkill(BaseSkill):
    """Upload files to remote servers via SFTP."""

    name = "sftp_upload"
    description = """Upload a file to a remote server via SFTP.
Use this to deploy files, configurations, or code to remote servers."""
    version = "1.0.0"

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote server hostname or IP"
                },
                "local_path": {
                    "type": "string",
                    "description": "Local file path to upload"
                },
                "remote_path": {
                    "type": "string",
                    "description": "Remote destination path"
                },
                "username": {
                    "type": "string",
                    "description": "SSH username"
                },
                "password": {
                    "type": "string",
                    "description": "SSH password"
                },
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key file"
                },
                "port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22
                }
            },
            "required": ["host", "local_path", "remote_path", "username"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Upload a file via SFTP."""
        if not PARAMIKO_AVAILABLE:
            return {"success": False, "error": "paramiko not installed"}

        host = params.get('host', '').strip()
        local_path = params.get('local_path', '').strip()
        remote_path = params.get('remote_path', '').strip()
        username = params.get('username', '').strip()
        password = params.get('password')
        key_path = params.get('key_path')
        port = params.get('port', 22)

        if not all([host, local_path, remote_path, username]):
            return {"success": False, "error": "host, local_path, remote_path, and username are required"}

        local_file = Path(local_path)
        if not local_file.exists():
            return {"success": False, "error": f"Local file not found: {local_path}"}

        try:
            logger.info(f"SFTP uploading {local_path} to {host}:{remote_path}")

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': host,
                'port': port,
                'username': username,
                'timeout': 30,
                'look_for_keys': False,
                'allow_agent': False
            }

            if key_path:
                connect_kwargs['key_filename'] = str(Path(key_path).expanduser())
            else:
                connect_kwargs['password'] = password

            ssh.connect(**connect_kwargs)
            sftp = ssh.open_sftp()

            # Upload file
            local_size = local_file.stat().st_size
            sftp.put(str(local_file), remote_path)

            # Verify
            remote_stat = sftp.stat(remote_path)
            remote_size = remote_stat.st_size

            sftp.close()
            ssh.close()

            if local_size != remote_size:
                return {
                    "success": False,
                    "error": f"Size mismatch: local={local_size}, remote={remote_size}"
                }

            logger.info(f"SFTP upload complete: {remote_path} ({remote_size} bytes)")

            return {
                "success": True,
                "result": {
                    "message": f"Uploaded {local_file.name} to {host}:{remote_path}",
                    "local_path": str(local_file),
                    "remote_path": remote_path,
                    "size_bytes": remote_size,
                    "host": host
                }
            }

        except Exception as e:
            logger.error(f"SFTP upload failed: {e}")
            return {"success": False, "error": f"SFTP upload failed: {str(e)}"}


class SFTPDownloadSkill(BaseSkill):
    """Download files from remote servers via SFTP."""

    name = "sftp_download"
    description = """Download a file from a remote server via SFTP."""
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote server hostname or IP"
                },
                "remote_path": {
                    "type": "string",
                    "description": "Remote file path to download"
                },
                "local_path": {
                    "type": "string",
                    "description": "Local destination path (optional - defaults to output dir)"
                },
                "username": {
                    "type": "string",
                    "description": "SSH username"
                },
                "password": {
                    "type": "string",
                    "description": "SSH password"
                },
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key file"
                },
                "port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22
                }
            },
            "required": ["host", "remote_path", "username"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Download a file via SFTP."""
        if not PARAMIKO_AVAILABLE:
            return {"success": False, "error": "paramiko not installed"}

        host = params.get('host', '').strip()
        remote_path = params.get('remote_path', '').strip()
        local_path = params.get('local_path', '').strip()
        username = params.get('username', '').strip()
        password = params.get('password')
        key_path = params.get('key_path')
        port = params.get('port', 22)

        if not all([host, remote_path, username]):
            return {"success": False, "error": "host, remote_path, and username are required"}

        # Default local path
        if not local_path:
            filename = Path(remote_path).name
            local_path = str(self.output_dir / filename)

        try:
            logger.info(f"SFTP downloading {host}:{remote_path} to {local_path}")

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': host,
                'port': port,
                'username': username,
                'timeout': 30,
                'look_for_keys': False,
                'allow_agent': False
            }

            if key_path:
                connect_kwargs['key_filename'] = str(Path(key_path).expanduser())
            else:
                connect_kwargs['password'] = password

            ssh.connect(**connect_kwargs)
            sftp = ssh.open_sftp()

            # Download
            sftp.get(remote_path, local_path)

            # Get size
            local_size = Path(local_path).stat().st_size

            sftp.close()
            ssh.close()

            logger.info(f"SFTP download complete: {local_path} ({local_size} bytes)")

            return {
                "success": True,
                "result": {
                    "message": f"Downloaded {remote_path} from {host}",
                    "local_path": local_path,
                    "remote_path": remote_path,
                    "size_bytes": local_size,
                    "host": host
                }
            }

        except FileNotFoundError:
            return {"success": False, "error": f"Remote file not found: {remote_path}"}
        except Exception as e:
            logger.error(f"SFTP download failed: {e}")
            return {"success": False, "error": f"SFTP download failed: {str(e)}"}


class SFTPListSkill(BaseSkill):
    """List directory contents on remote servers via SFTP."""

    name = "sftp_list"
    description = """List files and directories on a remote server via SFTP."""
    version = "1.0.0"

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote server hostname or IP"
                },
                "remote_path": {
                    "type": "string",
                    "description": "Remote directory path to list",
                    "default": "."
                },
                "username": {
                    "type": "string",
                    "description": "SSH username"
                },
                "password": {
                    "type": "string",
                    "description": "SSH password"
                },
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key file"
                },
                "port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22
                }
            },
            "required": ["host", "username"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List remote directory via SFTP."""
        if not PARAMIKO_AVAILABLE:
            return {"success": False, "error": "paramiko not installed"}

        host = params.get('host', '').strip()
        remote_path = params.get('remote_path', '.').strip()
        username = params.get('username', '').strip()
        password = params.get('password')
        key_path = params.get('key_path')
        port = params.get('port', 22)

        if not host or not username:
            return {"success": False, "error": "host and username are required"}

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': host,
                'port': port,
                'username': username,
                'timeout': 30,
                'look_for_keys': False,
                'allow_agent': False
            }

            if key_path:
                connect_kwargs['key_filename'] = str(Path(key_path).expanduser())
            else:
                connect_kwargs['password'] = password

            ssh.connect(**connect_kwargs)
            sftp = ssh.open_sftp()

            # List directory
            items = []
            for entry in sftp.listdir_attr(remote_path):
                item_type = 'directory' if entry.st_mode and (entry.st_mode & 0o40000) else 'file'
                items.append({
                    'name': entry.filename,
                    'type': item_type,
                    'size': entry.st_size,
                    'modified': entry.st_mtime
                })

            sftp.close()
            ssh.close()

            return {
                "success": True,
                "result": {
                    "path": remote_path,
                    "host": host,
                    "items": items,
                    "count": len(items)
                }
            }

        except FileNotFoundError:
            return {"success": False, "error": f"Remote path not found: {remote_path}"}
        except Exception as e:
            logger.error(f"SFTP list failed: {e}")
            return {"success": False, "error": f"SFTP list failed: {str(e)}"}

"""
Credentials Manager - Secure storage and retrieval of credentials.
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
from cryptography.fernet import Fernet
from loguru import logger


class CredentialsManager:
    """Manages encrypted credential storage and retrieval."""

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.key_file = self.data_dir / ".key"
        self.creds_file = self.data_dir / "credentials.enc"

        self._fernet = None
        self._credentials = None

    def _ensure_key(self) -> bytes:
        """Ensure encryption key exists."""
        if self.key_file.exists():
            return self.key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            # Set restrictive permissions on key file
            try:
                os.chmod(self.key_file, 0o600)
            except:
                pass  # Windows may not support chmod
            return key

    @property
    def fernet(self) -> Fernet:
        """Get Fernet instance."""
        if self._fernet is None:
            key = self._ensure_key()
            self._fernet = Fernet(key)
        return self._fernet

    def load(self) -> Dict[str, Any]:
        """Load and decrypt credentials."""
        if self._credentials is not None:
            return self._credentials

        if self.creds_file.exists():
            try:
                encrypted = self.creds_file.read_bytes()
                decrypted = self.fernet.decrypt(encrypted)
                self._credentials = json.loads(decrypted.decode())
            except Exception as e:
                logger.error(f"Failed to load credentials: {e}")
                self._credentials = {}
        else:
            self._credentials = {}

        return self._credentials

    def save(self, credentials: Dict[str, Any]):
        """Encrypt and save credentials."""
        try:
            data = json.dumps(credentials).encode()
            encrypted = self.fernet.encrypt(data)
            self.creds_file.write_bytes(encrypted)
            self._credentials = credentials
            logger.info("Credentials saved successfully")
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            raise

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a credential value.

        Args:
            section: Credential section (e.g., 'matsya', 'email')
            key: Key within section
            default: Default value if not found

        Returns:
            Credential value or default
        """
        creds = self.load()
        return creds.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any):
        """Set a credential value.

        Args:
            section: Credential section
            key: Key within section
            value: Value to set
        """
        creds = self.load()
        if section not in creds:
            creds[section] = {}
        creds[section][key] = value
        self.save(creds)

    def get_section(self, section: str) -> Dict[str, Any]:
        """Get an entire credential section.

        Args:
            section: Section name

        Returns:
            Section dictionary
        """
        return self.load().get(section, {})

    def set_section(self, section: str, data: Dict[str, Any]):
        """Set an entire credential section.

        Args:
            section: Section name
            data: Section data
        """
        creds = self.load()
        creds[section] = data
        self.save(creds)

    def delete(self, section: str, key: Optional[str] = None):
        """Delete a credential or section.

        Args:
            section: Section name
            key: Optional key to delete (if None, deletes entire section)
        """
        creds = self.load()
        if section in creds:
            if key:
                creds[section].pop(key, None)
            else:
                del creds[section]
            self.save(creds)

    def get_from_env_or_creds(self, env_var: str, section: str, key: str, default: Any = None) -> Any:
        """Get value from environment variable, falling back to stored credentials.

        Args:
            env_var: Environment variable name
            section: Credential section
            key: Key within section
            default: Default value

        Returns:
            Value from env or credentials
        """
        value = os.getenv(env_var)
        if value:
            return value
        return self.get(section, key, default)

    def list_sections(self) -> list:
        """List all credential sections."""
        return list(self.load().keys())


# Global instance
_manager = None


def get_credentials_manager() -> CredentialsManager:
    """Get global credentials manager instance."""
    global _manager
    if _manager is None:
        _manager = CredentialsManager()
    return _manager

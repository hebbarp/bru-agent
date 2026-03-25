"""
BRU - Omni AI Agent
Main entry point for the BRU system.
"""

import asyncio
import yaml
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

from bru_agent.core.agent import BruAgent
from bru_agent.core.state import StateManager


def get_bru_home() -> Path:
    """Get BRU home directory. Priority: BRU_HOME env var > ~/.bru/ > project dir."""
    if os.getenv("BRU_HOME"):
        return Path(os.getenv("BRU_HOME"))

    home_bru = Path.home() / ".bru"
    if home_bru.exists():
        return home_bru

    # Fallback to project directory (for development with pip install -e .)
    return Path(__file__).parent.parent


def get_config_path() -> Path:
    """Get config.yaml path. Checks BRU_HOME first, then project root."""
    bru_home = get_bru_home()

    # Check ~/.bru/config.yaml
    home_config = bru_home / "config.yaml"
    if home_config.exists():
        return home_config

    # Fallback: project root config.yaml (development)
    project_config = Path(__file__).parent.parent / "config.yaml"
    if project_config.exists():
        return project_config

    # Last resort: bundled default
    return Path(__file__).parent / "default_config.yaml"


def get_env_path() -> Path:
    """Get .env path. Checks BRU_HOME first, then project root."""
    bru_home = get_bru_home()

    home_env = bru_home / ".env"
    if home_env.exists():
        return home_env

    # Fallback: project root .env (development)
    return Path(__file__).parent.parent / ".env"


def load_config() -> dict:
    """Load configuration from config.yaml and environment."""
    config_path = get_config_path()

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Override with environment variables for Matsya
    config['matsya']['api_key'] = os.getenv('MATSYA_API_KEY')
    config['matsya']['user_id'] = os.getenv('MATSYA_USER_ID')
    config['matsya']['tenant_id'] = os.getenv('MATSYA_TENANT_ID')
    config['matsya']['default_workspace_id'] = os.getenv('MATSYA_DEFAULT_WORKSPACE_ID')

    # Email config
    if 'email' in config:
        config['email']['email_address'] = os.getenv('EMAIL_ADDRESS')
        config['email']['password'] = os.getenv('EMAIL_PASSWORD')
        config['email']['imap_server'] = os.getenv('IMAP_SERVER', config['email'].get('imap_server', ''))
        config['email']['smtp_server'] = os.getenv('SMTP_SERVER', config['email'].get('smtp_server', ''))

    return config


def load_authorized_groups() -> list:
    """Load authorized WhatsApp groups."""
    bru_home = get_bru_home()
    path = bru_home / "authorized_groups.yaml"
    if not path.exists():
        # Fallback to project dir
        path = Path(__file__).parent.parent / "authorized_groups.yaml"
    if not path.exists():
        return []
    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}
    return data.get('groups', [])


def load_authorized_senders() -> tuple:
    """Load authorized email senders and domains."""
    bru_home = get_bru_home()
    path = bru_home / "authorized_senders.yaml"
    if not path.exists():
        path = Path(__file__).parent.parent / "authorized_senders.yaml"
    if not path.exists():
        return [], []
    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}
    return data.get('senders', []), data.get('domains', [])


def setup_logging():
    """Configure logging."""
    bru_home = get_bru_home()
    log_dir = bru_home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Remove default logger
    logger.remove()

    # Add console logger
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>"
    )

    # Add file logger
    logger.add(
        log_dir / "bru_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"
    )


def validate_config(config: dict) -> bool:
    """Validate required configuration."""
    errors = []

    if not os.getenv('ANTHROPIC_API_KEY'):
        errors.append("ANTHROPIC_API_KEY not set")

    if not config['matsya'].get('api_key'):
        errors.append("MATSYA_API_KEY not set")

    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        return False

    return True


async def main():
    """Main entry point."""
    # Load environment variables from .env file
    env_path = get_env_path()
    load_dotenv(env_path)

    # Setup logging
    setup_logging()

    logger.info("=" * 50)
    logger.info("BRU - Omni AI Agent Starting")
    logger.info("=" * 50)

    agent = None
    try:
        # Load configuration
        config = load_config()

        # Validate config
        if not validate_config(config):
            logger.error("Configuration validation failed. Please check your .env file.")
            logger.info('Run "bru setup" to configure, or copy .env.example to .env.')
            return

        authorized_groups = load_authorized_groups()
        authorized_senders, authorized_domains = load_authorized_senders()

        logger.info(f"Matsya URL: {config['matsya'].get('base_url')}")
        logger.info(f"Poll interval: {config['matsya'].get('poll_interval_seconds', 60)}s")

        # Initialize state manager
        state = StateManager()

        # Create and initialize agent
        agent = BruAgent(config)
        await agent.initialize()

        # Run the agent
        logger.info("BRU agent is now running. Press Ctrl+C to stop.")
        await agent.run()

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if agent:
            await agent.cleanup()
        logger.info("BRU agent shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())

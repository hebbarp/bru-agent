"""
BRU CLI - Command-line interface for BRU agent.

Commands:
    bru setup       Interactive setup wizard
    bru start       Start agent (foreground)
    bru start -d    Start agent (background/daemon)
    bru stop        Stop background agent
    bru status      Show connection status
    bru config      Show current config
    bru version     Show version
"""

import os
import sys
import shutil
import signal
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

from bru_agent import __version__

# BRU home directory (~/.bru/)
BRU_HOME = Path.home() / ".bru"
BRU_ENV_FILE = BRU_HOME / ".env"
BRU_CONFIG_FILE = BRU_HOME / "config.yaml"
BRU_PID_FILE = BRU_HOME / "bru.pid"
BRU_LOG_DIR = BRU_HOME / "logs"
BRU_DATA_DIR = BRU_HOME / "data"


def ensure_bru_home():
    """Create ~/.bru/ directory structure if it doesn't exist."""
    BRU_HOME.mkdir(exist_ok=True)
    BRU_LOG_DIR.mkdir(exist_ok=True)
    BRU_DATA_DIR.mkdir(exist_ok=True)


def load_bru_env():
    """Load environment from ~/.bru/.env if it exists."""
    if BRU_ENV_FILE.exists():
        load_dotenv(BRU_ENV_FILE)
        return True
    return False


def get_default_config_path():
    """Get path to the bundled default_config.yaml."""
    return Path(__file__).parent / "default_config.yaml"


@click.group()
def main():
    """BRU - AI agent that connects to Matsya platform."""
    pass


@main.command()
def version():
    """Show BRU version."""
    click.echo(f"BRU Agent v{__version__}")


@main.command()
def setup():
    """Interactive setup wizard - configure BRU for first use."""
    click.echo(f"BRU Agent v{__version__} - Setup Wizard")
    click.echo("=" * 40)
    click.echo()

    ensure_bru_home()

    # 1. Matsya URL
    matsya_url = click.prompt(
        "Matsya URL",
        default="https://matsyaai.com",
        type=str
    )
    matsya_url = matsya_url.rstrip("/")

    # 2. Matsya API Key
    click.echo()
    click.echo("Get your API key from Matsya: Settings > API Keys")
    matsya_api_key = click.prompt("Matsya API Key (msk_...)", type=str)

    # 3. Anthropic API Key
    click.echo()
    click.echo("Get your key from: https://console.anthropic.com/")
    anthropic_api_key = click.prompt("Anthropic API Key (sk-ant-...)", type=str)

    # 4. User/Tenant IDs (optional)
    click.echo()
    matsya_user_id = click.prompt("Matsya User ID", default="", type=str)
    matsya_tenant_id = click.prompt("Matsya Tenant ID", default="", type=str)
    matsya_workspace_id = click.prompt("Matsya Workspace ID", default="", type=str)

    # 5. Test connection
    click.echo()
    click.echo("Testing connection to Matsya...")
    connection_ok = _test_matsya_connection(matsya_url, matsya_api_key)

    if connection_ok:
        click.secho("  Connected!", fg="green")
    else:
        click.secho("  Could not connect (will save config anyway)", fg="yellow")

    # 6. Save .env
    env_lines = [
        f"BRU_WORKER_TYPE=local",
        f"ANTHROPIC_API_KEY={anthropic_api_key}",
        f"MATSYA_API_KEY={matsya_api_key}",
    ]
    if matsya_user_id:
        env_lines.append(f"MATSYA_USER_ID={matsya_user_id}")
    if matsya_tenant_id:
        env_lines.append(f"MATSYA_TENANT_ID={matsya_tenant_id}")
    if matsya_workspace_id:
        env_lines.append(f"MATSYA_DEFAULT_WORKSPACE_ID={matsya_workspace_id}")

    BRU_ENV_FILE.write_text("\n".join(env_lines) + "\n")
    click.echo(f"  Saved credentials to {BRU_ENV_FILE}")

    # 7. Save config.yaml (copy default if not exists, update matsya URL)
    if not BRU_CONFIG_FILE.exists():
        default_config = get_default_config_path()
        if default_config.exists():
            shutil.copy2(default_config, BRU_CONFIG_FILE)
        else:
            # Minimal fallback config
            config = {
                "system": {"name": "bru", "version": __version__},
                "matsya": {"base_url": matsya_url, "poll_interval_seconds": 60},
                "agent": {"mode": "active", "max_concurrent_tasks": 3},
                "skills": {"auto_discover": True},
            }
            BRU_CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False))

    # Update matsya base_url in config
    config = yaml.safe_load(BRU_CONFIG_FILE.read_text())
    config["matsya"]["base_url"] = matsya_url
    BRU_CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False))
    click.echo(f"  Saved config to {BRU_CONFIG_FILE}")

    click.echo()
    click.secho("Setup complete!", fg="green")
    click.echo('Run "bru start" to begin.')


def _test_matsya_connection(url: str, api_key: str) -> bool:
    """Test connection to Matsya."""
    try:
        import httpx
        response = httpx.get(
            f"{url}/api/bru-status.php",
            params={"action": "heartbeat"},
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


@main.command()
@click.option("-d", "--daemon", is_flag=True, help="Run in background (daemon mode)")
def start(daemon):
    """Start the BRU agent."""
    ensure_bru_home()

    if not BRU_ENV_FILE.exists():
        click.secho("BRU is not configured. Run 'bru setup' first.", fg="red")
        raise SystemExit(1)

    load_bru_env()

    if daemon:
        _start_daemon()
    else:
        _start_foreground()


def _start_foreground():
    """Start BRU agent in the foreground."""
    click.echo(f"BRU Agent v{__version__}")
    click.echo("=" * 40)

    # Set BRU_HOME env var so main.py knows where to find config
    os.environ["BRU_HOME"] = str(BRU_HOME)

    import asyncio
    from bru_agent.main import main as agent_main
    try:
        asyncio.run(agent_main())
    except KeyboardInterrupt:
        click.echo("\nBRU agent stopped.")


def _start_daemon():
    """Start BRU agent as a background process."""
    import subprocess

    if BRU_PID_FILE.exists():
        pid = BRU_PID_FILE.read_text().strip()
        if _is_process_running(int(pid)):
            click.secho(f"BRU is already running (PID {pid})", fg="yellow")
            return

    # Launch as background process
    env = os.environ.copy()
    env["BRU_HOME"] = str(BRU_HOME)
    # Load .env vars into the subprocess environment
    load_bru_env()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("ANTHROPIC_", "MATSYA_", "BRU_"))})

    log_file = BRU_LOG_DIR / "bru_daemon.log"

    proc = subprocess.Popen(
        [sys.executable, "-m", "bru_agent.main"],
        env=env,
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    BRU_PID_FILE.write_text(str(proc.pid))
    click.echo(f"BRU agent started in background (PID {proc.pid})")
    click.echo(f"Logs: {log_file}")


@main.command()
def stop():
    """Stop the background BRU agent."""
    if not BRU_PID_FILE.exists():
        click.echo("No BRU agent running (no PID file found).")
        return

    pid = int(BRU_PID_FILE.read_text().strip())

    if not _is_process_running(pid):
        click.echo(f"BRU agent (PID {pid}) is not running. Cleaning up PID file.")
        BRU_PID_FILE.unlink()
        return

    try:
        os.kill(pid, signal.SIGTERM)
        click.secho(f"BRU agent (PID {pid}) stopped.", fg="green")
    except OSError as e:
        click.secho(f"Failed to stop BRU agent: {e}", fg="red")
    finally:
        if BRU_PID_FILE.exists():
            BRU_PID_FILE.unlink()


@main.command()
def status():
    """Show BRU agent status."""
    ensure_bru_home()
    load_bru_env()

    click.echo(f"BRU Agent v{__version__}")
    click.echo("-" * 30)

    # Check if running
    if BRU_PID_FILE.exists():
        pid = int(BRU_PID_FILE.read_text().strip())
        if _is_process_running(pid):
            click.secho(f"Status: Running (PID {pid})", fg="green")
        else:
            click.secho("Status: Not running (stale PID file)", fg="yellow")
            BRU_PID_FILE.unlink()
    else:
        click.echo("Status: Not running")

    # Check config
    if BRU_CONFIG_FILE.exists():
        config = yaml.safe_load(BRU_CONFIG_FILE.read_text())
        matsya_url = config.get("matsya", {}).get("base_url", "not set")
        click.echo(f"Matsya: {matsya_url}")
    else:
        click.secho("Config: Not configured (run 'bru setup')", fg="yellow")
        return

    # Check Matsya connection
    api_key = os.getenv("MATSYA_API_KEY", "")
    if api_key and matsya_url:
        connected = _test_matsya_connection(matsya_url, api_key)
        if connected:
            click.secho("Connection: Online", fg="green")
        else:
            click.secho("Connection: Offline", fg="red")
    else:
        click.echo("Connection: No API key configured")

    click.echo(f"Config: {BRU_CONFIG_FILE}")
    click.echo(f"Logs: {BRU_LOG_DIR}")


@main.command()
def config():
    """Show current BRU configuration."""
    if not BRU_CONFIG_FILE.exists():
        click.secho("No config found. Run 'bru setup' first.", fg="yellow")
        return

    click.echo(f"Config file: {BRU_CONFIG_FILE}")
    click.echo("-" * 40)
    click.echo(BRU_CONFIG_FILE.read_text())


def _is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    main()

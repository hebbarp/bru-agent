"""
Action Ledger — Persistent audit trail for tool executions.

Records every tool call's ground truth (success/fail) during a session,
persists to disk in a human-readable format, and provides playback.

Format (one file per day, multiple sessions):

    SESSION 2026-03-25T09:32:15 | task:"AI CCTV Market Report" | model:claude-sonnet-4
      09:32:16  OK   web_search->"ICC rankings" [results:5]
      09:32:18  OK   create_excel->rankings.xlsx [bytes:4096]
      09:32:20  FAIL send_email->prashanth@knobly.com [code:404 reason:endpoint_missing]
      ---
      VERIFICATION: triggered (1 failure, 1 correction)
      TOKENS: 2340 in + 890 out = 3230
      DURATION: 12.3s
      OUTCOME: corrected
    END SESSION
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


class ActionLedger:
    """Persistent action ledger for a single session."""

    def __init__(self, storage_dir: str = "./data/ledger"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.session_id: Optional[str] = None
        self.task_name: Optional[str] = None
        self.model: str = ""
        self.entries: List[Dict[str, Any]] = []
        self.start_time: Optional[datetime] = None
        self.verification_triggered: bool = False
        self.verification_result: str = ""
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def start_session(self, task_name: str, model: str = ""):
        """Begin a new session."""
        self.start_time = datetime.now()
        self.session_id = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.task_name = task_name
        self.model = model
        self.entries = []
        self.verification_triggered = False
        self.verification_result = ""
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def record(self, tool: str, target: str, success: bool,
               summary: str = "", metadata: Optional[Dict] = None):
        """Record a tool execution."""
        entry = {
            'timestamp': datetime.now(),
            'tool': tool,
            'target': target,
            'success': success,
            'summary': summary,
            'metadata': metadata or {},
        }
        self.entries.append(entry)
        return entry

    def record_verification(self, triggered: bool, result: str = ""):
        """Record whether the verification pass was triggered and its outcome."""
        self.verification_triggered = triggered
        self.verification_result = result

    def record_tokens(self, input_tokens: int, output_tokens: int):
        """Record token usage."""
        self.total_input_tokens = input_tokens
        self.total_output_tokens = output_tokens

    @property
    def has_failures(self) -> bool:
        return any(not e['success'] for e in self.entries)

    @property
    def failure_count(self) -> int:
        return sum(1 for e in self.entries if not e['success'])

    @property
    def success_count(self) -> int:
        return sum(1 for e in self.entries if e['success'])

    def format_entry(self, entry: Dict) -> str:
        """Format a single ledger entry as LNTL."""
        ts = entry['timestamp'].strftime("%H:%M:%S")
        status = "OK  " if entry['success'] else "FAIL"
        line = f"  {ts}  {status} {entry['tool']}->{entry['target']}"

        meta = entry.get('metadata', {})
        if entry['summary'] and not entry['success']:
            meta['error'] = entry['summary'][:80]
        elif entry['summary'] and entry['success']:
            meta['result'] = entry['summary'][:80]

        if meta:
            pairs = " ".join(f"{k}:{v}" for k, v in meta.items())
            line += f" [{pairs}]"

        return line

    def format_session(self) -> str:
        """Format the entire session as a human-readable block."""
        if not self.start_time:
            return ""

        lines = []

        # Header
        ts = self.start_time.strftime("%Y-%m-%d %H:%M:%S")
        task = self.task_name or "unnamed"
        lines.append(f"SESSION {ts} | task:\"{task}\" | model:{self.model}")

        # Entries
        for entry in self.entries:
            lines.append(self.format_entry(entry))

        # Separator
        lines.append("  ---")

        # Summary
        if self.verification_triggered:
            lines.append(f"  VERIFICATION: triggered ({self.failure_count} failure(s), {self.verification_result})")
        elif self.entries:
            lines.append(f"  VERIFICATION: not needed (all {self.success_count} actions succeeded)")

        total_tokens = self.total_input_tokens + self.total_output_tokens
        if total_tokens > 0:
            lines.append(f"  TOKENS: {self.total_input_tokens} in + {self.total_output_tokens} out = {total_tokens}")

        if self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()
            lines.append(f"  DURATION: {duration:.1f}s")

        outcome = "all succeeded"
        if self.has_failures and self.verification_triggered:
            outcome = "corrected"
        elif self.has_failures:
            outcome = "failures present (no verification)"
        lines.append(f"  OUTCOME: {outcome}")

        lines.append("END SESSION")
        lines.append("")

        return "\n".join(lines)

    def save(self):
        """Save session to daily ledger file."""
        if not self.entries:
            return

        date_str = datetime.now().strftime("%Y-%m-%d")
        filepath = self.storage_dir / f"ledger_{date_str}.log"

        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(self.format_session())
            f.write("\n")

    def close(self):
        """End session and save."""
        self.save()

    # ========== PLAYBACK / REVIEW ==========

    @classmethod
    def list_days(cls, storage_dir: str = "./data/ledger") -> List[str]:
        """List all days that have ledger entries."""
        path = Path(storage_dir)
        if not path.exists():
            return []
        files = sorted(path.glob("ledger_*.log"))
        return [f.stem.replace("ledger_", "") for f in files]

    @classmethod
    def read_day(cls, date_str: str, storage_dir: str = "./data/ledger") -> str:
        """Read the full ledger for a given day."""
        filepath = Path(storage_dir) / f"ledger_{date_str}.log"
        if not filepath.exists():
            return f"No ledger found for {date_str}"
        return filepath.read_text(encoding='utf-8')

    @classmethod
    def read_latest(cls, storage_dir: str = "./data/ledger", count: int = 5) -> str:
        """Read the most recent sessions."""
        path = Path(storage_dir)
        if not path.exists():
            return "No ledger data found."

        files = sorted(path.glob("ledger_*.log"), reverse=True)
        if not files:
            return "No ledger data found."

        # Read from newest file
        content = files[0].read_text(encoding='utf-8')
        sessions = content.split("END SESSION")

        # Take last N sessions
        recent = sessions[-(count + 1):-1] if len(sessions) > count else sessions[:-1]
        return ("END SESSION\n".join(recent) + "END SESSION").strip()

    @classmethod
    def read_failures(cls, storage_dir: str = "./data/ledger", days: int = 7) -> str:
        """Read only sessions that had failures, from the last N days."""
        path = Path(storage_dir)
        if not path.exists():
            return "No ledger data found."

        files = sorted(path.glob("ledger_*.log"), reverse=True)[:days]
        failures = []

        for f in files:
            content = f.read_text(encoding='utf-8')
            for session in content.split("END SESSION"):
                if "FAIL " in session and session.strip():
                    failures.append(session.strip() + "\nEND SESSION")

        if not failures:
            return "No failures found in the last {days} days."

        return "\n\n".join(failures)

"""
Business logic for MDM failures reporting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .jamf_client import JamfClient
from .models import MdmCommand
from .utils import parse_line_delimited_file


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    now = datetime.now(timezone.utc)
    try:
        if value.endswith("h"):
            hours = float(value[:-1])
            return now - timedelta(hours=hours)
        if value.endswith("d"):
            days = float(value[:-1])
            return now - timedelta(days=days)
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise ValueError(f"Invalid --since value: {value}")


def _timestamp_to_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def mdm_failures_report(
    scope_kind: str,
    scope_values: Optional[Iterable[str]],
    client: JamfClient,
    *,
    since: Optional[str],
    command_types: Optional[List[str]],
    logger: Optional[logging.Logger] = None,
) -> Tuple[Dict, int]:
    """
    Generate a report of failed MDM commands for specified scope.

    This function:
    1. Fetches all MDM commands from Jamf
    2. Filters by scope (global, specific computers, or list)
    3. Optionally filters by time window and command types
    4. Aggregates failures by command type and device

    Args:
        scope_kind: One of "global", "computer-id", "serial", or "list"
        scope_values: List of values matching scope_kind (e.g., computer IDs for "computer-id")
        client: JamfClient instance for API calls
        since: Optional time filter - ISO8601 timestamp or relative (e.g., "24h", "7d")
        command_types: Optional list of command type names to filter by
        logger: Optional logger instance

    Returns:
        Tuple of (results, exit_code) where:
        - results: Dict with "generatedAt", "summary" (by command type), and "failures" (by device)
        - exit_code: Always 0 (informational report)

    Example:
        >>> results, _ = mdm_failures_report("global", None, client, since="24h")
        >>> print(f"Failed commands: {sum(results['summary'].values())}")
    """
    log = logger or logging.getLogger(__name__)
    scope_values = list(scope_values or [])
    since_dt = _parse_since(since)
    all_commands = client.list_computer_commands()
    if not isinstance(all_commands, list):
        log.warning("Unexpected command payload type: %s", type(all_commands))
        all_commands = []

    allowed_devices: Optional[Set[int]] = None
    if scope_kind != "global":
        ids: Set[int] = set()
        serials: Set[str] = set()
        if scope_kind == "computer-id":
            ids = {int(v) for v in scope_values}
        elif scope_kind == "serial":
            serials = {v.upper() for v in scope_values}
        elif scope_kind == "list":
            for item in scope_values:
                if item.isdigit():
                    ids.add(int(item))
                else:
                    serials.add(item.upper())
        inventory = client.list_computers_inventory(ids=ids or None, serials=serials or None)
        allowed_devices = {c.id for c in inventory}
        log.debug("Limiting to devices: %s", allowed_devices)

    filtered: List[MdmCommand] = []
    for cmd in all_commands:
        if cmd.status.lower() != "failed":
            continue
        if allowed_devices is not None and cmd.device_id not in allowed_devices:
            continue
        if command_types and cmd.command_name not in command_types:
            continue
        if since_dt:
            ts = _timestamp_to_dt(cmd.completed or cmd.issued)
            if ts and ts < since_dt:
                continue
        filtered.append(cmd)

    summary_by_command: Dict[str, int] = {}
    failures_by_device: Dict[int, List[MdmCommand]] = {}
    for cmd in filtered:
        summary_by_command[cmd.command_name] = summary_by_command.get(cmd.command_name, 0) + 1
        failures_by_device.setdefault(cmd.device_id, []).append(cmd)

    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": summary_by_command,
        "failures": [
            {
                "deviceId": device_id,
                "count": len(cmds),
                "commands": [
                    {
                        "uuid": cmd.uuid,
                        "command": cmd.command_name,
                        "status": cmd.status,
                        "issued": cmd.issued,
                        "completed": cmd.completed,
                    }
                    for cmd in cmds
                ],
            }
            for device_id, cmds in failures_by_device.items()
        ],
    }
    log.info("Found %s failed commands", len(filtered))
    return results, 0

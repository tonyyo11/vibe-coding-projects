"""
Business logic for the policy-failures command.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .jamf_client import DataModelError, JamfCliError, JamfClient
from .models import Computer, PolicyExecutionStatus, Policy
from .utils import validate_policy_ids


def load_policy_ids(policy_ids: Iterable[int], policy_ids_file: Optional[str]) -> List[int]:
    """
    Load and validate policy IDs from CLI arguments and/or a file.

    Args:
        policy_ids: Policy IDs from CLI arguments
        policy_ids_file: Optional path to file with policy IDs (one per line)

    Returns:
        Validated list of policy IDs

    Raises:
        ValueError: If any policy ID is invalid or file contains non-numeric data
        FileNotFoundError: If policy_ids_file is specified but doesn't exist
    """
    ids = list(policy_ids) if policy_ids else []

    if policy_ids_file:
        file_path = Path(policy_ids_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Policy IDs file not found: {policy_ids_file}")

        for line_num, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):  # Skip empty lines and comments
                continue
            try:
                pid = int(line)
                ids.append(pid)
            except ValueError as exc:
                raise ValueError(f"Invalid policy ID on line {line_num} in {policy_ids_file}: '{line}'") from exc

    if not ids:
        raise ValueError("No policy IDs provided. Use --policy-id or --policy-ids-file")

    # Validate all policy IDs
    return validate_policy_ids(ids)


def _get_all_inventory(client: JamfClient) -> Dict[int, Computer]:
    inventory = client.list_computers_inventory()
    return {c.id: c for c in inventory}


def _get_group_members(client: JamfClient, group_id: int, cache: Dict[int, List[Computer]]) -> List[Computer]:
    if group_id not in cache:
        cache[group_id] = client.get_computer_group_members(group_id)
    return cache[group_id]


def _resolve_scope_computers(
    policy: Policy,
    client: JamfClient,
    *,
    limiting_group_id: Optional[int],
    inventory_cache: Dict[int, Computer],
    group_cache: Dict[int, List[Computer]],
) -> Dict[int, Computer]:
    included: Set[int] = set()
    excluded: Set[int] = set()

    if policy.scope.all_computers:
        if not inventory_cache:
            inventory_cache.update(_get_all_inventory(client))
        included.update(inventory_cache.keys())
    else:
        for gid in policy.scope.included_group_ids:
            members = _get_group_members(client, gid, group_cache)
            for comp in members:
                included.add(comp.id)
                if comp.id not in inventory_cache:
                    inventory_cache[comp.id] = comp
        included.update(policy.scope.included_computer_ids)

    for gid in policy.scope.excluded_group_ids:
        members = _get_group_members(client, gid, group_cache)
        for comp in members:
            excluded.add(comp.id)
            if comp.id not in inventory_cache:
                inventory_cache[comp.id] = comp
    excluded.update(policy.scope.excluded_computer_ids)

    if limiting_group_id:
        limiting_members = _get_group_members(client, limiting_group_id, group_cache)
        limiting_set = {c.id for c in limiting_members}
        included = included & limiting_set if included else limiting_set

    scoped_ids = included - excluded

    # Refresh inventory details for scoped devices to ensure we have last_check_in and serials.
    if scoped_ids:
        refreshed = client.list_computers_inventory(ids=scoped_ids)
        for comp in refreshed:
            inventory_cache[comp.id] = comp

    return {cid: inventory_cache[cid] for cid in scoped_ids if cid in inventory_cache}


def _classify_history(
    entries: List[PolicyExecutionStatus],
    cr_start_dt: Optional[datetime] = None,
    cr_end_dt: Optional[datetime] = None,
    filter_to_cr_window: bool = True
) -> Tuple[int, int, int, Optional[str]]:
    """
    Classify policy execution history entries.

    When filtering is enabled, prefers runs within CR window but falls back to most recent
    run if no CR-window runs exist. This prevents >100% rates while still showing status.

    Args:
        entries: List of PolicyExecutionStatus objects for a specific device and policy
        cr_start_dt: Optional CR window start datetime
        cr_end_dt: Optional CR window end datetime
        filter_to_cr_window: If True, deduplicates and prefers CR window runs (prevents >100% rates)

    Returns:
        Tuple of (completed_count, failed_count, pending_count, last_failure_time)
    """
    completed = failed = pending = 0
    last_failure_time: Optional[str] = None

    if not entries:
        pending = 1
        return completed, failed, pending, last_failure_time

    # Filter to CR window if enabled and dates provided
    filtered_entries = entries
    if filter_to_cr_window and cr_start_dt and cr_end_dt:
        filtered_entries = []
        for entry in entries:
            if entry.last_run_time:
                try:
                    run_dt = datetime.fromisoformat(entry.last_run_time.replace("Z", "+00:00"))
                    if run_dt.tzinfo is None:
                        run_dt = run_dt.replace(tzinfo=timezone.utc)

                    # Only include if within CR window
                    if cr_start_dt <= run_dt <= cr_end_dt:
                        filtered_entries.append(entry)
                except Exception:
                    pass  # Skip entries with invalid timestamps

    # FALLBACK: If no runs in CR window, use most recent run overall
    # This prevents showing "pending" when policy ran outside window
    # while still preventing >100% rates from multiple runs
    if not filtered_entries and filter_to_cr_window and entries:
        filtered_entries = entries[-1:]  # Use most recent run overall

    if not filtered_entries:
        # Truly no executions at all
        pending = 1
        return completed, failed, pending, last_failure_time

    # Deduplicate: Only count the most recent execution status
    # This prevents >100% completion rates when policies run multiple times
    latest_entry = filtered_entries[-1]
    status = (latest_entry.last_status or "").lower()

    if status == "failed":
        failed = 1
        last_failure_time = latest_entry.last_run_time
    elif status == "completed" or status == "complete":
        completed = 1
    else:
        pending = 1

    return completed, failed, pending, last_failure_time


def evaluate_policy_failures(
    policy_ids: List[int],
    client: JamfClient,
    limiting_group_id: Optional[int],
    cr_start: Optional[str] = None,
    cr_end: Optional[str] = None,
    filter_to_cr_window: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Dict], int]:
    """
    Evaluate policy execution failures across scoped computers.

    This function:
    1. Fetches policy details and determines scoped computers
    2. Retrieves execution history for each computer
    3. Classifies executions as completed, failed, pending, or offline
    4. Returns detailed results and appropriate exit code

    Args:
        policy_ids: List of Jamf policy IDs to evaluate
        client: JamfClient instance for API calls
        limiting_group_id: Optional group ID to constrain "All Computers" scope
        cr_start: ISO8601 timestamp marking change request start; devices not checked in since are marked offline
        cr_end: ISO8601 timestamp marking change request end; used for filtering policy executions
        filter_to_cr_window: If True, only count policy executions within CR window (prevents >100% rates)
        logger: Optional logger instance

    Returns:
        Tuple of (results, exit_code) where:
        - results: List of dicts containing policy details and execution stats
        - exit_code: 0 if no failures, 1 if failures detected

    Example:
        >>> results, exit_code = evaluate_policy_failures(
        ...     [123, 456], client, None,
        ...     cr_start="2024-01-01T00:00:00Z",
        ...     cr_end="2024-01-07T23:59:59Z",
        ...     filter_to_cr_window=True
        ... )
        >>> print(f"Exit code: {exit_code}, Failures: {results[0]['results']['failed']}")
    """
    log = logger or logging.getLogger(__name__)
    group_cache: Dict[int, List[Computer]] = {}
    inventory_cache: Dict[int, Computer] = {}
    results = []
    exit_code = 0

    cr_start_dt: Optional[datetime] = None
    cr_end_dt: Optional[datetime] = None

    if cr_start:
        try:
            cr_start_dt = datetime.fromisoformat(cr_start.replace("Z", "+00:00"))
            if cr_start_dt.tzinfo is None:
                cr_start_dt = cr_start_dt.replace(tzinfo=timezone.utc)
        except Exception as exc:
            raise ValueError(f"Invalid --cr-start value: {cr_start}") from exc

    if cr_end:
        try:
            cr_end_dt = datetime.fromisoformat(cr_end.replace("Z", "+00:00"))
            if cr_end_dt.tzinfo is None:
                cr_end_dt = cr_end_dt.replace(tzinfo=timezone.utc)
        except Exception as exc:
            raise ValueError(f"Invalid --cr-end value: {cr_end}") from exc

    for pid in policy_ids:
        log.info("Processing policy %s", pid)
        policy = client.get_policy(pid)
        computers = _resolve_scope_computers(
            policy, client, limiting_group_id=limiting_group_id, inventory_cache=inventory_cache, group_cache=group_cache
        )
        total = len(computers)
        completed_total = failed_total = pending_total = offline_total = 0
        failed_devices = []
        offline_devices = []
        for idx, comp in enumerate(computers.values(), start=1):
            if idx % 50 == 0:
                log.info("Processed %s/%s computers for policy %s", idx, total, pid)

            if cr_start_dt:
                last_check = comp.last_check_in
                last_check_dt = None
                if last_check:
                    try:
                        last_check_dt = datetime.fromisoformat(last_check.replace("Z", "+00:00"))
                        if last_check_dt.tzinfo is None:
                            last_check_dt = last_check_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        last_check_dt = None
                if not last_check_dt or last_check_dt < cr_start_dt:
                    offline_total += 1
                    offline_devices.append(
                        {
                            "computerId": comp.id,
                            "name": comp.name,
                            "serial": comp.serial,
                            "lastCheckIn": comp.last_check_in,
                        }
                    )
                    continue

            history = client.get_computer_history(comp.id)
            relevant = [entry for entry in history if entry.policy_id == pid]
            completed, failed, pending, last_failure_time = _classify_history(
                relevant,
                cr_start_dt=cr_start_dt,
                cr_end_dt=cr_end_dt,
                filter_to_cr_window=filter_to_cr_window
            )
            completed_total += completed
            failed_total += failed
            pending_total += pending
            if failed > 0:
                failed_devices.append(
                    {
                        "computerId": comp.id,
                        "computerName": comp.name,  # Changed from "name" to match Excel export
                        "serial": comp.serial,
                        "policyId": pid,
                        "policyName": policy.name,
                        "status": "Failed",
                        "lastFailure": last_failure_time,
                    }
                )
        # Set exit code 1 if there are failures or offline devices (when cr_start is specified)
        if failed_total > 0:
            exit_code = 1
        if cr_start_dt and offline_total > 0:
            exit_code = 1
        results.append(
            {
                "id": pid,
                "name": policy.name,
                "enabled": policy.enabled,
                "devicesInScope": total,
                "results": {
                    "completed": completed_total,
                    "failed": failed_total,
                    "pending": pending_total,
                    "offline": offline_total,
                },
                "failedDevices": failed_devices,
                "offlineDevices": offline_devices,
            }
        )

    return results, exit_code

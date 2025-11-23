"""
CR Readiness Pre-Flight Check

Validates device health and readiness before a Change Request window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .jamf_client import JamfClient
from .models import Computer


@dataclass
class ReadinessCheck:
    """Result of a readiness check for a single device"""
    computer_id: int
    computer_name: str
    serial: Optional[str]
    ready: bool
    issues: List[str]
    warnings: List[str]
    last_check_in: Optional[str]
    disk_free_gb: Optional[float]
    disk_free_percent: Optional[float]
    battery_percent: Optional[int]
    os_version: Optional[str]


def analyze_cr_readiness(
    client: JamfClient,
    scope_group_id: Optional[int] = None,
    min_check_in_hours: int = 24,
    min_disk_space_gb: float = 10.0,
    min_battery_percent: int = 20,
    logger: Optional[logging.Logger] = None,
) -> tuple[Dict[str, Any], int]:
    """
    Analyze CR readiness for devices in scope.

    Args:
        client: JamfClient instance
        scope_group_id: Optional group ID to limit scope
        min_check_in_hours: Devices must have checked in within this many hours
        min_disk_space_gb: Minimum free disk space in GB
        min_battery_percent: Minimum battery level for laptops
        logger: Optional logger

    Returns:
        Tuple of (results dict, exit code)
    """
    log = logger or logging.getLogger(__name__)

    # Determine scope
    if scope_group_id:
        log.info(f"Fetching devices in group {scope_group_id}...")
        computers = client.get_computer_group_members(scope_group_id)
    else:
        log.info("Fetching all devices...")
        computers = client.list_computers_inventory()

    total_devices = len(computers)
    log.info(f"Analyzing readiness for {total_devices} devices...")

    # Calculate check-in threshold
    check_in_threshold = datetime.now(timezone.utc) - timedelta(hours=min_check_in_hours)

    readiness_checks: List[ReadinessCheck] = []
    ready_count = 0
    not_ready_count = 0

    # Analyze each device
    for idx, computer in enumerate(computers, start=1):
        if idx % 50 == 0 or idx == total_devices:
            log.info(f"Analyzing device {idx}/{total_devices}...")

        issues: List[str] = []
        warnings: List[str] = []

        # Get detailed information
        try:
            detail = client.get_computer_detail(computer.id)
        except Exception as e:
            log.warning(f"Failed to get details for {computer.name}: {e}")
            detail = {}

        # Check 1: Last check-in time
        last_check_in_str = computer.last_check_in
        if last_check_in_str:
            try:
                # Parse ISO8601 timestamp
                if last_check_in_str.endswith('Z'):
                    last_check_in = datetime.fromisoformat(last_check_in_str.replace('Z', '+00:00'))
                else:
                    last_check_in = datetime.fromisoformat(last_check_in_str)

                if last_check_in < check_in_threshold:
                    hours_ago = (datetime.now(timezone.utc) - last_check_in).total_seconds() / 3600
                    issues.append(f"Last check-in {hours_ago:.1f} hours ago (threshold: {min_check_in_hours}h)")
            except (ValueError, AttributeError) as e:
                warnings.append(f"Could not parse check-in time: {last_check_in_str}")
        else:
            issues.append("No check-in time available")

        # Check 2: Disk space
        disk_free_gb = None
        disk_free_percent = None

        storage = detail.get("storage", {})
        if storage:
            # Parse storage information
            disks = storage.get("disks", [])
            if disks and len(disks) > 0:
                boot_disk = disks[0]  # Usually the boot disk
                available_mb = boot_disk.get("availableMegabytes", 0)
                percent_free = boot_disk.get("percentFree")

                if available_mb:
                    disk_free_gb = available_mb / 1024.0

                    if disk_free_gb < min_disk_space_gb:
                        issues.append(f"Low disk space: {disk_free_gb:.1f} GB free (minimum: {min_disk_space_gb} GB)")
                    elif disk_free_gb < min_disk_space_gb * 1.5:
                        warnings.append(f"Disk space marginal: {disk_free_gb:.1f} GB free")

                if percent_free is not None:
                    disk_free_percent = float(percent_free)

        # Check 3: Battery level (for laptops)
        battery_percent = None
        hardware = detail.get("hardware", {})
        if hardware:
            # Check if it's a laptop
            model = hardware.get("model", "").lower()
            is_laptop = any(keyword in model for keyword in ["macbook", "book"])

            if is_laptop:
                # Try to get battery info
                battery_capacity = hardware.get("batteryCapacityPercent")
                if battery_capacity is not None:
                    battery_percent = int(battery_capacity)

                    if battery_percent < min_battery_percent:
                        issues.append(f"Low battery: {battery_percent}% (minimum: {min_battery_percent}%)")
                    elif battery_percent < min_battery_percent + 20:
                        warnings.append(f"Battery marginal: {battery_percent}%")

        # Check 4: Pending MDM commands
        pending_commands = []
        try:
            all_commands = client.list_computer_commands()
            device_commands = [cmd for cmd in all_commands if cmd.device_id == computer.id]
            pending_commands = [cmd for cmd in device_commands if cmd.status.lower() in ["pending", "queued"]]

            if len(pending_commands) > 5:
                warnings.append(f"{len(pending_commands)} pending MDM commands")
        except Exception as e:
            log.debug(f"Could not check MDM commands for {computer.name}: {e}")

        # Determine if device is ready
        is_ready = len(issues) == 0

        readiness_checks.append(ReadinessCheck(
            computer_id=computer.id,
            computer_name=computer.name,
            serial=computer.serial,
            ready=is_ready,
            issues=issues,
            warnings=warnings,
            last_check_in=last_check_in_str,
            disk_free_gb=disk_free_gb,
            disk_free_percent=disk_free_percent,
            battery_percent=battery_percent,
            os_version=computer.os_version,
        ))

        if is_ready:
            ready_count += 1
        else:
            not_ready_count += 1

    # Calculate readiness rate
    readiness_rate = (ready_count / total_devices * 100) if total_devices > 0 else 0

    # Categorize not-ready devices by issue type
    issue_categories: Dict[str, int] = {}
    for check in readiness_checks:
        if not check.ready:
            for issue in check.issues:
                # Categorize by issue type
                if "check-in" in issue.lower():
                    issue_categories["Offline/Not Checking In"] = issue_categories.get("Offline/Not Checking In", 0) + 1
                elif "disk" in issue.lower():
                    issue_categories["Low Disk Space"] = issue_categories.get("Low Disk Space", 0) + 1
                elif "battery" in issue.lower():
                    issue_categories["Low Battery"] = issue_categories.get("Low Battery", 0) + 1

    # Generate recommendations
    recommendations = []
    if readiness_rate < 80:
        recommendations.append("⚠️  Less than 80% of devices are ready - consider delaying CR window")
    if issue_categories.get("Offline/Not Checking In", 0) > total_devices * 0.1:
        recommendations.append(f"⚠️  {issue_categories['Offline/Not Checking In']} devices offline - use wake-devices command")
    if issue_categories.get("Low Disk Space", 0) > 0:
        recommendations.append(f"⚠️  {issue_categories['Low Disk Space']} devices have low disk space - may need cleanup")
    if readiness_rate >= 95:
        recommendations.append("✓ Excellent readiness - proceed with CR as planned")
    elif readiness_rate >= 80:
        recommendations.append("✓ Good readiness - address minor issues before CR window")

    # Build results
    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "totalDevices": total_devices,
            "groupId": scope_group_id,
        },
        "criteria": {
            "minCheckInHours": min_check_in_hours,
            "minDiskSpaceGB": min_disk_space_gb,
            "minBatteryPercent": min_battery_percent,
        },
        "readiness": {
            "ready": ready_count,
            "notReady": not_ready_count,
            "readinessRate": readiness_rate,
        },
        "issueBreakdown": issue_categories,
        "recommendations": recommendations,
        "devices": [
            {
                "id": check.computer_id,
                "name": check.computer_name,
                "serial": check.serial,
                "ready": check.ready,
                "issues": check.issues,
                "warnings": check.warnings,
                "lastCheckIn": check.last_check_in,
                "diskFreeGB": round(check.disk_free_gb, 1) if check.disk_free_gb else None,
                "diskFreePercent": round(check.disk_free_percent, 1) if check.disk_free_percent else None,
                "batteryPercent": check.battery_percent,
                "osVersion": check.os_version,
            }
            for check in readiness_checks
        ]
    }

    # Determine exit code
    exit_code = 0
    if readiness_rate < 50:
        exit_code = 2  # Critical - majority not ready
    elif readiness_rate < 80:
        exit_code = 1  # Warning - significant portion not ready

    return results, exit_code

"""
Business logic for device availability reporting during CR windows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .jamf_client import JamfClient
from .models import Computer, DeviceCheckIn
from .utils import parse_jamf_datetime


def analyze_device_availability(
    cr_start: str,
    cr_end: str,
    client: JamfClient,
    scope_group_id: Optional[int] = None,
    min_checkin_count: int = 1,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Dict, int]:
    """
    Analyze device availability during a CR window based on check-in patterns.

    Args:
        cr_start: ISO8601 timestamp marking CR window start
        cr_end: ISO8601 timestamp marking CR window end
        client: JamfClient for API calls
        scope_group_id: Optional group ID to limit scope
        min_checkin_count: Minimum check-ins required to be considered "available"
        logger: Optional logger instance

    Returns:
        Tuple of (results_dict, exit_code) where:
        - results_dict contains availability statistics and device lists
        - exit_code is always 0 (informational report)

    Example:
        >>> results, _ = analyze_device_availability(
        ...     "2024-11-18T00:00:00Z",
        ...     "2024-11-22T23:59:59Z",
        ...     client,
        ...     scope_group_id=123
        ... )
    """
    log = logger or logging.getLogger(__name__)

    # Parse CR window
    try:
        cr_start_dt = datetime.fromisoformat(cr_start.replace("Z", "+00:00"))
        if cr_start_dt.tzinfo is None:
            cr_start_dt = cr_start_dt.replace(tzinfo=timezone.utc)

        cr_end_dt = datetime.fromisoformat(cr_end.replace("Z", "+00:00"))
        if cr_end_dt.tzinfo is None:
            cr_end_dt = cr_end_dt.replace(tzinfo=timezone.utc)
    except Exception as exc:
        raise ValueError(f"Invalid CR window timestamps: {exc}") from exc

    window_duration_days = (cr_end_dt - cr_start_dt).days + 1

    # Fetch computers in scope
    log.info("Fetching computers in scope...")
    if scope_group_id:
        computers = client.get_computer_group_members(scope_group_id)
        computer_ids = [c.id for c in computers]
        computers = client.list_computers_inventory(ids=computer_ids)
    else:
        computers = client.list_computers_inventory()

    log.info("Analyzing %d computers", len(computers))

    # Categorize devices by availability (single bucket: online if any check-in within/after window)
    online_window = []
    offline_window = []

    for comp in computers:
        if not comp.last_check_in:
            # No check-in data at all
            offline_window.append({
                "computerId": comp.id,
                "name": comp.name,
                "serial": comp.serial,
                "lastCheckIn": None,
                "reason": "No check-in data available"
            })
            continue

        last_check_in_dt = parse_jamf_datetime(comp.last_check_in)
        if not last_check_in_dt:
            offline_window.append({
                "computerId": comp.id,
                "name": comp.name,
                "serial": comp.serial,
                "lastCheckIn": comp.last_check_in,
                "reason": "Unable to parse check-in timestamp"
            })
            continue

        device_info = {
            "computerId": comp.id,
            "name": comp.name,
            "serial": comp.serial,
            "lastCheckIn": comp.last_check_in,
            "osVersion": comp.os_version
        }

        # Online if checked-in any time within/after the window; otherwise offline before window
        if cr_start_dt <= last_check_in_dt <= cr_end_dt:
            online_window.append(device_info)
        elif last_check_in_dt > cr_end_dt:
            online_window.append(device_info)
        else:
            device_info["reason"] = f"Last check-in before CR window: {comp.last_check_in}"
            offline_window.append(device_info)

    # Calculate statistics
    total = len(computers)
    online_count = len(online_window)
    offline_count = len(offline_window)

    online_pct = (online_count / total * 100) if total > 0 else 0
    offline_pct = (offline_count / total * 100) if total > 0 else 0

    # Recommendations
    recommendations = []
    if offline_count > 0:
        recommendations.append(f"Follow up on {offline_count} devices that were offline during CR window")
    if online_count / total < 0.90:
        recommendations.append("Consider extending CR window or notifying users to power on devices")
    else:
        recommendations.append(f"Good device availability: {online_pct:.1f}% online during window")

    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "crWindow": {
            "start": cr_start,
            "end": cr_end,
            "durationDays": window_duration_days
        },
        "scope": {
            "totalDevices": total,
            "scopeGroupId": scope_group_id
        },
        "availability": {
            "onlineDuringWindow": {
                "count": online_count,
                "percentage": round(online_pct, 2),
                "devices": online_window
            },
            "offlineDuringWindow": {
                "count": offline_count,
                "percentage": round(offline_pct, 2),
                "devices": offline_window
            },
            # Legacy keys for compatibility
            "onlinePartialWindow": {
                "count": online_count,
                "percentage": round(online_pct, 2),
                "devices": online_window
            },
            "onlineEntireWindow": {
                "count": 0,
                "percentage": 0,
                "devices": []
            },
            "offlineEntireWindow": {
                "count": offline_count,
                "percentage": round(offline_pct, 2),
                "devices": offline_window
            },
        },
        "recommendations": recommendations
    }

    log.info(
        "Device availability: Online: %d (%.1f%%), Offline: %d (%.1f%%)",
        online_count, online_pct,
        offline_count, offline_pct
    )

    return results, 0  # Always exit 0 - this is an informational report

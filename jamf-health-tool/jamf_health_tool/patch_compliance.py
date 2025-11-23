"""
Business logic for patch compliance checking (OS and application versions).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .jamf_client import JamfClient
from .models import Application, Computer, PatchTarget
from .utils import parse_jamf_datetime


def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Parse a version string into a tuple of integers for comparison.

    Args:
        version_str: Version string like "14.7.1" or "131.0.6778.86"

    Returns:
        Tuple of integers representing version components

    Examples:
        >>> parse_version("14.7.1")
        (14, 7, 1)
        >>> parse_version("131.0.6778.86")
        (131, 0, 6778, 86)
    """
    # Remove any non-numeric prefix (like "v" in "v1.2.3")
    version_str = re.sub(r'^[^0-9]+', '', version_str)

    # Extract numeric components
    parts = re.findall(r'\d+', version_str)
    return tuple(int(p) for p in parts)


def version_meets_minimum(current: str, minimum: str) -> bool:
    """
    Check if current version meets minimum required version.

    Args:
        current: Current version string
        minimum: Minimum required version string

    Returns:
        True if current >= minimum

    Examples:
        >>> version_meets_minimum("14.7.1", "14.7.0")
        True
        >>> version_meets_minimum("14.6.1", "14.7.0")
        False
    """
    try:
        current_parts = parse_version(current)
        minimum_parts = parse_version(minimum)
        return current_parts >= minimum_parts
    except (ValueError, AttributeError):
        return False


def check_os_compliance(computers: List[Computer], target_versions: List[str]) -> Dict:
    """
    Check OS version compliance across computers.

    Only checks devices running the same major OS version as the targets.
    For example, if checking "14.7.1", only macOS 14.x devices are included.
    Devices running macOS 15.x are excluded from the scope.

    Args:
        computers: List of Computer objects with os_version populated
        target_versions: List of acceptable OS versions (e.g., ["14.7.1", "15.1"])

    Returns:
        Dict with compliance statistics and lists of compliant/non-compliant devices
    """
    compliant = []
    outdated = []
    unknown = []
    excluded = []  # Devices running different major versions

    # Extract major versions from targets
    target_major_versions = set()
    for target in target_versions:
        try:
            major = parse_version(target)[0]
            target_major_versions.add(major)
        except (IndexError, ValueError):
            pass
    if not target_major_versions:
        return {
            "total": 0,
            "compliant": 0,
            "outdated": 0,
            "unknown": len(computers),
            "excluded": 0,
            "complianceRate": 0,
            "compliantDevices": [],
            "outdatedDevices": [],
            "unknownDevices": [
                {
                    "computerId": c.id,
                    "name": c.name,
                    "serial": c.serial,
                    "osVersion": c.os_version,
                    "reason": "No valid target versions provided"
                }
                for c in computers
            ],
            "excludedDevices": [],
            "targetVersions": target_versions
        }

    for computer in computers:
        if not computer.os_version:
            unknown.append({
                "computerId": computer.id,
                "name": computer.name,
                "serial": computer.serial,
                "osVersion": None,
                "reason": "OS version not reported"
            })
            # Unknown OS does not affect compliance rate; skip to next device
            continue

        # Get major version of computer's OS
        try:
            computer_major = parse_version(computer.os_version)[0]
        except (IndexError, ValueError):
            unknown.append({
                "computerId": computer.id,
                "name": computer.name,
                "serial": computer.serial,
                "osVersion": computer.os_version,
                "reason": "Unable to parse OS version"
            })
            continue

        # Only check devices on same major version as targets
        if computer_major not in target_major_versions:
            excluded.append({
                "computerId": computer.id,
                "name": computer.name,
                "serial": computer.serial,
                "osVersion": computer.os_version,
                "reason": f"Running macOS {computer_major}.x (not checking this major version)"
            })
            continue

        # Find matching target for this major version
        matching_targets = [t for t in target_versions if parse_version(t)[0] == computer_major]

        # Check if current OS version meets any of the matching target versions
        is_compliant = any(
            version_meets_minimum(computer.os_version, target)
            for target in matching_targets
        )

        if is_compliant:
            compliant.append({
                "computerId": computer.id,
                "name": computer.name,
                "serial": computer.serial,
                "osVersion": computer.os_version
            })
        else:
            outdated.append({
                "computerId": computer.id,
                "name": computer.name,
                "serial": computer.serial,
                "osVersion": computer.os_version,
                "targetVersions": matching_targets
            })

    # Total only includes devices in-scope for the target major(s); unknown/excluded don't affect the rate
    total = len(compliant) + len(outdated)
    compliance_rate = (len(compliant) / total * 100) if total > 0 else 0

    return {
        "total": total,
        "compliant": len(compliant),
        "outdated": len(outdated),
        "unknown": len(unknown),
        "excluded": len(excluded),
        "complianceRate": round(compliance_rate, 2),
        "compliantDevices": compliant,
        "outdatedDevices": outdated,
        "unknownDevices": unknown,
        "excludedDevices": excluded,
        "targetVersions": target_versions
    }


def check_application_compliance(
    computer: Computer,
    target: PatchTarget,
    client: JamfClient
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if a specific application meets compliance requirements on a computer.

    Args:
        computer: Computer object
        target: PatchTarget with application requirements
        client: JamfClient to fetch application data if needed

    Returns:
        Tuple of (is_compliant, current_version, reason)
    """
    # Fetch applications for this computer if not already loaded
    if not computer.applications:
        computer.applications = client.get_computer_applications(computer.id)

    # Find the target application
    app_found = None
    target_lower = target.name.lower()
    for app in computer.applications:
        # Match by name (case-insensitive) or bundle ID
        name_match = app.name.lower() == target_lower or target_lower in app.name.lower()
        bundle_match = target.bundle_id and app.bundle_id == target.bundle_id

        if name_match or bundle_match:
            app_found = app
            break

    if not app_found:
        return False, None, f"Application '{target.name}' not installed"

    # Check version compliance
    if version_meets_minimum(app_found.version, target.min_version):
        return True, app_found.version, None
    else:
        return False, app_found.version, f"Version {app_found.version} < {target.min_version}"


def discover_application_from_inventory(
    app_name: str,
    computers: List[Computer],
    client: JamfClient,
    logger: Optional[logging.Logger] = None,
) -> Optional[Tuple[str, Optional[str]]]:
    """
    Discover an application and its latest version from device inventory.

    When no Patch Management entry exists, this function scans all devices
    to find the application and determine the most recent version installed.

    Args:
        app_name: Application name to search for (case-insensitive)
        computers: List of computers to scan
        client: JamfClient for API calls
        logger: Optional logger instance

    Returns:
        Tuple of (discovered_name, latest_version) if app found, None otherwise

    Example:
        >>> name, version = discover_application_from_inventory(
        ...     "Google Chrome", computers, client, logger
        ... )
        >>> print(f"Found: {name} version {version}")
        Found: Google Chrome version 131.0.6778.86
    """
    log = logger or logging.getLogger(__name__)

    app_name_lower = app_name.lower()
    version_counts: Dict[str, int] = {}
    discovered_name = None
    discovered_bundle_id = None

    log.info(f"Scanning {len(computers)} devices for '{app_name}'...")

    # Sample a subset of devices for faster discovery (max 100 devices)
    sample_size = min(100, len(computers))
    import random
    sample_computers = random.sample(computers, sample_size) if len(computers) > sample_size else computers

    devices_scanned = 0
    devices_with_app = 0

    for computer in sample_computers:
        try:
            # Fetch applications for this computer
            apps = client.get_computer_applications(computer.id)
            devices_scanned += 1

            # Find matching application
            for app in apps:
                name_match = app_name_lower in app.name.lower()

                if name_match:
                    if not discovered_name:
                        discovered_name = app.name
                        discovered_bundle_id = app.bundle_id
                        log.debug(f"Found app: {app.name} (bundle: {app.bundle_id})")

                    # Track version distribution
                    version = app.version or "unknown"
                    version_counts[version] = version_counts.get(version, 0) + 1
                    devices_with_app += 1
                    break

            # Early exit if we've found the app on enough devices
            if devices_with_app >= 20:
                log.debug(f"Found app on {devices_with_app} devices, stopping scan")
                break

        except Exception as exc:
            log.debug(f"Failed to get applications for computer {computer.id}: {exc}")
            continue

    if not discovered_name:
        log.warning(f"Application '{app_name}' not found on any of {devices_scanned} devices sampled")
        return None

    # Find the latest version
    valid_versions = [v for v in version_counts.keys() if v != "unknown"]
    if not valid_versions:
        log.warning(f"Found '{discovered_name}' but no valid versions detected")
        return None

    # Sort versions and pick the latest
    try:
        latest_version = max(valid_versions, key=parse_version)
    except (ValueError, TypeError):
        # Fallback to most common version if parsing fails
        latest_version = max(version_counts, key=version_counts.get)

    log.info(
        f"Discovered: '{discovered_name}' (latest version: {latest_version}) "
        f"found on {devices_with_app}/{devices_scanned} devices scanned"
    )
    log.debug(f"Version distribution: {version_counts}")

    return discovered_name, latest_version


def check_application_compliance_via_patch_report(
    online_computers: List[Computer],
    target: PatchTarget,
    client: JamfClient,
    logger: Optional[logging.Logger] = None,
) -> Optional[Tuple[List[Dict], List[Dict], List[Dict]]]:
    """
    Check application compliance using Patch Report endpoint (optimized).

    This method fetches all device versions in a single API call using the
    patch report endpoint, providing ~98% fewer API calls compared to
    querying each computer individually.

    Args:
        online_computers: List of computers to check
        target: PatchTarget with application requirements (must have patch_mgmt_id)
        client: JamfClient for API calls
        logger: Optional logger instance

    Returns:
        Tuple of (compliant_devices, non_compliant_devices, not_installed_devices)
        or None if patch report is unavailable

    Example:
        >>> compliant, non_compliant, not_installed = check_application_compliance_via_patch_report(
        ...     computers, target, client, logger
        ... )
    """
    log = logger or logging.getLogger(__name__)

    # Can only use patch report if we have a patch_mgmt_id
    if not target.patch_mgmt_id:
        log.debug("No patch_mgmt_id for %s, falling back to inventory method", target.name)
        return None

    try:
        # Fetch patch report (1 API call for ALL devices)
        log.debug("Fetching patch report for %s (ID: %d)", target.name, target.patch_mgmt_id)
        report = client.get_patch_report(target.patch_mgmt_id)

        # Build device version map from patch report
        device_versions = {}
        for device_status in report.get("deviceStatuses", []):
            try:
                device_id = int(device_status.get("deviceId", 0))
                installed_version = device_status.get("installedVersion")
                if device_id and installed_version:
                    device_versions[device_id] = installed_version
            except (ValueError, TypeError):
                continue

        log.debug("Patch report returned %d devices with %s", len(device_versions), target.name)

        # Check compliance for each computer in scope
        compliant = []
        non_compliant = []
        not_installed = []

        for computer in online_computers:
            device_info = {
                "computerId": computer.id,
                "name": computer.name,
                "serial": computer.serial,
            }

            if computer.id in device_versions:
                version = device_versions[computer.id]
                device_info["version"] = version

                if version_meets_minimum(version, target.min_version):
                    compliant.append(device_info)
                else:
                    device_info["reason"] = f"Version {version} < {target.min_version}"
                    non_compliant.append(device_info)
            else:
                # Device not in patch report = app not installed
                device_info["version"] = None
                device_info["reason"] = f"Application '{target.name}' not installed"
                not_installed.append(device_info)

        log.info(
            "Patch report method: %d compliant, %d non-compliant, %d not installed",
            len(compliant), len(non_compliant), len(not_installed)
        )

        return (compliant, non_compliant, not_installed)

    except Exception as exc:
        log.debug(
            "Failed to use patch report for %s (ID: %d): %s - falling back to inventory method",
            target.name, target.patch_mgmt_id, exc
        )
        return None


def evaluate_patch_compliance(
    patch_targets: List[PatchTarget],
    client: JamfClient,
    scope_group_id: Optional[int] = None,
    cr_start: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Dict, int]:
    """
    Evaluate patch compliance for OS and applications across scoped computers.

    Args:
        patch_targets: List of PatchTarget objects defining what to check
        client: JamfClient for API calls
        scope_group_id: Optional group ID to limit scope
        cr_start: Optional ISO8601 timestamp; devices offline since this time are flagged
        logger: Optional logger instance

    Returns:
        Tuple of (results_dict, exit_code) where:
        - results_dict contains compliance data for each target
        - exit_code is 0 if compliant, 1 if non-compliant

    Example:
        >>> targets = [
        ...     PatchTarget("macOS", "os", "14.7.1", critical=True),
        ...     PatchTarget("Google Chrome", "application", "131.0.0", critical=True)
        ... ]
        >>> results, exit_code = evaluate_patch_compliance(targets, client)
    """
    log = logger or logging.getLogger(__name__)

    # Parse CR start time if provided
    cr_start_dt = None
    if cr_start:
        try:
            cr_start_dt = datetime.fromisoformat(cr_start.replace("Z", "+00:00"))
            if cr_start_dt.tzinfo is None:
                cr_start_dt = cr_start_dt.replace(tzinfo=timezone.utc)
        except Exception as exc:
            raise ValueError(f"Invalid --cr-start value: {cr_start}") from exc

    # Fetch computers in scope
    log.info("Fetching computers in scope...")
    if scope_group_id:
        computers = client.get_computer_group_members(scope_group_id)
        # Refresh with inventory data to get OS versions
        computer_ids = [c.id for c in computers]
        computers = client.list_computers_inventory(ids=computer_ids)
    else:
        computers = client.list_computers_inventory()

    log.info("Found %d computers in scope", len(computers))

    # Debug: Show device OS versions
    if log.isEnabledFor(logging.DEBUG):
        for comp in computers[:5]:  # Show first 5 devices
            log.debug(
                "Device: %s (ID: %d) - OS Version: %s, Serial: %s",
                comp.name, comp.id, comp.os_version or "NONE", comp.serial or "NONE"
            )

    # Filter out offline devices if cr_start specified
    online_computers = []
    offline_computers = []

    if cr_start_dt:
        for comp in computers:
            if comp.last_check_in:
                last_check = parse_jamf_datetime(comp.last_check_in)
                if last_check and last_check >= cr_start_dt:
                    online_computers.append(comp)
                else:
                    offline_computers.append(comp)
            else:
                offline_computers.append(comp)
    else:
        online_computers = computers

    log.info("Online devices: %d, Offline devices: %d", len(online_computers), len(offline_computers))

    # Process each patch target
    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "totalDevices": len(computers),
            "onlineDevices": len(online_computers),
            "offlineDevices": len(offline_computers)
        },
        "targets": [],
        "offlineDevices": [
            {
                "computerId": comp.id,
                "name": comp.name,
                "serial": comp.serial,
                "lastCheckIn": comp.last_check_in
            }
            for comp in offline_computers
        ]
    }

    exit_code = 0

    for target in patch_targets:
        log.info("Checking compliance for %s (%s)...", target.name, target.target_type)

        if target.target_type == "os":
            # OS version compliance
            target_versions = [target.min_version]
            compliance_result = check_os_compliance(online_computers, target_versions)
            compliance_result["target"] = {
                "name": target.name,
                "type": "os",
                "minVersion": target.min_version,
                "critical": target.critical
            }

            # Set exit code if critical and we evaluated any devices for this major and not 100%
            if target.critical and compliance_result["total"] > 0 and compliance_result["complianceRate"] < 100:
                exit_code = 1

            results["targets"].append(compliance_result)

        elif target.target_type == "application":
            # Application compliance - try patch report method first (optimized)
            patch_report_result = check_application_compliance_via_patch_report(
                online_computers, target, client, log
            )

            if patch_report_result is not None:
                # Patch report method successful - use results directly
                compliant, non_compliant, not_installed = patch_report_result
                log.info("Used patch report method for %s (1 API call vs %d)", target.name, len(online_computers))
            else:
                # Patch report unavailable - fall back to inventory method
                log.info("Using inventory method for %s (%d API calls)", target.name, len(online_computers))
                compliant = []
                non_compliant = []
                not_installed = []

                for idx, comp in enumerate(online_computers, start=1):
                    if idx % 50 == 0:
                        log.info("Checked %d/%d computers for %s", idx, len(online_computers), target.name)

                    is_compliant, current_version, reason = check_application_compliance(comp, target, client)

                    # Debug: Show app check results
                    if idx <= 3:  # Show first 3 devices
                        log.debug(
                            "App check - Device: %s, App: %s, Version: %s, Compliant: %s, Reason: %s",
                            comp.name, target.name, current_version or "NOT FOUND", is_compliant, reason or "OK"
                        )

                    device_info = {
                        "computerId": comp.id,
                        "name": comp.name,
                        "serial": comp.serial,
                        "version": current_version
                    }

                    if is_compliant:
                        compliant.append(device_info)
                    else:
                        device_info["reason"] = reason
                        if reason and "not installed" in reason.lower():
                            not_installed.append(device_info)
                        else:
                            non_compliant.append(device_info)

            total = len(compliant) + len(non_compliant)  # only consider devices with the app present
            compliance_rate = (len(compliant) / total * 100) if total > 0 else 0

            app_result = {
                "target": {
                    "name": target.name,
                    "type": "application",
                    "minVersion": target.min_version,
                    "critical": target.critical,
                    "bundleId": target.bundle_id
                },
                "total": total,
                "compliant": len(compliant),
                "nonCompliant": len(non_compliant),
                "notInstalled": len(not_installed),
                "complianceRate": round(compliance_rate, 2),
                "compliantDevices": compliant,
                "nonCompliantDevices": non_compliant,
                "notInstalledDevices": not_installed,
            }

            # Set exit code if critical and not compliant
            if target.critical and total > 0 and compliance_rate < 100:
                exit_code = 1

            results["targets"].append(app_result)

    # Calculate overall compliance
    if results["targets"]:
        total_checks = sum(t.get("total", 0) for t in results["targets"])
        total_compliant = sum(t.get("compliant", 0) for t in results["targets"])
        overall_rate = (total_compliant / total_checks * 100) if total_checks > 0 else 0
        results["overallCompliance"] = round(overall_rate, 2)
    else:
        results["overallCompliance"] = 0

    return results, exit_code

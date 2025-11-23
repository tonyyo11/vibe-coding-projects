"""
Problem Devices Exception Tracking

Identifies devices that consistently fail across multiple CR windows.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .jamf_client import JamfClient


def analyze_problem_devices(
    client: JamfClient,
    cr_summary_files: List[Path],
    min_failures: int = 3,
    lookback_days: int = 90,
    logger: Optional[logging.Logger] = None,
) -> tuple[Dict[str, Any], int]:
    """
    Analyze problem devices from multiple CR summaries.

    Args:
        client: JamfClient instance
        cr_summary_files: List of CR summary JSON files to analyze
        min_failures: Minimum failures to be considered a problem device
        lookback_days: Only consider CRs within this many days
        logger: Optional logger

    Returns:
        Tuple of (results dict, exit code)
    """
    log = logger or logging.getLogger(__name__)

    # Load all CR summaries
    cr_summaries = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    for file_path in cr_summary_files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

                # Check if within lookback window
                cr_date_str = data.get('crWindow', {}).get('start')
                if cr_date_str:
                    try:
                        cr_date = datetime.fromisoformat(cr_date_str.replace('Z', '+00:00'))
                        if cr_date >= cutoff_date:
                            cr_summaries.append(data)
                            log.info(f"Loaded CR: {data.get('crName')} ({cr_date_str})")
                        else:
                            log.debug(f"Skipped CR {data.get('crName')} - outside lookback window")
                    except ValueError:
                        # Can't parse date, include anyway
                        cr_summaries.append(data)
                else:
                    # No date, include anyway
                    cr_summaries.append(data)

        except Exception as e:
            log.warning(f"Failed to load {file_path}: {e}")
            continue

    if not cr_summaries:
        raise ValueError("No valid CR summary files found")

    log.info(f"Analyzing {len(cr_summaries)} CR windows for problem devices")

    # Track failures by device
    device_failures: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
        'failures': [],
        'computerName': None,
        'serial': None,
    })

    # Extract failures from each CR
    for cr_data in cr_summaries:
        cr_name = cr_data.get('crName', 'Unknown')
        cr_date = cr_data.get('crWindow', {}).get('start', 'Unknown')

        # Policy failures
        policy_exec = cr_data.get('policyExecution', {})
        failed_devices = policy_exec.get('failedDevices', [])

        for device in failed_devices:
            computer_id = device.get('computerId')
            if computer_id:
                device_failures[computer_id]['failures'].append({
                    'crName': cr_name,
                    'crDate': cr_date,
                    'type': 'policy',
                    'policyId': device.get('policyId'),
                    'policyName': device.get('policyName'),
                    'error': device.get('error'),
                })
                device_failures[computer_id]['computerName'] = device.get('computerName')
                device_failures[computer_id]['serial'] = device.get('serial')

        # Patch compliance failures
        patch = cr_data.get('patchCompliance', {})
        for target_result in patch.get('targets', []):
            target_info = target_result.get('target', {})
            non_compliant_devices = target_result.get('nonCompliantDevices', [])

            for device in non_compliant_devices:
                computer_id = device.get('id')
                if computer_id:
                    device_failures[computer_id]['failures'].append({
                        'crName': cr_name,
                        'crDate': cr_date,
                        'type': 'patch',
                        'target': target_info.get('name'),
                        'targetVersion': target_info.get('minVersion'),
                        'currentVersion': device.get('version'),
                    })
                    device_failures[computer_id]['computerName'] = device.get('name')
                    device_failures[computer_id]['serial'] = device.get('serial')

    # Filter to problem devices (>= min_failures)
    problem_devices = []
    for computer_id, data in device_failures.items():
        failure_count = len(data['failures'])
        if failure_count >= min_failures:
            # Get current device details
            try:
                computers = client.list_computers_inventory(ids=[computer_id])
                if computers:
                    comp = computers[0]
                    last_check_in = comp.last_check_in
                    os_version = comp.os_version
                else:
                    last_check_in = None
                    os_version = None
            except Exception:
                last_check_in = None
                os_version = None

            # Categorize failure types
            failure_types = defaultdict(int)
            for failure in data['failures']:
                failure_types[failure['type']] += 1

            # Generate recommendations
            recommendations = _generate_device_recommendations(
                failure_count=failure_count,
                failure_types=dict(failure_types),
                last_check_in=last_check_in,
            )

            problem_devices.append({
                'computerId': computer_id,
                'computerName': data['computerName'],
                'serial': data['serial'],
                'failureCount': failure_count,
                'failureTypes': dict(failure_types),
                'failures': data['failures'],
                'lastCheckIn': last_check_in,
                'osVersion': os_version,
                'recommendations': recommendations,
            })

    # Sort by failure count (descending)
    problem_devices.sort(key=lambda x: x['failureCount'], reverse=True)

    # Generate overall recommendations
    overall_recommendations = _generate_overall_recommendations(
        problem_count=len(problem_devices),
        total_crs=len(cr_summaries),
    )

    # Build results
    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "analysisWindow": {
            "lookbackDays": lookback_days,
            "crsAnalyzed": len(cr_summaries),
        },
        "criteria": {
            "minFailures": min_failures,
        },
        "summary": {
            "totalProblemDevices": len(problem_devices),
            "topOffender": problem_devices[0] if problem_devices else None,
        },
        "problemDevices": problem_devices,
        "recommendations": overall_recommendations,
    }

    # Determine exit code
    exit_code = 0
    if len(problem_devices) > 10:
        exit_code = 1  # Warning - many problem devices
    if len(problem_devices) > 50:
        exit_code = 2  # Critical - very many problem devices

    return results, exit_code


def _generate_device_recommendations(
    failure_count: int,
    failure_types: Dict[str, int],
    last_check_in: Optional[str],
) -> List[str]:
    """Generate recommendations for a specific problem device."""
    recommendations = []

    if failure_count >= 10:
        recommendations.append("Critical: Consider removing from production fleet or reimaging")

    if failure_count >= 5:
        recommendations.append("High priority: Investigate hardware or configuration issues")

    if failure_types.get('policy', 0) > failure_types.get('patch', 0):
        recommendations.append("Policy execution issues - check network connectivity and MDM enrollment")

    if failure_types.get('patch', 0) > failure_types.get('policy', 0):
        recommendations.append("Patch compliance issues - check available disk space and update mechanisms")

    if last_check_in:
        try:
            check_in_date = datetime.fromisoformat(last_check_in.replace('Z', '+00:00'))
            hours_ago = (datetime.now(timezone.utc) - check_in_date).total_seconds() / 3600

            if hours_ago > 72:
                recommendations.append(f"Device offline for {hours_ago/24:.1f} days - may need physical intervention")
            elif hours_ago > 24:
                recommendations.append("Device not checking in regularly - verify network connectivity")
        except ValueError:
            pass

    if not recommendations:
        recommendations.append("Review device logs and contact user for troubleshooting")

    return recommendations


def _generate_overall_recommendations(
    problem_count: int,
    total_crs: int,
) -> List[str]:
    """Generate overall recommendations."""
    recommendations = []

    if problem_count == 0:
        recommendations.append("✓ No persistent problem devices found")
        recommendations.append("Current CR processes working well")
        return recommendations

    if problem_count > 50:
        recommendations.append("⚠️  Critical: Many problem devices detected")
        recommendations.append("Consider systematic review of deployment processes")

    elif problem_count > 10:
        recommendations.append("⚠️  Warning: Significant number of problem devices")
        recommendations.append("Review top offenders for common patterns")

    recommendations.append(f"Use auto-remediate with retry logic for {problem_count} problem devices")
    recommendations.append("Consider pre-CR readiness checks to catch issues early")
    recommendations.append("Use wake-devices and update-inventory before next CR")

    if total_crs >= 3:
        recommendations.append("Export problem device list to ticketing system for tracking")

    return recommendations

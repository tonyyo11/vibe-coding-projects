"""
Business logic for comprehensive Change Request summary reporting.

Combines policy execution, patch compliance, and device availability into a single CR validation report.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .device_availability import analyze_device_availability
from .jamf_client import JamfClient
from .models import PatchTarget
from .patch_compliance import evaluate_patch_compliance
from .policy_failures import evaluate_policy_failures


def generate_cr_summary(
    cr_name: str,
    cr_start: str,
    cr_end: str,
    policy_ids: List[int],
    patch_targets: List[PatchTarget],
    client: JamfClient,
    scope_group_id: Optional[int] = None,
    success_threshold: float = 0.95,
    filter_to_cr_window: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Dict, int]:
    """
    Generate a comprehensive Change Request summary report.

    This function combines:
    - Policy execution results (from policy_failures)
    - Patch compliance checking (from patch_compliance)
    - Device availability analysis (from device_availability)

    Args:
        cr_name: Human-readable name for the CR (e.g., "November 2024 Patching")
        cr_start: ISO8601 timestamp for CR window start
        cr_end: ISO8601 timestamp for CR window end
        policy_ids: List of policy IDs that were executed during CR
        patch_targets: List of PatchTarget objects to validate
        client: JamfClient for API calls
        scope_group_id: Optional group ID to limit scope
        success_threshold: Success rate required for CR to pass (default 0.95 = 95%)
        filter_to_cr_window: If True, only count policy executions within CR window (prevents >100% rates)
        logger: Optional logger instance

    Returns:
        Tuple of (results_dict, exit_code) where:
        - results_dict contains comprehensive CR validation data
        - exit_code is 0 if CR successful, 1 if needs attention

    Example:
        >>> targets = [PatchTarget("macOS", "os", "14.7.1", critical=True)]
        >>> results, code = generate_cr_summary(
        ...     "Nov 2024 Patching",
        ...     "2024-11-18T00:00:00Z",
        ...     "2024-11-22T23:59:59Z",
        ...     [100, 101],
        ...     targets,
        ...     client,
        ...     filter_to_cr_window=True
        ... )
    """
    log = logger or logging.getLogger(__name__)

    log.info("=" * 60)
    log.info("Generating CR Summary: %s", cr_name)
    log.info("=" * 60)

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

    window_duration = (cr_end_dt - cr_start_dt).days + 1

    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "crName": cr_name,
        "crWindow": {
            "start": cr_start,
            "end": cr_end,
            "durationDays": window_duration
        },
        "successThreshold": success_threshold
    }

    # 1. Device Availability Analysis
    log.info("Step 1/3: Analyzing device availability...")
    try:
        availability_results, _ = analyze_device_availability(
            cr_start=cr_start,
            cr_end=cr_end,
            client=client,
            scope_group_id=scope_group_id,
            logger=log
        )
        results["deviceAvailability"] = availability_results["availability"]
        results["scope"] = availability_results["scope"]
    except Exception as exc:
        log.error("Failed to analyze device availability: %s", exc)
        results["deviceAvailability"] = {"error": str(exc)}

    # 2. Policy Execution Results
    log.info("Step 2/3: Evaluating policy executions...")
    if policy_ids:
        try:
            policy_results, policy_exit_code = evaluate_policy_failures(
                policy_ids=policy_ids,
                client=client,
                limiting_group_id=scope_group_id,
                cr_start=cr_start,
                cr_end=cr_end,
                filter_to_cr_window=filter_to_cr_window,
                logger=log
            )

            # Summarize policy results
            total_devices_in_scope = 0
            total_completed = 0
            total_failed = 0
            total_pending = 0
            total_offline = 0

            policy_summary = []
            for policy_result in policy_results:
                total_devices_in_scope = max(total_devices_in_scope, policy_result["devicesInScope"])
                total_completed += policy_result["results"]["completed"]
                total_failed += policy_result["results"]["failed"]
                total_pending += policy_result["results"]["pending"]
                total_offline += policy_result["results"].get("offline", 0)

                policy_summary.append({
                    "policyId": policy_result["id"],
                    "policyName": policy_result["name"],
                    "enabled": policy_result["enabled"],
                    "devicesInScope": policy_result["devicesInScope"],
                    "completed": policy_result["results"]["completed"],
                    "failed": policy_result["results"]["failed"],
                    "pending": policy_result["results"]["pending"],
                    "offline": policy_result["results"].get("offline", 0)
                })

            results["policyExecution"] = {
                "summary": policy_summary,
                "totals": {
                    "devicesInScope": total_devices_in_scope,
                    "completed": total_completed,
                    "failed": total_failed,
                    "pending": total_pending,
                    "offline": total_offline
                },
                "failedDevices": [
                    device
                    for policy_result in policy_results
                    for device in policy_result.get("failedDevices", [])
                ]
            }
        except Exception as exc:
            log.error("Failed to evaluate policy executions: %s", exc)
            results["policyExecution"] = {"error": str(exc)}
    else:
        results["policyExecution"] = {"message": "No policies specified for evaluation"}

    # 3. Patch Compliance Checking
    log.info("Step 3/3: Checking patch compliance...")
    if patch_targets:
        try:
            compliance_results, compliance_exit_code = evaluate_patch_compliance(
                patch_targets=patch_targets,
                client=client,
                scope_group_id=scope_group_id,
                cr_start=cr_start,
                logger=log
            )

            results["patchCompliance"] = {
                "overallCompliance": compliance_results.get("overallCompliance", 0),
                "targets": compliance_results.get("targets", []),
                "scope": compliance_results.get("scope", {})
            }
        except Exception as exc:
            log.error("Failed to check patch compliance: %s", exc)
            results["patchCompliance"] = {"error": str(exc)}
    else:
        results["patchCompliance"] = {"message": "No patch targets specified for validation"}

    # 4. Calculate Overall CR Success
    log.info("Calculating overall CR success...")

    cr_success = True
    issues = []

    # Check policy execution success rate
    if "policyExecution" in results and "totals" in results["policyExecution"]:
        totals = results["policyExecution"]["totals"]
        if totals["devicesInScope"] > 0:
            policy_success_rate = (totals["completed"] / totals["devicesInScope"])
            if policy_success_rate < success_threshold:
                cr_success = False
                issues.append(f"Policy execution below threshold: {policy_success_rate*100:.1f}% < {success_threshold*100:.1f}%")

    # Check patch compliance
    if "patchCompliance" in results and "overallCompliance" in results["patchCompliance"]:
        compliance_rate = results["patchCompliance"]["overallCompliance"] / 100
        if compliance_rate < success_threshold:
            cr_success = False
            issues.append(f"Patch compliance below threshold: {compliance_rate*100:.1f}% < {success_threshold*100:.1f}%")

    # Check device availability
    if "deviceAvailability" in results and "offlineDuringWindow" in results["deviceAvailability"]:
        offline_pct = results["deviceAvailability"]["offlineDuringWindow"]["percentage"]
        if offline_pct > 10:  # More than 10% offline is concerning
            issues.append(f"High offline rate: {offline_pct:.1f}% of devices offline during CR window")

    results["crStatus"] = {
        "successful": cr_success,
        "issues": issues,
        "nextSteps": _generate_next_steps(results, issues)
    }

    # Determine exit code
    exit_code = 0 if cr_success else 1

    log.info("=" * 60)
    if cr_success:
        log.info("CR Status: ✓ SUCCESSFUL")
    else:
        log.info("CR Status: ✗ NEEDS ATTENTION")
        for issue in issues:
            log.info("  - %s", issue)
    log.info("=" * 60)

    return results, exit_code


def _generate_next_steps(results: Dict, issues: List[str]) -> List[str]:
    """
    Generate recommended next steps based on CR results.

    Args:
        results: CR summary results dictionary
        issues: List of issues identified

    Returns:
        List of recommended next steps
    """
    next_steps = []

    # Policy failures
    if "policyExecution" in results and "failedDevices" in results["policyExecution"]:
        failed_count = len(results["policyExecution"]["failedDevices"])
        if failed_count > 0:
            next_steps.append(f"Review {failed_count} devices with policy failures (see failedDevices in JSON)")

    # Patch compliance
    if "patchCompliance" in results and "targets" in results["patchCompliance"]:
        for target in results["patchCompliance"]["targets"]:
            if target.get("nonCompliant", 0) > 0 or target.get("outdated", 0) > 0:
                non_compliant = target.get("nonCompliant", target.get("outdated", 0))
                target_name = target.get("target", {}).get("name", "Unknown")
                next_steps.append(f"Address {non_compliant} devices non-compliant for {target_name}")

    # Offline devices
    if "deviceAvailability" in results:
        offline_count = results["deviceAvailability"].get("offlineDuringWindow", {}).get("count", 0)
        if offline_count > 0:
            next_steps.append(f"Follow up on {offline_count} devices offline during CR window")

    # General recommendations
    if not issues:
        next_steps.append("CR completed successfully - verify random sample of devices")
        next_steps.append("Document CR completion in change management system")
    else:
        next_steps.append("Generate detailed device lists from JSON output for follow-up")
        next_steps.append("Consider extending CR window if high failure rate persists")

    return next_steps

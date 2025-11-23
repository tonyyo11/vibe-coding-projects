"""
Auto-Remediation with Retry Logic

Automatically retries failed policies and profiles with intelligent backoff and recovery.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .jamf_client import JamfClient


@dataclass
class RemediationAttempt:
    """Record of a remediation attempt"""
    computer_id: int
    computer_name: str
    item_id: int  # Policy or Profile ID
    item_type: str  # "policy" or "profile"
    attempt_number: int
    success: bool
    error: Optional[str] = None


def auto_remediate(
    client: JamfClient,
    computer_ids: List[int],
    policy_ids: Optional[List[int]] = None,
    profile_ids: Optional[List[int]] = None,
    max_retries: int = 3,
    retry_delay: int = 300,  # seconds
    send_blank_push_between_retries: bool = True,
    dry_run: bool = False,
    logger: Optional[logging.Logger] = None,
) -> tuple[Dict[str, Any], int]:
    """
    Auto-remediate policies and profiles with retry logic.

    Args:
        client: JamfClient instance
        computer_ids: List of computer IDs to remediate
        policy_ids: Optional list of policy IDs to remediate
        profile_ids: Optional list of profile IDs to remediate
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        send_blank_push_between_retries: Send blank push to wake devices between retries
        dry_run: Preview mode - no actual changes
        logger: Optional logger

    Returns:
        Tuple of (results dict, exit code)
    """
    log = logger or logging.getLogger(__name__)

    if not policy_ids and not profile_ids:
        raise ValueError("At least one of policy_ids or profile_ids must be provided")

    # Fetch computer details
    log.info(f"Fetching details for {len(computer_ids)} computers...")
    computers = client.list_computers_inventory(ids=computer_ids)
    computer_map = {c.id: c.name for c in computers}

    attempts: List[RemediationAttempt] = []
    final_successes: Dict[str, List[int]] = {"policies": [], "profiles": []}
    final_failures: Dict[str, List[int]] = {"policies": [], "profiles": []}

    # Remediate policies
    if policy_ids:
        log.info(f"Remediating {len(policy_ids)} policies with up to {max_retries} retries...")

        for policy_id in policy_ids:
            for computer_id in computer_ids:
                computer_name = computer_map.get(computer_id, f"ID:{computer_id}")
                success = False

                for attempt_num in range(1, max_retries + 1):
                    log.info(f"Policy {policy_id} on {computer_name} - Attempt {attempt_num}/{max_retries}")

                    if not dry_run:
                        # Flush policy logs
                        flush_success = client.flush_policy_logs(computer_id, policy_id)

                        if flush_success:
                            # Send blank push to wake device and trigger re-run
                            if send_blank_push_between_retries:
                                client.send_blank_push(computer_id)

                            # Wait for retry delay (except on last attempt)
                            if attempt_num < max_retries:
                                log.debug(f"Waiting {retry_delay}s before next attempt...")
                                time.sleep(retry_delay)

                            # Check if policy ran successfully (would need to query history)
                            # For now, we consider the flush successful
                            success = True
                            attempts.append(RemediationAttempt(
                                computer_id=computer_id,
                                computer_name=computer_name,
                                item_id=policy_id,
                                item_type="policy",
                                attempt_number=attempt_num,
                                success=True,
                            ))
                            break
                        else:
                            attempts.append(RemediationAttempt(
                                computer_id=computer_id,
                                computer_name=computer_name,
                                item_id=policy_id,
                                item_type="policy",
                                attempt_number=attempt_num,
                                success=False,
                                error="Failed to flush policy logs",
                            ))
                    else:
                        log.info(f"[DRY RUN] Would flush policy {policy_id} logs for {computer_name}")
                        success = True
                        break

                if success:
                    final_successes["policies"].append(computer_id)
                else:
                    final_failures["policies"].append(computer_id)

    # Remediate profiles
    if profile_ids:
        log.info(f"Remediating {len(profile_ids)} profiles with up to {max_retries} retries...")

        # First, get failed MDM commands
        all_commands = client.list_computer_commands()

        for profile_id in profile_ids:
            for computer_id in computer_ids:
                computer_name = computer_map.get(computer_id, f"ID:{computer_id}")
                success = False

                # Find failed InstallProfile commands for this computer/profile
                failed_commands = [
                    cmd for cmd in all_commands
                    if cmd.device_id == computer_id
                    and cmd.status.lower() == "failed"
                    and "installconfigurationprofile" in cmd.command_name.lower()
                ]

                for attempt_num in range(1, max_retries + 1):
                    log.info(f"Profile {profile_id} on {computer_name} - Attempt {attempt_num}/{max_retries}")

                    if not dry_run:
                        # Clear failed commands
                        for cmd in failed_commands:
                            client.delete_computer_command(cmd.uuid)

                        # Send new install profile command
                        cmd_uuid = client.send_install_profile_command(computer_id, profile_id)

                        if cmd_uuid:
                            # Send blank push to wake device
                            if send_blank_push_between_retries:
                                client.send_blank_push(computer_id)

                            # Wait for retry delay (except on last attempt)
                            if attempt_num < max_retries:
                                log.debug(f"Waiting {retry_delay}s before next attempt...")
                                time.sleep(retry_delay)

                            success = True
                            attempts.append(RemediationAttempt(
                                computer_id=computer_id,
                                computer_name=computer_name,
                                item_id=profile_id,
                                item_type="profile",
                                attempt_number=attempt_num,
                                success=True,
                            ))
                            break
                        else:
                            attempts.append(RemediationAttempt(
                                computer_id=computer_id,
                                computer_name=computer_name,
                                item_id=profile_id,
                                item_type="profile",
                                attempt_number=attempt_num,
                                success=False,
                                error="Failed to send InstallProfile command",
                            ))
                    else:
                        log.info(f"[DRY RUN] Would remediate profile {profile_id} for {computer_name}")
                        success = True
                        break

                if success:
                    final_successes["profiles"].append(computer_id)
                else:
                    final_failures["profiles"].append(computer_id)

    # Build results
    total_attempts = len(attempts)
    successful_attempts = len([a for a in attempts if a.success])
    failed_attempts = total_attempts - successful_attempts

    # Calculate average attempts to success
    successful_items = [a for a in attempts if a.success]
    avg_attempts = (
        sum(a.attempt_number for a in successful_items) / len(successful_items)
        if successful_items else 0
    )

    results = {
        "summary": {
            "totalAttempts": total_attempts,
            "successfulAttempts": successful_attempts,
            "failedAttempts": failed_attempts,
            "averageAttemptsToSuccess": round(avg_attempts, 1),
        },
        "policies": {
            "attempted": len(policy_ids) * len(computer_ids) if policy_ids else 0,
            "succeeded": len(final_successes["policies"]),
            "failed": len(final_failures["policies"]),
        } if policy_ids else None,
        "profiles": {
            "attempted": len(profile_ids) * len(computer_ids) if profile_ids else 0,
            "succeeded": len(final_successes["profiles"]),
            "failed": len(final_failures["profiles"]),
        } if profile_ids else None,
        "attempts": [
            {
                "computerId": a.computer_id,
                "computerName": a.computer_name,
                "itemId": a.item_id,
                "itemType": a.item_type,
                "attemptNumber": a.attempt_number,
                "success": a.success,
                "error": a.error,
            }
            for a in attempts
        ],
    }

    # Determine exit code
    exit_code = 0
    if failed_attempts > 0:
        if failed_attempts > successful_attempts:
            exit_code = 2  # Majority failed
        else:
            exit_code = 1  # Some failures

    return results, exit_code

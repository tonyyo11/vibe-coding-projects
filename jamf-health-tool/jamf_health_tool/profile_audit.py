"""
Business logic for configuration profile scope auditing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .jamf_client import JamfClient
from .models import Computer, ConfigurationProfile, MdmCommand
from .utils import compile_safe_regex, parse_line_delimited_file, split_computer_identifiers, validate_profile_ids


def load_profile_ids(profile_ids: Iterable[int], profile_ids_file: Optional[str]) -> List[int]:
    """
    Load and validate profile IDs from CLI arguments and/or a file.

    Args:
        profile_ids: Profile IDs from CLI arguments
        profile_ids_file: Optional path to file with profile IDs (one per line)

    Returns:
        Validated list of profile IDs (deduplicated)

    Raises:
        ValueError: If any profile ID is invalid or file contains non-numeric data
        FileNotFoundError: If profile_ids_file is specified but doesn't exist

    Examples:
        >>> load_profile_ids([1, 2, 3], None)
        [1, 2, 3]

        >>> load_profile_ids([], "profiles.txt")  # File contains: 10\\n20\\n30
        [10, 20, 30]

    Note:
        - Empty lines and lines starting with '#' are ignored in files
        - Duplicate IDs are automatically removed
    """
    ids = list(profile_ids) if profile_ids else []

    if profile_ids_file:
        file_path = Path(profile_ids_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Profile IDs file not found: {profile_ids_file}")

        for line_num, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):  # Skip empty lines and comments
                continue
            try:
                pid = int(line)
                ids.append(pid)
            except ValueError as exc:
                raise ValueError(f"Invalid profile ID on line {line_num} in {profile_ids_file}: '{line}'") from exc

    # Validate all profile IDs (will raise if empty list or invalid IDs)
    if not ids:
        return []  # Return empty list if no IDs provided (will use defaults or no filtering)

    return validate_profile_ids(ids)


def _computer_matches_scope(profile: ConfigurationProfile, computer: Computer) -> bool:
    scope = profile.scope
    if computer.id in scope.excluded_computer_ids:
        return False
    if scope.excluded_group_ids and (
        scope.excluded_group_ids & computer.smart_groups or scope.excluded_group_ids & computer.static_groups
    ):
        return False
    included = False
    if scope.all_computers:
        included = True
    if scope.included_group_ids and (
        scope.included_group_ids & computer.smart_groups or scope.included_group_ids & computer.static_groups
    ):
        included = True
    if computer.id in scope.included_computer_ids:
        included = True
    return included


def _filter_profiles(
    profiles: List[ConfigurationProfile],
    limit_ids: Optional[List[int]],
    name_pattern: Optional[str],
) -> List[ConfigurationProfile]:
    """
    Filter configuration profiles by IDs and/or name pattern.

    Args:
        profiles: List of configuration profiles to filter
        limit_ids: Optional list of profile IDs to limit to
        name_pattern: Optional regex pattern to match profile names (case-insensitive)

    Returns:
        Filtered list of configuration profiles

    Raises:
        ValueError: If name_pattern is invalid regex or potentially dangerous

    Note:
        Uses safe regex compilation to prevent ReDoS attacks and validate patterns.
    """
    filtered = profiles
    if limit_ids:
        limit_set = set(limit_ids)
        filtered = [p for p in filtered if p.id in limit_set]
    if name_pattern:
        # Use safe regex compilation with validation
        regex = compile_safe_regex(name_pattern, re.IGNORECASE)
        filtered = [p for p in filtered if regex.search(p.name)]
    return filtered


def audit_profiles(
    computer_inputs: Iterable[str],
    client: JamfClient,
    *,
    limit_profile_ids: Optional[List[int]] = None,
    limit_profile_pattern: Optional[str] = None,
    correlate_failed_commands: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Dict], int]:
    """
    Audit configuration profile scope vs actual application for a set of computers.

    This function:
    1. Resolves computer identifiers (IDs, serials, names) to computer records
    2. Fetches all configuration profiles (optionally filtered)
    3. Compares expected profiles (based on scope) vs applied profiles
    4. Optionally correlates missing profiles with failed MDM commands

    Args:
        computer_inputs: Computer IDs, serial numbers, or hostnames as strings
        client: JamfClient instance for API calls
        limit_profile_ids: Optional list of profile IDs to limit audit to
        limit_profile_pattern: Optional regex pattern to filter profiles by name
        correlate_failed_commands: If True, check for failed MDM install commands
        logger: Optional logger instance

    Returns:
        Tuple of (results, exit_code) where:
        - results: List of dicts with computer info, missing/unexpected profiles
        - exit_code: 0 if no issues, 2 if missing profiles detected

    Raises:
        ValueError: If no matching computers found

    Example:
        >>> results, code = audit_profiles(["123", "ABC123456"], client, limit_profile_pattern="WiFi.*")
        >>> for result in results:
        ...     print(f"Computer: {result['computer']['name']}, Missing: {len(result['missingProfiles'])}")
    """
    log = logger or logging.getLogger(__name__)
    ids, serials, names = split_computer_identifiers(computer_inputs)
    computers = client.list_computers_inventory(ids=ids or None, serials=serials or None, names=names or None)
    inventory_by_id: Dict[int, Computer] = {c.id: c for c in computers}
    if not inventory_by_id:
        raise ValueError("No matching computers found for provided identifiers.")

    log.info("Fetching configuration profiles...")
    profiles = client.list_configuration_profiles()
    log.info("Found %d total configuration profiles", len(profiles))

    profiles = _filter_profiles(profiles, limit_profile_ids, limit_profile_pattern)
    log.info("After filtering: %d profiles to check", len(profiles))

    commands_by_device: Dict[int, List[MdmCommand]] = {}
    if correlate_failed_commands:
        for cmd in client.list_computer_commands():
            commands_by_device.setdefault(cmd.device_id, []).append(cmd)

    results = []
    exit_code = 0
    log.info("Auditing %d computers against %d profiles...", len(computers), len(profiles))
    for idx, comp in enumerate(computers, start=1):
        log.info("Checking computer %d/%d: %s (ID: %d)", idx, len(computers), comp.name, comp.id)
        mgmt = client.get_computer_management(comp.id)
        expected_profiles = set()
        for profile in profiles:
            if _computer_matches_scope(profile, mgmt):
                expected_profiles.add(profile.id)
        applied_profiles = mgmt.applied_profile_ids
        missing = expected_profiles - applied_profiles
        unexpected = applied_profiles - expected_profiles
        if missing:
            exit_code = 2
        missing_details = []
        for profile in profiles:
            if profile.id in missing:
                failed_commands = []
                for cmd in commands_by_device.get(comp.id, []):
                    if cmd.status.lower() == "failed" and "installconfigurationprofile" in cmd.command_name.lower():
                        if not profile.identifier or (profile.identifier and profile.identifier in (cmd.command_name or "")):
                            failed_commands.append(cmd.uuid)
                missing_details.append(
                    {
                        "id": profile.id,
                        "name": profile.name,
                        "identifier": profile.identifier,
                        "failedCommands": failed_commands,
                    }
                )
        unexpected_details = []
        for profile in profiles:
            if profile.id in unexpected:
                unexpected_details.append({"id": profile.id, "name": profile.name, "identifier": profile.identifier})
        results.append(
            {
                "computer": {
                    "id": mgmt.id,
                    "name": mgmt.name,
                    "serial": mgmt.serial,
                    "udid": mgmt.udid,
                    "smartGroups": sorted(mgmt.smart_groups),
                    "staticGroups": sorted(mgmt.static_groups),
                },
                "missingProfiles": missing_details,
                "unexpectedProfiles": unexpected_details,
            }
        )
        log.info(
            "Audited %s (missing=%s unexpected=%s)", mgmt.name, len(missing_details), len(unexpected_details)
        )

    return results, exit_code

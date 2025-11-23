"""
Typer CLI entrypoint for Jamf Health Tool.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from tabulate import tabulate

from .auto_remediate import auto_remediate
from .config import Config, ConfigError, load_config
from .cr_compare import compare_cr_results
from .cr_readiness import analyze_cr_readiness
from .cr_summary import generate_cr_summary
from .device_availability import analyze_device_availability
from .jamf_client import DataModelError, JamfApiError, JamfCliError, JamfClient
from .logging_utils import setup_logging
from .mdm_failures import mdm_failures_report
from .models import PatchTarget
from .patch_compliance import evaluate_patch_compliance
from .policy_failures import evaluate_policy_failures, load_policy_ids
from .problem_devices import analyze_problem_devices
from .profile_audit import audit_profiles, load_profile_ids
from .report_generation import generate_excel_report, generate_html_report, generate_pdf_report
from .teams_webhook import post_teams_summary
from .utils import parse_flexible_date, parse_line_delimited_file, validate_date_range
from .workflows import execute_workflow, validate_workflow_file

app = typer.Typer(add_completion=False, help="Jamf health checks for policies, profiles, and MDM commands.")


@dataclass
class CliState:
    logger: Any
    config: Config
    output_json: Optional[Path]
    output_xlsx: Optional[Path]
    output_pdf: Optional[Path]
    output_html: Optional[Path]
    teams_webhook_url: Optional[str]


def _write_json(path: Path, data: Dict[str, Any], logger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Wrote JSON output to %s", path)


def _resolve_base_url(ctx: typer.Context, state: CliState) -> Optional[str]:
    """
    Resolve base URL preference for direct HTTP mode.
    """
    # Prefer CLI flag, then config.tenant_url, then environment variable
    return ctx.meta.get("base_url") or state.config.tenant_url or os.environ.get("JAMF_BASE_URL")


def _build_client(ctx: typer.Context, state: CliState) -> JamfClient:
    """
    Build a JamfClient enforcing direct-HTTP-as-default and surfacing a clear error
    when JAMF_BASE_URL is missing.
    """
    use_apiutil = bool(ctx.meta.get("use_apiutil"))
    base_url = _resolve_base_url(ctx, state)

    if not use_apiutil and not base_url:
        typer.echo(
            "Direct HTTP mode is default. Set JAMF_BASE_URL (or use --base-url or config tenant_url) "
            "so the tool can contact Jamf over HTTPS. To intentionally use Jamf API Utility, pass --use-apiutil.",
            err=True,
        )
        raise typer.Exit(code=2)

    # Create cache instance based on config and CLI options
    cache_enabled = state.config.cache_enabled and not ctx.meta.get("no_cache", False)
    cache_ttl = ctx.meta.get("cache_ttl") or state.config.cache_ttl
    cache_dir = state.config.cache_dir

    from .cache import FileCache
    cache = FileCache(
        cache_dir=cache_dir,
        default_ttl=cache_ttl,
        enabled=cache_enabled,
        logger=state.logger,
    ) if cache_enabled else None

    if cache:
        state.logger.debug(f"Cache enabled (TTL: {cache_ttl}s, dir: {cache.cache_dir})")
    else:
        state.logger.debug("Cache disabled")

    # Concurrency settings
    concurrency_enabled = state.config.concurrency_enabled and not ctx.meta.get("no_concurrency", False)
    max_workers = ctx.meta.get("max_workers") or state.config.max_workers

    if concurrency_enabled:
        state.logger.debug(f"Concurrency enabled (max workers: {max_workers})")
    else:
        state.logger.debug("Concurrency disabled")

    return JamfClient(
        target=state.config.target,
        logger=state.logger,
        use_apiutil=use_apiutil,
        base_url=base_url,
        verify_ssl=ctx.meta.get("verify_ssl", True),
        ssl_cert_path=ctx.meta.get("ssl_cert_path"),
        debug_api=ctx.meta.get("debug_api", False),
        cache=cache,
        concurrency_enabled=concurrency_enabled,
        max_workers=max_workers,
    )


@app.callback()
def main(
    ctx: typer.Context,
    target: Optional[str] = typer.Option(None, help="Jamf API Utility target name."),
    config_file: Optional[Path] = typer.Option(None, help="Optional config file to load defaults."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose debug logging."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Reduce log verbosity."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", help="Write command output to JSON file."),
    output_xlsx: Optional[Path] = typer.Option(None, "--output-xlsx", help="Write command output to Excel (.xlsx) file."),
    output_pdf: Optional[Path] = typer.Option(None, "--output-pdf", help="Write command output to PDF file."),
    output_html: Optional[Path] = typer.Option(None, "--output-html", help="Write command output to HTML file."),
    teams_webhook_url: Optional[str] = typer.Option(None, help="Teams webhook URL for summary notification."),
    use_apiutil: bool = typer.Option(False, "--use-apiutil", help="Use Jamf API Utility (apiutil) instead of direct HTTP API calls."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Jamf base URL (https://tenant.jamfcloud.com or on-prem URL) for direct HTTP mode (default)."),
    no_verify_ssl: bool = typer.Option(False, "--no-verify-ssl", help="Disable SSL certificate verification (INSECURE - only for testing)."),
    ssl_cert_path: Optional[Path] = typer.Option(None, "--ssl-cert-path", help="Path to SSL certificate file for verification."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable API response caching (forces fresh data)."),
    cache_ttl: Optional[int] = typer.Option(None, "--cache-ttl", help="Cache time-to-live in seconds (default: 3600 = 1 hour)."),
    no_concurrency: bool = typer.Option(False, "--no-concurrency", help="Disable concurrent API calls (run sequentially)."),
    max_workers: Optional[int] = typer.Option(None, "--max-workers", help="Maximum concurrent API workers (default: 10)."),
):
    """
    Configure global options and shared context.
    """
    logger = setup_logging(verbose=verbose, quiet=quiet, logger_name="jamf-health-tool")
    try:
        config = load_config(cli_target=target, config_file=str(config_file) if config_file else None)
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}", err=True)
        raise typer.Exit(code=2)

    # Security warnings
    if no_verify_ssl:
        logger.warning("⚠️  SSL certificate verification is DISABLED - connection is not secure!")
        typer.echo("⚠️  WARNING: SSL certificate verification disabled. Use only in testing environments.", err=True)

    # Warn about credential exposure via environment variables
    import os
    if os.environ.get("JAMF_PASSWORD"):
        logger.warning(
            "⚠️  JAMF_PASSWORD detected in environment. Credentials in environment variables are visible to other processes."
        )
        typer.echo(
            "⚠️  WARNING: Using JAMF_PASSWORD environment variable. Consider using JAMF_BEARER_TOKEN or client credentials instead.",
            err=True
        )

    # Store the use_apiutil/base_url/SSL/cache/concurrency flags on the context for JamfClient construction.
    ctx.meta["use_apiutil"] = use_apiutil
    ctx.meta["base_url"] = base_url
    ctx.meta["verify_ssl"] = not no_verify_ssl
    ctx.meta["ssl_cert_path"] = str(ssl_cert_path) if ssl_cert_path else None
    ctx.meta["debug_api"] = verbose  # Enable API debugging in verbose mode
    ctx.meta["no_cache"] = no_cache
    ctx.meta["cache_ttl"] = cache_ttl
    ctx.meta["no_concurrency"] = no_concurrency
    ctx.meta["max_workers"] = max_workers
    ctx.obj = CliState(
        logger=logger,
        config=config,
        output_json=output_json,
        output_xlsx=output_xlsx,
        output_pdf=output_pdf,
        output_html=output_html,
        teams_webhook_url=teams_webhook_url
    )


def _print_policy_table(results):
    table = []
    for item in results:
        table.append(
            [
                item["id"],
                item["name"],
                "Y" if item["enabled"] else "N",
                item["devicesInScope"],
                item["results"]["completed"],
                item["results"]["failed"],
                item["results"]["pending"],
                item["results"].get("offline", 0),
            ]
        )
    headers = ["Policy ID", "Policy Name", "Enabled", "Devices in Scope", "Completed", "Failed", "Pending", "Offline"]
    typer.echo(tabulate(table, headers=headers, tablefmt="github"))


@app.command("policy-failures")
def policy_failures_cmd(
    ctx: typer.Context,
    policy_id: List[int] = typer.Option(None, "--policy-id", help="Policy ID to inspect.", show_default=False),
    policy_ids_file: Optional[Path] = typer.Option(None, help="File with policy IDs, one per line."),
    limiting_group_id: Optional[int] = typer.Option(None, help="Limit 'all computers' scope to a specific group."),
    cr_start: Optional[str] = typer.Option(None, help="CR start time (flexible date format: 2024-11-22 or 11-22-2024 or ISO8601); classify devices offline since this time."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Detect failed executions for given policies across scoped computers.

    Date formats accepted: 2024-11-22, 11-22-2024, 11/22/2024, or ISO8601 (2024-11-22T00:00:00Z)
    """
    state: CliState = ctx.obj
    logger = state.logger
    try:
        # Parse flexible date format if provided
        cr_start_parsed = None
        if cr_start:
            try:
                cr_start_parsed = parse_flexible_date(cr_start, end_of_day=False)
                logger.debug(f"Parsed CR start: {cr_start_parsed}")
            except ValueError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(code=2)

        ids = load_policy_ids(policy_id or [], str(policy_ids_file) if policy_ids_file else None)
        if not ids:
            raise typer.Exit(code=2)
        client = _build_client(ctx, state)
        results, exit_code = evaluate_policy_failures(
            ids, client, limiting_group_id or state.config.limiting_group_id, cr_start=cr_start_parsed, logger=logger
        )
        _print_policy_table(results)
        json_payload = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "tenant": state.config.tenant_url,
            "policies": results,
        }
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, json_payload, logger)
        if state.teams_webhook_url:
            total_failed = sum(item["results"]["failed"] for item in results)
            post_teams_summary(
                state.teams_webhook_url,
                title="Jamf policy failures",
                summary=f"{total_failed} failed executions across {len(results)} policies",
                data={"failed": total_failed, "policies": len(results)},
                logger=logger,
            )
        raise typer.Exit(code=exit_code)
    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("Policy failure check error: %s", exc)
        raise typer.Exit(code=3)


def _collect_computer_inputs(
    computer_ids: List[int],
    serials: List[str],
    computer_list: Optional[Path],
) -> List[str]:
    inputs: List[str] = []
    inputs.extend([str(cid) for cid in computer_ids])
    inputs.extend(serials)
    if computer_list:
        inputs.extend(parse_line_delimited_file(str(computer_list)))
    return inputs


def _print_profile_results(results):
    rows = []
    for item in results:
        comp = item["computer"]
        rows.append(
            [
                comp["id"],
                comp["name"],
                comp.get("serial"),
                len(item["missingProfiles"]),
                len(item["unexpectedProfiles"]),
            ]
        )
    headers = ["Computer ID", "Name", "Serial", "Missing Profiles", "Unexpected Profiles"]
    typer.echo(tabulate(rows, headers=headers, tablefmt="github"))


@app.command("profile-scope-audit")
def profile_scope_audit_cmd(
    ctx: typer.Context,
    computer_id: List[int] = typer.Option(None, "--computer-id", help="Computer ID to audit.", show_default=False),
    serial: List[str] = typer.Option(None, "--serial", help="Computer serial to audit.", show_default=False),
    computer_list: Optional[Path] = typer.Option(None, "--computer-list", help="File containing computer IDs/serials/hostnames."),
    limit_to_profile_id: List[int] = typer.Option(None, "--limit-to-profile-id", help="Restrict to specific profile IDs (repeatable)."),
    limit_to_profile_ids_file: Optional[Path] = typer.Option(None, "--limit-to-profile-ids-file", help="File with profile IDs, one per line."),
    limit_to_profile_name_pattern: Optional[str] = typer.Option(None, "--limit-to-profile-name-pattern", help="Regex to filter profiles by name (e.g., 'WiFi.*' or '^Security'). Validated for safety."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Audit expected vs applied configuration profiles for a set of computers.

    Profile filtering options:
    - By ID: Use --limit-to-profile-id (repeatable) or --limit-to-profile-ids-file
    - By name: Use --limit-to-profile-name-pattern with regex (case-insensitive)

    Safety features:
    - Regex patterns are validated before use
    - Potentially dangerous patterns (e.g., nested quantifiers) are rejected
    - Profile IDs are validated and deduplicated

    Examples:
        # Audit specific profiles by ID
        jamf-health-tool profile-scope-audit --computer-id 123 --limit-to-profile-id 10 --limit-to-profile-id 20

        # Audit profiles matching a pattern
        jamf-health-tool profile-scope-audit --computer-list computers.txt --limit-to-profile-name-pattern "WiFi.*"

        # Use file for profile IDs
        jamf-health-tool profile-scope-audit --serial ABC123 --limit-to-profile-ids-file profiles.txt
    """
    state: CliState = ctx.obj
    logger = state.logger
    try:
        # Load and validate profile IDs from CLI and/or file
        try:
            profile_ids = load_profile_ids(
                limit_to_profile_id or [],
                str(limit_to_profile_ids_file) if limit_to_profile_ids_file else None
            )
            # Fall back to config defaults if no IDs provided
            if not profile_ids:
                profile_ids = state.config.default_profile_ids or []
            if profile_ids:
                logger.info(f"Limiting audit to {len(profile_ids)} profile IDs")
        except (ValueError, FileNotFoundError) as e:
            typer.echo(f"Error loading profile IDs: {e}", err=True)
            raise typer.Exit(code=2)

        # Validate regex pattern if provided
        if limit_to_profile_name_pattern:
            try:
                # Pre-validate the regex pattern to provide better error messages
                from .utils import compile_safe_regex
                compile_safe_regex(limit_to_profile_name_pattern, re.IGNORECASE)
                logger.info(f"Using profile name pattern: {limit_to_profile_name_pattern}")
            except ValueError as e:
                typer.echo(f"Error in profile name pattern: {e}", err=True)
                raise typer.Exit(code=2)

        inputs = _collect_computer_inputs(computer_id or [], serial or [], computer_list)
        client = _build_client(ctx, state)
        results, exit_code = audit_profiles(
            inputs,
            client,
            limit_profile_ids=profile_ids if profile_ids else None,
            limit_profile_pattern=limit_to_profile_name_pattern,
            correlate_failed_commands=True,
            logger=logger,
        )
        _print_profile_results(results)
        payload = {"generatedAt": datetime.now(timezone.utc).isoformat(), "results": results}
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, payload, logger)
        if state.teams_webhook_url:
            missing_count = sum(len(r["missingProfiles"]) for r in results)
            post_teams_summary(
                state.teams_webhook_url,
                title="Jamf profile audit",
                summary=f"{missing_count} missing profiles detected",
                data={"computers": len(results), "missingProfiles": missing_count},
                logger=logger,
            )
        raise typer.Exit(code=exit_code)
    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("Profile audit error: %s", exc)
        raise typer.Exit(code=3)


@app.command("remediate-profiles")
def remediate_profiles_cmd(
    ctx: typer.Context,
    profile_id: List[int] = typer.Option(..., "--profile-id", help="Profile ID(s) to remediate (repeatable)."),
    computer_id: List[int] = typer.Option(None, "--computer-id", help="Computer ID(s) to remediate (repeatable)."),
    computer_list: Optional[Path] = typer.Option(None, "--computer-list", help="File containing computer IDs/serials/hostnames."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes."),
    clear_failed_commands: bool = typer.Option(True, help="Clear failed MDM commands before repushing (default: True)."),
    send_blank_push: bool = typer.Option(False, help="Send blank push after installing profiles to wake devices."),
):
    """
    Remediate failed profile installations by clearing failed MDM commands and repushing profiles.

    This command:
    1. Finds devices with failed profile installation commands
    2. Clears the failed MDM commands (optional)
    3. Sends new InstallProfile commands
    4. Optionally sends a blank push to wake devices

    Safety features:
    - Dry-run mode to preview actions
    - Requires explicit profile IDs to prevent accidental mass changes
    - Logs all actions for audit trail

    Examples:
        # Preview remediation for a profile across specific computers
        jamf-health-tool remediate-profiles --profile-id 10 --computer-id 123 --computer-id 456 --dry-run

        # Remediate profile 10 and 20 on all computers in a list
        jamf-health-tool remediate-profiles --profile-id 10 --profile-id 20 --computer-list computers.txt

        # Remediate and send blank push to wake devices
        jamf-health-tool remediate-profiles --profile-id 15 --computer-id 789 --send-blank-push
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Validate inputs
        if not profile_id:
            typer.echo("Error: At least one --profile-id is required", err=True)
            raise typer.Exit(code=2)

        # Collect computer inputs
        inputs = _collect_computer_inputs(computer_id or [], [], computer_list)
        if not inputs:
            typer.echo("Error: At least one computer must be specified", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        # Resolve computer IDs from inputs
        from .utils import split_computer_identifiers
        ids, serials, names = split_computer_identifiers(inputs)
        computers = client.list_computers_inventory(ids=ids or None, serials=serials or None, names=names or None)

        if not computers:
            typer.echo("Error: No matching computers found", err=True)
            raise typer.Exit(code=2)

        computer_ids = [c.id for c in computers]
        logger.info(f"Targeting {len(computer_ids)} computers for remediation")

        # Get all MDM commands to find failed profile installations
        logger.info("Fetching MDM commands...")
        all_commands = client.list_computer_commands()

        # Filter for failed InstallProfile commands on target computers and profiles
        failed_commands_by_computer: Dict[int, List[str]] = {}

        for cmd in all_commands:
            if (cmd.device_id in computer_ids and
                cmd.status.lower() == "failed" and
                "installconfigurationprofile" in cmd.command_name.lower()):

                # Check if this is one of our target profiles
                # The command name may contain the profile identifier
                for pid in profile_id:
                    # This is a best-effort match; some commands may not have clear profile ID
                    failed_commands_by_computer.setdefault(cmd.device_id, []).append(cmd.uuid)
                    break  # Only add each command once

        logger.info(f"Found {sum(len(v) for v in failed_commands_by_computer.values())} failed commands across {len(failed_commands_by_computer)} devices")

        # Show summary
        typer.echo("\n" + "=" * 70)
        typer.echo("Profile Remediation Plan")
        typer.echo("=" * 70)
        typer.echo(f"Profiles to install: {', '.join(str(p) for p in profile_id)}")
        typer.echo(f"Target computers: {len(computer_ids)}")
        typer.echo(f"Computers with failed commands: {len(failed_commands_by_computer)}")
        typer.echo(f"Total failed commands to clear: {sum(len(v) for v in failed_commands_by_computer.values())}")
        typer.echo(f"Clear failed commands: {'Yes' if clear_failed_commands else 'No'}")
        typer.echo(f"Send blank push: {'Yes' if send_blank_push else 'No'}")

        if dry_run:
            typer.echo("\n⚠️  DRY RUN MODE - No changes will be made\n")

        typer.echo()

        # Execute remediation
        cleared_count = 0
        installed_count = 0
        blank_push_count = 0
        errors = []

        for comp_id in computer_ids:
            comp_name = next((c.name for c in computers if c.id == comp_id), f"ID:{comp_id}")

            # Clear failed commands if requested
            if clear_failed_commands and comp_id in failed_commands_by_computer:
                for cmd_uuid in failed_commands_by_computer[comp_id]:
                    if not dry_run:
                        if client.delete_computer_command(cmd_uuid):
                            cleared_count += 1
                            logger.debug(f"Cleared command {cmd_uuid} for {comp_name}")
                        else:
                            errors.append(f"Failed to clear command {cmd_uuid} for {comp_name}")
                    else:
                        logger.info(f"[DRY RUN] Would clear command {cmd_uuid} for {comp_name}")
                        cleared_count += 1

            # Install profiles
            for pid in profile_id:
                if not dry_run:
                    uuid = client.send_install_profile_command(comp_id, pid)
                    if uuid:
                        installed_count += 1
                        logger.info(f"✓ Sent InstallProfile for profile {pid} to {comp_name} (UUID: {uuid})")
                    else:
                        errors.append(f"Failed to send InstallProfile for profile {pid} to {comp_name}")
                else:
                    logger.info(f"[DRY RUN] Would send InstallProfile for profile {pid} to {comp_name}")
                    installed_count += 1

            # Send blank push if requested
            if send_blank_push:
                if not dry_run:
                    uuid = client.send_blank_push(comp_id)
                    if uuid:
                        blank_push_count += 1
                        logger.debug(f"Sent BlankPush to {comp_name} (UUID: {uuid})")
                    else:
                        errors.append(f"Failed to send BlankPush to {comp_name}")
                else:
                    logger.info(f"[DRY RUN] Would send BlankPush to {comp_name}")
                    blank_push_count += 1

        # Show results
        typer.echo("\n" + "=" * 70)
        typer.echo("Remediation Results")
        typer.echo("=" * 70)
        typer.echo(f"Failed commands cleared: {cleared_count}")
        typer.echo(f"Profile install commands sent: {installed_count}")
        if send_blank_push:
            typer.echo(f"Blank pushes sent: {blank_push_count}")
        if errors:
            typer.echo(f"\n⚠️  Errors encountered: {len(errors)}")
            for error in errors[:10]:  # Show first 10 errors
                typer.echo(f"  - {error}")
            if len(errors) > 10:
                typer.echo(f"  ... and {len(errors) - 10} more errors (check logs)")

        if dry_run:
            typer.echo("\n✓ Dry run completed - no actual changes were made")
        else:
            typer.echo("\n✓ Remediation completed")

        exit_code = 0 if not errors else 1
        raise typer.Exit(code=exit_code)

    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("Profile remediation error: %s", exc)
        raise typer.Exit(code=3)


def _print_mdm_results(results: Dict[str, Any]):
    summary_rows = [[cmd, count] for cmd, count in results.get("summary", {}).items()]
    if summary_rows:
        typer.echo("Summary by command type:")
        typer.echo(tabulate(summary_rows, headers=["Command", "Failed Count"], tablefmt="github"))
    if results.get("failures"):
        typer.echo("\nFailures by device:")
        device_rows = []
        for entry in results["failures"]:
            device_rows.append([entry["deviceId"], entry["count"]])
        typer.echo(tabulate(device_rows, headers=["Device ID", "Failed Commands"], tablefmt="github"))


@app.command("mdm-failures-report")
def mdm_failures_cmd(
    ctx: typer.Context,
    scope: str = typer.Option("global", help="Scope: global, computer-id, serial, or list"),
    computer_id: Optional[int] = typer.Option(None, help="Computer ID when scope=computer-id"),
    serial: Optional[str] = typer.Option(None, help="Serial when scope=serial"),
    list_path: Optional[Path] = typer.Option(None, help="File with device IDs/serials when scope=list"),
    since: Optional[str] = typer.Option(None, help="Date (flexible format: 2024-11-22 or 11-22-2024 or ISO8601) or relative time (24h, 7d)."),
    only_command_types: List[str] = typer.Option(None, help="Restrict to command types (repeatable)."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Report failed MDM commands globally or for specific devices.

    Date formats accepted: 2024-11-22, 11-22-2024, 11/22/2024, ISO8601 (2024-11-22T00:00:00Z), or relative (24h, 7d)
    """
    state: CliState = ctx.obj
    logger = state.logger
    try:
        # Parse flexible date format if provided (but preserve relative time formats like "24h", "7d")
        since_parsed = None
        if since:
            # Check if it's a relative time format (e.g., "24h", "7d", "30m")
            if re.match(r'^\d+[hdmHDM]$', since):
                # It's a relative time - pass through unchanged
                since_parsed = since
                logger.debug(f"Using relative time format: {since}")
            else:
                # Try to parse as a flexible date
                try:
                    since_parsed = parse_flexible_date(since, end_of_day=False)
                    logger.debug(f"Parsed since date: {since_parsed}")
                except ValueError as e:
                    typer.echo(f"Error: {e}", err=True)
                    raise typer.Exit(code=2)

        if scope == "computer-id" and computer_id is None:
            raise typer.BadParameter("--computer-id required when scope=computer-id")
        if scope == "serial" and not serial:
            raise typer.BadParameter("--serial required when scope=serial")
        if scope == "list" and not list_path:
            raise typer.BadParameter("--list-path required when scope=list")
        scope_values = []
        if scope == "computer-id" and computer_id is not None:
            scope_values = [str(computer_id)]
        elif scope == "serial" and serial:
            scope_values = [serial]
        elif scope == "list" and list_path:
            scope_values = parse_line_delimited_file(str(list_path))
        client = _build_client(ctx, state)
        results, exit_code = mdm_failures_report(
            scope,
            scope_values,
            client,
            since=since_parsed,
            command_types=only_command_types or None,
            logger=logger,
        )
        _print_mdm_results(results)
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)
        if state.teams_webhook_url:
            total = sum(results.get("summary", {}).values())
            post_teams_summary(
                state.teams_webhook_url,
                title="Jamf MDM failures",
                summary=f"{total} failed MDM commands",
                data={"failed": total},
                logger=logger,
            )
        raise typer.Exit(code=exit_code)
    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("MDM failures report error: %s", exc)
        raise typer.Exit(code=3)


@app.command("patch-compliance")
def patch_compliance_cmd(
    ctx: typer.Context,
    os_version: List[str] = typer.Option(None, "--os-version", help="Target macOS versions (e.g., '14.7.1,15.1')"),
    app_name: List[str] = typer.Option(None, "--app", help="Application name:min_version OR just name to auto-fetch (e.g., 'Google Chrome:131.0' or 'Google Chrome')"),
    limiting_group_id: Optional[int] = typer.Option(None, help="Limit to a specific group."),
    cr_start: Optional[str] = typer.Option(None, help="CR start time (flexible date format: 2024-11-22 or 11-22-2024 or ISO8601); mark devices offline since this time."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Check patch compliance for macOS versions and applications.

    Date formats accepted: 2024-11-22, 11-22-2024, 11/22/2024, or ISO8601 (2024-11-22T00:00:00Z)
    """
    state: CliState = ctx.obj
    logger = state.logger
    try:
        # Parse flexible date format if provided
        cr_start_parsed = None
        if cr_start:
            try:
                cr_start_parsed = parse_flexible_date(cr_start, end_of_day=False)
                logger.debug(f"Parsed CR start: {cr_start_parsed}")
            except ValueError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(code=2)

        # Parse patch targets
        patch_targets = []
        client = None  # Will be created when needed

        # Add OS targets
        if os_version:
            for os_ver in os_version:
                for ver in os_ver.split(","):
                    ver = ver.strip()
                    if ver:
                        patch_targets.append(PatchTarget(name="macOS", target_type="os", min_version=ver, critical=True))

        # Add application targets
        if app_name:
            for app_spec in app_name:
                if ":" in app_spec:
                    # Explicit version provided
                    name, min_ver = app_spec.split(":", 1)
                    name_stripped = name.strip()

                    # Try to find patch_mgmt_id for optimization
                    if client is None:
                        client = _build_client(ctx, state)

                    patch_title = client.search_patch_software_title(name_stripped)
                    patch_mgmt_id = patch_title.id if patch_title else None
                    bundle_id = patch_title.bundle_id if patch_title else None

                    if patch_mgmt_id:
                        logger.debug(f"Found Patch Management entry for '{name_stripped}' (ID: {patch_mgmt_id})")
                    else:
                        logger.debug(f"No Patch Management entry for '{name_stripped}', will use inventory method")

                    patch_targets.append(PatchTarget(
                        name=name_stripped,
                        target_type="application",
                        min_version=min_ver.strip(),
                        critical=True,
                        bundle_id=bundle_id,
                        patch_mgmt_id=patch_mgmt_id
                    ))
                else:
                    # No version - try to auto-fetch from Patch Management
                    app_name_stripped = app_spec.strip()
                    logger.info(f"No version specified for '{app_name_stripped}', searching Patch Management...")

                    if client is None:
                        client = _build_client(ctx, state)

                    patch_title = client.search_patch_software_title(app_name_stripped)

                    if patch_title and patch_title.latest_version:
                        logger.info(
                            f"Found Patch Management entry: '{patch_title.name}' "
                            f"(latest version: {patch_title.latest_version})"
                        )
                        patch_targets.append(PatchTarget(
                            name=patch_title.name,
                            target_type="application",
                            min_version=patch_title.latest_version,
                            critical=True,
                            bundle_id=patch_title.bundle_id,
                            patch_mgmt_id=patch_title.id
                        ))
                    else:
                        # No Patch Management entry - try inventory-based discovery
                        logger.info(
                            f"No Patch Management entry for '{app_name_stripped}'. "
                            f"Attempting inventory-based discovery..."
                        )

                        # Fetch computers to scan for the application
                        from .patch_compliance import discover_application_from_inventory

                        computers = client.list_computers_inventory(
                            ids=([limiting_group_id] if limiting_group_id else None)
                        )

                        if not computers:
                            logger.error("No computers found in scope for inventory scan")
                            raise typer.Exit(code=2)

                        # Discover application from inventory
                        discovery_result = discover_application_from_inventory(
                            app_name_stripped, computers, client, logger
                        )

                        if discovery_result:
                            discovered_name, latest_version = discovery_result
                            logger.info(
                                f"✓ Discovered '{discovered_name}' via inventory scan "
                                f"(using version {latest_version} as target)"
                            )
                            typer.echo(
                                f"ℹ No Patch Management entry found. Using inventory discovery:\n"
                                f"  Application: {discovered_name}\n"
                                f"  Target version: {latest_version} (latest found across devices)"
                            )
                            patch_targets.append(PatchTarget(
                                name=discovered_name,
                                target_type="application",
                                min_version=latest_version,
                                critical=True,
                                bundle_id=None,  # Unknown without Patch Management
                                patch_mgmt_id=None
                            ))
                        else:
                            logger.error(
                                f"Application '{app_name_stripped}' not found via Patch Management OR inventory scan. "
                                "Options:\n"
                                "  1. Specify version explicitly (e.g., 'Google Chrome:131.0')\n"
                                "  2. Create a Patch Management entry in Jamf Pro\n"
                                "  3. Ensure the application is installed on at least one device"
                            )
                            raise typer.Exit(code=2)

        if not patch_targets:
            logger.error("No patch targets specified. Use --os-version or --app")
            raise typer.Exit(code=2)

        # Build client if not already created for Patch Management lookup
        if client is None:
            client = _build_client(ctx, state)

        results, exit_code = evaluate_patch_compliance(
            patch_targets=patch_targets,
            client=client,
            scope_group_id=limiting_group_id,
            cr_start=cr_start_parsed,
            logger=logger,
        )

        # Print summary
        typer.echo("\nPatch Compliance Report")
        typer.echo("=" * 60)
        typer.echo(f"Overall Compliance: {results.get('overallCompliance', 0):.1f}%")
        typer.echo(f"Total Devices: {results['scope']['totalDevices']}")
        typer.echo(f"Online Devices: {results['scope']['onlineDevices']}")
        typer.echo(f"Offline Devices: {results['scope']['offlineDevices']}")
        typer.echo()

        for target_result in results.get("targets", []):
            target_info = target_result.get("target", {})
            typer.echo(f"{target_info.get('name', 'Unknown')} ({target_info.get('type', 'unknown')}):")
            typer.echo(f"  Target: {target_info.get('minVersion', 'N/A')}")
            typer.echo(f"  Compliant: {target_result.get('compliant', 0)}/{target_result.get('total', 0)} ({target_result.get('complianceRate', 0):.1f}%)")

            non_compliant = target_result.get('nonCompliant', target_result.get('outdated', 0))
            if non_compliant > 0:
                typer.echo(f"  Non-Compliant: {non_compliant}")
            typer.echo()

        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)

        if state.output_xlsx:
            try:
                generate_excel_report(results, str(state.output_xlsx), logger)
            except ImportError as exc:
                logger.error(f"Excel report generation failed: {exc}")
                typer.echo(f"⚠️  Excel report generation failed: {exc}", err=True)
            except Exception as exc:
                logger.error(f"Excel report generation error: {exc}")
                typer.echo(f"⚠️  Excel report generation error: {exc}", err=True)

        if state.output_pdf:
            try:
                generate_pdf_report(results, str(state.output_pdf), logger)
            except ImportError as exc:
                logger.error(f"PDF report generation failed: {exc}")
                typer.echo(f"⚠️  PDF report generation failed: {exc}", err=True)
            except Exception as exc:
                logger.error(f"PDF report generation error: {exc}")
                typer.echo(f"⚠️  PDF report generation error: {exc}", err=True)

        if state.output_html:
            try:
                generate_html_report(results, str(state.output_html), logger)
            except Exception as exc:
                logger.error(f"HTML report generation error: {exc}")
                typer.echo(f"⚠️  HTML report generation error: {exc}", err=True)

        if state.teams_webhook_url:
            post_teams_summary(
                state.teams_webhook_url,
                title="Patch Compliance Report",
                summary=f"{results.get('overallCompliance', 0):.1f}% compliance across {results['scope']['totalDevices']} devices",
                data={"compliance": results.get('overallCompliance', 0), "devices": results['scope']['totalDevices']},
                logger=logger,
            )

        raise typer.Exit(code=exit_code)
    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("Patch compliance check error: %s", exc)
        raise typer.Exit(code=3)


@app.command("device-availability")
def device_availability_cmd(
    ctx: typer.Context,
    cr_start: str = typer.Option(..., help="CR window start time (flexible date format: 2024-11-22 or 11-22-2024 or ISO8601)"),
    cr_end: str = typer.Option(..., help="CR window end time (flexible date format: 2024-11-22 or 11-22-2024 or ISO8601)"),
    scope_group_id: Optional[int] = typer.Option(None, "--scope-group-id", help="Limit to specific group."),
    min_checkin_count: int = typer.Option(1, help="Minimum check-ins required during window."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
    output_xlsx: Optional[Path] = typer.Option(None, "--output-xlsx", help="Write command output to Excel (.xlsx) file."),
    output_pdf: Optional[Path] = typer.Option(None, "--output-pdf", help="Write command output to PDF file."),
    output_html: Optional[Path] = typer.Option(None, "--output-html", help="Write command output to HTML file."),
):
    """
    Analyze device availability during a CR window based on check-in patterns.

    Date formats accepted: 2024-11-22, 11-22-2024, 11/22/2024, or ISO8601 (2024-11-22T00:00:00Z)
    """
    state: CliState = ctx.obj
    logger = state.logger
    try:
        # Parse flexible date formats
        try:
            cr_start_parsed, cr_end_parsed = validate_date_range(cr_start, cr_end)
            logger.debug(f"Parsed CR window: {cr_start_parsed} → {cr_end_parsed}")
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        results, exit_code = analyze_device_availability(
            cr_start=cr_start_parsed,
            cr_end=cr_end_parsed,
            client=client,
            scope_group_id=scope_group_id,
            min_checkin_count=min_checkin_count,
            logger=logger,
        )

        # Print summary
        typer.echo("\nDevice Availability Report")
        typer.echo("=" * 60)
        cr_window = results.get("crWindow", {})
        typer.echo(f"CR Window: {cr_window.get('start')} → {cr_window.get('end')}")
        typer.echo(f"Duration: {cr_window.get('durationDays')} days")
        typer.echo(f"Total Devices: {results['scope']['totalDevices']}")
        typer.echo()

        avail = results.get("availability", {})
        typer.echo(f"Online During Window: {avail.get('onlineDuringWindow', {}).get('count', 0)} ({avail.get('onlineDuringWindow', {}).get('percentage', 0):.1f}%)")
        typer.echo(f"Offline During Window: {avail.get('offlineDuringWindow', {}).get('count', 0)} ({avail.get('offlineDuringWindow', {}).get('percentage', 0):.1f}%)")
        typer.echo()

        typer.echo("Recommendations:")
        for rec in results.get("recommendations", []):
            typer.echo(f"  • {rec}")

        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)

        xlsx_dest = output_xlsx or state.output_xlsx
        if xlsx_dest:
            try:
                generate_excel_report(results, str(xlsx_dest), logger)
            except Exception as exc:
                logger.error(f"Excel report generation failed: {exc}")
                typer.echo(f"⚠️  Excel report generation failed: {exc}", err=True)

        pdf_dest = output_pdf or state.output_pdf
        if pdf_dest:
            try:
                generate_pdf_report(results, str(pdf_dest), logger)
            except Exception as exc:
                logger.error(f"PDF report generation failed: {exc}")
                typer.echo(f"⚠️  PDF report generation failed: {exc}", err=True)

        html_dest = output_html or state.output_html
        if html_dest:
            try:
                generate_html_report(results, str(html_dest), logger)
            except Exception as exc:
                logger.error(f"HTML report generation failed: {exc}")
                typer.echo(f"⚠️  HTML report generation failed: {exc}", err=True)

        if state.teams_webhook_url:
            online_pct = avail.get('onlineDuringWindow', {}).get('percentage', 0)
            post_teams_summary(
                state.teams_webhook_url,
                title="Device Availability Report",
                summary=f"{online_pct:.1f}% devices online during CR window",
                data={"onlinePct": online_pct, "totalDevices": results['scope']['totalDevices']},
                logger=logger,
            )

        raise typer.Exit(code=exit_code)
    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("Device availability analysis error: %s", exc)
        raise typer.Exit(code=3)


@app.command("cr-summary")
def cr_summary_cmd(
    ctx: typer.Context,
    cr_name: str = typer.Option(..., help="Human-readable name for CR (e.g., 'November 2024 Patching')"),
    cr_start: str = typer.Option(..., help="CR window start time (flexible date format: 2024-11-22 or 11-22-2024 or ISO8601)"),
    cr_end: str = typer.Option(..., help="CR window end time (flexible date format: 2024-11-22 or 11-22-2024 or ISO8601)"),
    policy_id: List[int] = typer.Option(None, "--policy-id", help="Policy IDs that were executed during CR"),
    os_version: List[str] = typer.Option(None, "--target-os-version", help="Target macOS versions"),
    app: List[str] = typer.Option(None, "--target-app", help="Target app as 'Name:MinVersion'"),
    scope_group_id: Optional[int] = typer.Option(None, help="Limit to specific group."),
    success_threshold: float = typer.Option(0.95, help="Success rate required (0.0-1.0)"),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Generate comprehensive CR summary combining policy execution, patch compliance, and device availability.

    Date formats accepted: 2024-11-22, 11-22-2024, 11/22/2024, or ISO8601 (2024-11-22T00:00:00Z)
    """
    state: CliState = ctx.obj
    logger = state.logger
    try:
        # Parse flexible date formats
        try:
            cr_start_parsed, cr_end_parsed = validate_date_range(cr_start, cr_end)
            logger.debug(f"Parsed CR window: {cr_start_parsed} → {cr_end_parsed}")
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=2)

        # Parse patch targets
        patch_targets = []

        if os_version:
            for os_ver in os_version:
                for ver in os_ver.split(","):
                    ver = ver.strip()
                    if ver:
                        patch_targets.append(PatchTarget(name="macOS", target_type="os", min_version=ver, critical=True))

        if app:
            for app_spec in app:
                if ":" in app_spec:
                    name, min_ver = app_spec.split(":", 1)
                    patch_targets.append(PatchTarget(name=name.strip(), target_type="application", min_version=min_ver.strip(), critical=True))

        client = _build_client(ctx, state)

        results, exit_code = generate_cr_summary(
            cr_name=cr_name,
            cr_start=cr_start_parsed,
            cr_end=cr_end_parsed,
            policy_ids=list(policy_id) if policy_id else [],
            patch_targets=patch_targets,
            client=client,
            scope_group_id=scope_group_id,
            success_threshold=success_threshold,
            logger=logger,
        )

        # Print formatted summary
        typer.echo()
        typer.echo("=" * 70)
        typer.echo(f"Change Request Summary: {results['crName']}")
        typer.echo("=" * 70)

        cr_window = results.get("crWindow", {})
        typer.echo(f"Window: {cr_window.get('start')} → {cr_window.get('end')} ({cr_window.get('durationDays')} days)")
        typer.echo(f"Scope: {results.get('scope', {}).get('totalDevices', 0)} devices")
        typer.echo()

        cr_status = results.get("crStatus", {})
        if cr_status.get("successful"):
            typer.echo("┌" + "─" * 68 + "┐")
            typer.echo("│ Overall CR Status: ✓ SUCCESSFUL" + " " * 35 + "│")
            typer.echo("└" + "─" * 68 + "┘")
        else:
            typer.echo("┌" + "─" * 68 + "┐")
            typer.echo("│ Overall CR Status: ✗ NEEDS ATTENTION" + " " * 29 + "│")
            typer.echo("└" + "─" * 68 + "┘")

        typer.echo()

        # Device Availability
        if "deviceAvailability" in results:
            avail = results["deviceAvailability"]
            typer.echo("Device Availability:")
            typer.echo(f"  Online during window: {avail.get('onlineDuringWindow', {}).get('count', 0)} ({avail.get('onlineDuringWindow', {}).get('percentage', 0):.1f}%)")
            typer.echo(f"  Offline during window: {avail.get('offlineDuringWindow', {}).get('count', 0)} ({avail.get('offlineDuringWindow', {}).get('percentage', 0):.1f}%)")
            typer.echo()

        # Policy Execution
        if "policyExecution" in results and "summary" in results["policyExecution"]:
            typer.echo("Policy Execution Results:")
            for pol in results["policyExecution"]["summary"]:
                typer.echo(f"  Policy {pol['policyId']} '{pol['policyName']}':")
                typer.echo(f"    ✓ Completed: {pol['completed']} ({pol['completed']/max(pol['devicesInScope'],1)*100:.1f}%)")
                if pol["failed"] > 0:
                    typer.echo(f"    ✗ Failed: {pol['failed']}")
                if pol.get("offline", 0) > 0:
                    typer.echo(f"    ⚠ Offline: {pol['offline']}")
            typer.echo()

        # Patch Compliance
        if "patchCompliance" in results and "targets" in results["patchCompliance"]:
            typer.echo("Patch Compliance:")
            typer.echo(f"  Overall: {results['patchCompliance'].get('overallCompliance', 0):.1f}%")
            for target_result in results["patchCompliance"]["targets"]:
                target_info = target_result.get("target", {})
                rate = target_result.get("complianceRate", 0)
                typer.echo(f"  {target_info.get('name')}: {rate:.1f}%")
            typer.echo()

        # Issues
        if cr_status.get("issues"):
            typer.echo("Issues Requiring Attention:")
            for issue in cr_status["issues"]:
                typer.echo(f"  • {issue}")
            typer.echo()

        # Next Steps
        if cr_status.get("nextSteps"):
            typer.echo("Next Steps:")
            for step in cr_status["nextSteps"]:
                typer.echo(f"  {step}")
            typer.echo()

        typer.echo("=" * 70)

        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)

        if state.output_xlsx:
            try:
                generate_excel_report(results, str(state.output_xlsx), logger)
            except ImportError as exc:
                logger.error(f"Excel report generation failed: {exc}")
                typer.echo(f"⚠️  Excel report generation failed: {exc}", err=True)
            except Exception as exc:
                logger.error(f"Excel report generation error: {exc}")
                typer.echo(f"⚠️  Excel report generation error: {exc}", err=True)

        if state.output_pdf:
            try:
                generate_pdf_report(results, str(state.output_pdf), logger)
            except ImportError as exc:
                logger.error(f"PDF report generation failed: {exc}")
                typer.echo(f"⚠️  PDF report generation failed: {exc}", err=True)
            except Exception as exc:
                logger.error(f"PDF report generation error: {exc}")
                typer.echo(f"⚠️  PDF report generation error: {exc}", err=True)

        if state.output_html:
            try:
                generate_html_report(results, str(state.output_html), logger)
            except Exception as exc:
                logger.error(f"HTML report generation error: {exc}")
                typer.echo(f"⚠️  HTML report generation error: {exc}", err=True)

        if state.teams_webhook_url:
            status_emoji = "✓" if cr_status.get("successful") else "✗"
            post_teams_summary(
                state.teams_webhook_url,
                title=f"CR Summary: {cr_name}",
                summary=f"{status_emoji} CR {'Successful' if cr_status.get('successful') else 'Needs Attention'}",
                data={"status": "success" if cr_status.get("successful") else "attention", "devices": results.get('scope', {}).get('totalDevices', 0)},
                logger=logger,
            )

        raise typer.Exit(code=exit_code)
    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("CR summary generation error: %s", exc)
        raise typer.Exit(code=3)


@app.command("clear-cache")
def clear_cache_cmd(
    ctx: typer.Context,
):
    """
    Clear all cached API responses.

    This command removes all cached data from the local cache directory.
    Use this if you want to force fresh data retrieval or if you suspect
    cached data is stale or corrupted.

    The cache directory location is:
    - Default: ~/.jamf_health_tool/cache/
    - Custom: Configured via config file or --cache-dir option

    Examples:
        # Clear all cached data
        jamf-health-tool clear-cache

        # Then run commands to get fresh data
        jamf-health-tool --no-cache policy-failures --policy-id 123
    """
    state: CliState = ctx.obj
    logger = state.logger

    from .cache import FileCache

    # Use config to determine cache directory
    cache_dir = state.config.cache_dir
    cache = FileCache(cache_dir=cache_dir, logger=logger)

    try:
        stats_before = cache.stats()
        count = cache.clear()

        if count > 0:
            typer.echo(f"✓ Cleared {count} cache entries from {cache.cache_dir}")
            logger.info(f"Cleared {count} cache entries")
        else:
            typer.echo(f"Cache is already empty (directory: {cache.cache_dir})")

        # Show size freed
        if stats_before.get("total_size_bytes", 0) > 0:
            from .utils import format_size_bytes
            size_freed = format_size_bytes(stats_before["total_size_bytes"])
            typer.echo(f"  Freed: {size_freed}")

    except Exception as exc:
        logger.error(f"Failed to clear cache: {exc}")
        typer.echo(f"Error clearing cache: {exc}", err=True)
        raise typer.Exit(code=3)


@app.command("remediate-policies")
def remediate_policies_cmd(
    ctx: typer.Context,
    policy_id: List[int] = typer.Option(..., "--policy-id", help="Policy ID(s) to remediate (repeatable)."),
    computer_id: List[int] = typer.Option(None, "--computer-id", help="Computer ID(s) to remediate (repeatable)."),
    computer_list: Optional[Path] = typer.Option(None, "--computer-list", help="File containing computer IDs/serials/hostnames."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes."),
    send_blank_push: bool = typer.Option(False, help="Send blank push after flushing to trigger policy re-run."),
):
    """
    Remediate failed or stuck policies by flushing policy logs for individual computers.

    This command flushes policy execution history on SPECIFIC COMPUTERS ONLY, not the entire
    policy. This is safe for "once per computer" policies and prevents accidentally forcing
    all scoped computers to re-run the policy.

    This command:
    1. Flushes policy logs for the specified computers and policies
    2. Optionally sends a blank push to wake devices
    3. The policy will run again on next check-in (if still in scope)

    Safety features:
    - Dry-run mode to preview actions
    - Only flushes logs for specified computers (not entire policy)
    - Requires explicit policy and computer IDs
    - Logs all actions for audit trail

    Examples:
        # Preview flushing policy logs for specific computers
        jamf-health-tool remediate-policies --policy-id 10 --computer-id 123 --computer-id 456 --dry-run

        # Flush policy logs and send blank push
        jamf-health-tool remediate-policies --policy-id 10 --computer-list computers.txt --send-blank-push

        # Remediate multiple policies on specific computers
        jamf-health-tool remediate-policies --policy-id 10 --policy-id 20 --computer-id 123
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Validate inputs
        if not policy_id:
            typer.echo("Error: At least one --policy-id is required", err=True)
            raise typer.Exit(code=2)

        # Collect computer inputs
        inputs = _collect_computer_inputs(computer_id or [], [], computer_list)
        if not inputs:
            typer.echo("Error: At least one computer must be specified", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        # Resolve computer IDs from inputs
        from .utils import split_computer_identifiers
        ids, serials, names = split_computer_identifiers(inputs)
        computers = client.list_computers_inventory(ids=ids or None, serials=serials or None, names=names or None)

        if not computers:
            typer.echo("Error: No matching computers found", err=True)
            raise typer.Exit(code=2)

        computer_ids = [c.id for c in computers]
        logger.info(f"Targeting {len(computer_ids)} computers for policy remediation")

        # Show summary
        typer.echo("\n" + "=" * 70)
        typer.echo("Policy Remediation Plan")
        typer.echo("=" * 70)
        typer.echo(f"Policies to flush: {', '.join(str(p) for p in policy_id)}")
        typer.echo(f"Target computers: {len(computer_ids)}")
        typer.echo(f"Send blank push: {'Yes' if send_blank_push else 'No'}")

        if dry_run:
            typer.echo("\n⚠️  DRY RUN MODE - No changes will be made\n")

        typer.echo()

        # Execute remediation
        flushed_count = 0
        blank_push_count = 0
        errors = []

        for comp_id in computer_ids:
            comp_name = next((c.name for c in computers if c.id == comp_id), f"ID:{comp_id}")

            # Flush policy logs for each policy
            for pid in policy_id:
                if not dry_run:
                    if client.flush_policy_logs(comp_id, pid):
                        flushed_count += 1
                        logger.info(f"✓ Flushed policy {pid} logs for {comp_name}")
                    else:
                        errors.append(f"Failed to flush policy {pid} logs for {comp_name}")
                else:
                    logger.info(f"[DRY RUN] Would flush policy {pid} logs for {comp_name}")
                    flushed_count += 1

            # Send blank push if requested
            if send_blank_push:
                if not dry_run:
                    uuid = client.send_blank_push(comp_id)
                    if uuid:
                        blank_push_count += 1
                        logger.debug(f"Sent BlankPush to {comp_name} (UUID: {uuid})")
                    else:
                        errors.append(f"Failed to send BlankPush to {comp_name}")
                else:
                    logger.info(f"[DRY RUN] Would send BlankPush to {comp_name}")
                    blank_push_count += 1

        # Show results
        typer.echo("\n" + "=" * 70)
        typer.echo("Remediation Results")
        typer.echo("=" * 70)
        typer.echo(f"Policy logs flushed: {flushed_count}")
        if send_blank_push:
            typer.echo(f"Blank pushes sent: {blank_push_count}")
        if errors:
            typer.echo(f"\n⚠️  Errors encountered: {len(errors)}")
            for error in errors[:10]:
                typer.echo(f"  - {error}")
            if len(errors) > 10:
                typer.echo(f"  ... and {len(errors) - 10} more errors (check logs)")

        if dry_run:
            typer.echo("\n✓ Dry run completed - no actual changes were made")
        else:
            typer.echo("\n✓ Remediation completed")
            typer.echo("\nℹ Policies will re-run on affected computers at next check-in (if still in scope)")

        exit_code = 0 if not errors else 1
        raise typer.Exit(code=exit_code)

    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("Policy remediation error: %s", exc)
        raise typer.Exit(code=3)


@app.command("auto-remediate")
def auto_remediate_cmd(
    ctx: typer.Context,
    policy_id: List[int] = typer.Option(None, "--policy-id", help="Policy ID(s) to remediate (repeatable)."),
    profile_id: List[int] = typer.Option(None, "--profile-id", help="Profile ID(s) to remediate (repeatable)."),
    computer_id: List[int] = typer.Option(None, "--computer-id", help="Computer ID(s) to remediate (repeatable)."),
    computer_list: Optional[Path] = typer.Option(None, "--computer-list", help="File containing computer IDs/serials/hostnames."),
    max_retries: int = typer.Option(3, "--max-retries", help="Maximum retry attempts (1-10)."),
    retry_delay: int = typer.Option(300, "--retry-delay", help="Delay between retries in seconds."),
    send_blank_push: bool = typer.Option(True, help="Send blank push between retries to wake devices."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Automated remediation with intelligent retry logic.

    This command automatically retries failed policies and profiles with exponential
    backoff and recovery strategies. Perfect for CR windows where you want automated
    recovery without manual intervention.

    Features:
    - Automatic retry with configurable attempts
    - Blank push between retries to wake devices
    - Tracks all attempts for audit trail
    - Works with both policies and profiles

    Examples:
        # Auto-remediate policies with default 3 retries
        jamf-health-tool auto-remediate --policy-id 10 --policy-id 20 --computer-list failed.txt

        # Auto-remediate profiles with custom retry settings
        jamf-health-tool auto-remediate --profile-id 5 --computer-id 123 --max-retries 5 --retry-delay 600

        # Preview auto-remediation
        jamf-health-tool auto-remediate --policy-id 10 --profile-id 5 --computer-list devices.txt --dry-run
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Validate inputs
        if not policy_id and not profile_id:
            typer.echo("Error: At least one --policy-id or --profile-id is required", err=True)
            raise typer.Exit(code=2)

        if max_retries < 1 or max_retries > 10:
            typer.echo("Error: --max-retries must be between 1 and 10", err=True)
            raise typer.Exit(code=2)

        # Collect computer inputs
        inputs = _collect_computer_inputs(computer_id or [], [], computer_list)
        if not inputs:
            typer.echo("Error: At least one computer must be specified", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        # Resolve computer IDs
        from .utils import split_computer_identifiers
        ids, serials, names = split_computer_identifiers(inputs)
        computers = client.list_computers_inventory(ids=ids or None, serials=serials or None, names=names or None)

        if not computers:
            typer.echo("Error: No matching computers found", err=True)
            raise typer.Exit(code=2)

        computer_ids = [c.id for c in computers]

        # Show plan
        typer.echo("\n" + "=" * 70)
        typer.echo("Auto-Remediation Plan")
        typer.echo("=" * 70)
        if policy_id:
            typer.echo(f"Policies: {', '.join(str(p) for p in policy_id)}")
        if profile_id:
            typer.echo(f"Profiles: {', '.join(str(p) for p in profile_id)}")
        typer.echo(f"Computers: {len(computer_ids)}")
        typer.echo(f"Max retries per item: {max_retries}")
        typer.echo(f"Retry delay: {retry_delay}s")
        typer.echo(f"Send blank push: {'Yes' if send_blank_push else 'No'}")

        if dry_run:
            typer.echo("\n⚠️  DRY RUN MODE - No changes will be made")

        typer.echo()

        # Execute auto-remediation
        results, exit_code = auto_remediate(
            client=client,
            computer_ids=computer_ids,
            policy_ids=list(policy_id) if policy_id else None,
            profile_ids=list(profile_id) if profile_id else None,
            max_retries=max_retries,
            retry_delay=retry_delay,
            send_blank_push_between_retries=send_blank_push,
            dry_run=dry_run,
            logger=logger,
        )

        # Show results
        typer.echo("\n" + "=" * 70)
        typer.echo("Auto-Remediation Results")
        typer.echo("=" * 70)

        summary = results.get("summary", {})
        typer.echo(f"Total attempts: {summary.get('totalAttempts', 0)}")
        typer.echo(f"Successful: {summary.get('successfulAttempts', 0)}")
        typer.echo(f"Failed: {summary.get('failedAttempts', 0)}")
        typer.echo(f"Average attempts to success: {summary.get('averageAttemptsToSuccess', 0):.1f}")

        if results.get("policies"):
            pol = results["policies"]
            typer.echo(f"\nPolicies: {pol['succeeded']}/{pol['attempted']} succeeded")

        if results.get("profiles"):
            prof = results["profiles"]
            typer.echo(f"Profiles: {prof['succeeded']}/{prof['attempted']} succeeded")

        if dry_run:
            typer.echo("\n✓ Dry run completed")
        else:
            typer.echo("\n✓ Auto-remediation completed")

        # Save JSON
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)

        raise typer.Exit(code=exit_code)

    except (JamfCliError, JamfApiError, DataModelError, ValueError) as exc:
        logger.error("Auto-remediation error: %s", exc)
        raise typer.Exit(code=3)


@app.command("wake-devices")
def wake_devices_cmd(
    ctx: typer.Context,
    computer_id: List[int] = typer.Option(None, "--computer-id", help="Computer ID(s) to wake (repeatable)."),
    computer_list: Optional[Path] = typer.Option(None, "--computer-list", help="File containing computer IDs/serials/hostnames."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes."),
):
    """
    Send blank push notifications to wake devices for check-in.

    This command sends a BlankPush MDM command to devices, which wakes them up
    and causes them to process any pending MDM commands or policy executions.

    Use cases:
    - Wake offline devices during CR window
    - Trigger immediate check-in after profile/policy changes
    - Speed up deployment by not waiting for natural check-in

    Examples:
        # Wake specific devices
        jamf-health-tool wake-devices --computer-id 123 --computer-id 456

        # Wake all devices in a list
        jamf-health-tool wake-devices --computer-list offline_devices.txt

        # Preview wake operation
        jamf-health-tool wake-devices --computer-list devices.txt --dry-run
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Collect computer inputs
        inputs = _collect_computer_inputs(computer_id or [], [], computer_list)
        if not inputs:
            typer.echo("Error: At least one computer must be specified", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        # Resolve computer IDs
        from .utils import split_computer_identifiers
        ids, serials, names = split_computer_identifiers(inputs)
        computers = client.list_computers_inventory(ids=ids or None, serials=serials or None, names=names or None)

        if not computers:
            typer.echo("Error: No matching computers found", err=True)
            raise typer.Exit(code=2)

        computer_ids = [c.id for c in computers]

        typer.echo(f"\nSending blank push to {len(computer_ids)} device(s)...")
        if dry_run:
            typer.echo("⚠️  DRY RUN MODE - No changes will be made\n")

        success_count = 0
        errors = []

        for comp_id in computer_ids:
            comp_name = next((c.name for c in computers if c.id == comp_id), f"ID:{comp_id}")

            if not dry_run:
                uuid = client.send_blank_push(comp_id)
                if uuid:
                    success_count += 1
                    typer.echo(f"✓ {comp_name}")
                else:
                    errors.append(comp_name)
                    typer.echo(f"✗ {comp_name} - Failed")
            else:
                logger.info(f"[DRY RUN] Would send BlankPush to {comp_name}")
                success_count += 1
                typer.echo(f"[DRY RUN] {comp_name}")

        # Summary
        typer.echo(f"\n{'=' * 50}")
        typer.echo(f"Sent blank push to {success_count}/{len(computer_ids)} devices")
        if errors:
            typer.echo(f"Failed: {len(errors)} devices")

        if dry_run:
            typer.echo("\n✓ Dry run completed")
        else:
            typer.echo("\n✓ Commands sent - devices should check in shortly")

        exit_code = 0 if not errors else 1
        raise typer.Exit(code=exit_code)

    except (JamfCliError, JamfApiError, DataModelError) as exc:
        logger.error("Wake devices error: %s", exc)
        raise typer.Exit(code=3)


@app.command("update-inventory")
def update_inventory_cmd(
    ctx: typer.Context,
    computer_id: List[int] = typer.Option(None, "--computer-id", help="Computer ID(s) to update (repeatable)."),
    computer_list: Optional[Path] = typer.Option(None, "--computer-list", help="File containing computer IDs/serials/hostnames."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes."),
):
    """
    Send inventory update commands to force devices to submit fresh inventory data.

    This command sends an UpdateInventory MDM command to devices, which causes
    them to collect and submit current inventory information to Jamf Pro.

    Use cases:
    - Get latest application versions before compliance checks
    - Update hardware inventory after upgrades
    - Refresh inventory after major system changes

    Examples:
        # Update inventory for specific devices
        jamf-health-tool update-inventory --computer-id 123 --computer-id 456

        # Update inventory for all devices in a list
        jamf-health-tool update-inventory --computer-list devices.txt
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Collect computer inputs
        inputs = _collect_computer_inputs(computer_id or [], [], computer_list)
        if not inputs:
            typer.echo("Error: At least one computer must be specified", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        # Resolve computer IDs
        from .utils import split_computer_identifiers
        ids, serials, names = split_computer_identifiers(inputs)
        computers = client.list_computers_inventory(ids=ids or None, serials=serials or None, names=names or None)

        if not computers:
            typer.echo("Error: No matching computers found", err=True)
            raise typer.Exit(code=2)

        computer_ids = [c.id for c in computers]

        typer.echo(f"\nSending inventory update to {len(computer_ids)} device(s)...")
        if dry_run:
            typer.echo("⚠️  DRY RUN MODE - No changes will be made\n")

        success_count = 0
        errors = []

        for comp_id in computer_ids:
            comp_name = next((c.name for c in computers if c.id == comp_id), f"ID:{comp_id}")

            if not dry_run:
                uuid = client.update_inventory(comp_id)
                if uuid:
                    success_count += 1
                    typer.echo(f"✓ {comp_name}")
                else:
                    errors.append(comp_name)
                    typer.echo(f"✗ {comp_name} - Failed")
            else:
                logger.info(f"[DRY RUN] Would send UpdateInventory to {comp_name}")
                success_count += 1
                typer.echo(f"[DRY RUN] {comp_name}")

        # Summary
        typer.echo(f"\n{'=' * 50}")
        typer.echo(f"Sent inventory update to {success_count}/{len(computer_ids)} devices")
        if errors:
            typer.echo(f"Failed: {len(errors)} devices")

        if dry_run:
            typer.echo("\n✓ Dry run completed")
        else:
            typer.echo("\n✓ Commands sent - inventory will update on next check-in")

        exit_code = 0 if not errors else 1
        raise typer.Exit(code=exit_code)

    except (JamfCliError, JamfApiError, DataModelError) as exc:
        logger.error("Update inventory error: %s", exc)
        raise typer.Exit(code=3)


@app.command("run-workflow")
def run_workflow_cmd(
    ctx: typer.Context,
    workflow_file: Path = typer.Option(..., "--workflow-file", help="Path to workflow YAML file."),
    workflow_name: str = typer.Option(..., "--workflow", help="Name of workflow to execute."),
    phase: Optional[str] = typer.Option(None, "--phase", help="Specific phase to run (pre_cr, during_cr, post_cr). If not specified, runs all phases."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing."),
    validate_only: bool = typer.Option(False, "--validate-only", help="Only validate workflow file structure."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Execute a predefined CR workflow from YAML configuration.

    Workflows allow you to define repeatable CR processes with multiple
    commands executed in sequence across different phases.

    Workflow file structure:
        workflows:
          monthly_patching:
            pre_cr:
              - command: cr-readiness
                args:
                  scope_group_id: 100
            during_cr:
              - command: patch-compliance
                args:
                  os_version: "14.7.1"
            post_cr:
              - command: cr-summary
                args:
                  output_html: report.html

    Examples:
        # Validate workflow file
        jamf-health-tool run-workflow --workflow-file workflows.yml --workflow monthly --validate-only

        # Preview workflow execution
        jamf-health-tool run-workflow --workflow-file workflows.yml --workflow monthly --dry-run

        # Run entire workflow
        jamf-health-tool run-workflow --workflow-file workflows.yml --workflow monthly

        # Run only pre-CR phase
        jamf-health-tool run-workflow --workflow-file workflows.yml --workflow monthly --phase pre_cr
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Validate file exists
        if not workflow_file.exists():
            typer.echo(f"Error: Workflow file not found: {workflow_file}", err=True)
            raise typer.Exit(code=2)

        # Validate workflow file
        is_valid, errors = validate_workflow_file(workflow_file)

        if validate_only:
            typer.echo("\n" + "=" * 70)
            typer.echo("Workflow Validation")
            typer.echo("=" * 70)
            typer.echo(f"File: {workflow_file}")
            typer.echo()

            if is_valid:
                typer.echo("✓ Workflow file is valid")

                # Show available workflows
                import yaml
                with open(workflow_file, 'r') as f:
                    config = yaml.safe_load(f)
                    workflows = config.get('workflows', {})
                    typer.echo(f"\nAvailable workflows: {', '.join(workflows.keys())}")
            else:
                typer.echo("✗ Workflow file has errors:")
                for error in errors:
                    typer.echo(f"  • {error}")

            raise typer.Exit(code=0 if is_valid else 1)

        if not is_valid:
            typer.echo(f"Error: Invalid workflow file:", err=True)
            for error in errors:
                typer.echo(f"  • {error}", err=True)
            raise typer.Exit(code=2)

        # Execute workflow
        results, exit_code = execute_workflow(
            workflow_file=workflow_file,
            workflow_name=workflow_name,
            phase=phase,
            dry_run=dry_run,
            logger=logger,
        )

        # Print results
        typer.echo("\n" + "=" * 70)
        typer.echo(f"Workflow Execution: {results.get('workflowName')}")
        typer.echo("=" * 70)

        if dry_run:
            typer.echo("⚠️  DRY RUN MODE - No actual changes were made")
            typer.echo()

        summary = results.get('summary', {})
        typer.echo(f"Total commands: {summary.get('totalCommands', 0)}")
        typer.echo(f"Successful: {summary.get('successful', 0)}")
        typer.echo(f"Failed: {summary.get('failed', 0)}")
        typer.echo(f"Success rate: {summary.get('successRate', 0):.1f}%")
        typer.echo()

        # Show phases executed
        for phase_result in results.get('phasesExecuted', []):
            phase_name = phase_result.get('phase')
            commands = phase_result.get('commands', [])

            typer.echo(f"Phase: {phase_name} ({len(commands)} commands)")

            for cmd in commands:
                if cmd.get('success'):
                    typer.echo(f"  ✓ {cmd.get('command')}")
                else:
                    typer.echo(f"  ✗ {cmd.get('command')}")
                    if cmd.get('error'):
                        typer.echo(f"    Error: {cmd.get('error')}")

            typer.echo()

        # Show failures
        failures = results.get('failures', [])
        if failures:
            typer.echo("⚠️  Failures:")
            for failure in failures:
                typer.echo(f"  Phase: {failure.get('phase')}")
                typer.echo(f"  Command: {failure.get('command')}")
                typer.echo(f"  Error: {failure.get('error', 'Unknown error')}")
                typer.echo()

        typer.echo("=" * 70)

        if dry_run:
            typer.echo("\n✓ Dry run completed")
        elif exit_code == 0:
            typer.echo("\n✓ Workflow completed successfully")
        else:
            typer.echo("\n⚠️  Workflow completed with errors")

        # Save JSON
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)

        raise typer.Exit(code=exit_code)

    except (ValueError, FileNotFoundError) as exc:
        logger.error("Workflow execution error: %s", exc)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=3)


@app.command("problem-devices")
def problem_devices_cmd(
    ctx: typer.Context,
    cr_summary: List[Path] = typer.Option(..., "--cr-summary", help="CR summary JSON file(s) to analyze (repeatable)."),
    min_failures: int = typer.Option(3, "--min-failures", help="Minimum failures to be considered a problem device."),
    lookback_days: int = typer.Option(90, "--lookback-days", help="Only consider CRs within this many days."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Identify devices that consistently fail across multiple CR windows.

    This command analyzes multiple CR summary files to find problem devices
    that repeatedly fail policies, patch compliance, or other checks.

    Use this to:
    - Identify hardware that needs replacement
    - Find devices requiring reimaging
    - Detect configuration issues
    - Prioritize remediation efforts

    Examples:
        # Analyze last 3 months of CRs
        jamf-health-tool problem-devices --cr-summary oct_cr.json --cr-summary nov_cr.json --cr-summary dec_cr.json

        # Find devices with 5+ failures
        jamf-health-tool problem-devices --cr-summary *.json --min-failures 5 --lookback-days 60

        # Export problem devices list
        jamf-health-tool problem-devices --cr-summary *.json --output-json problem_devices.json
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Validate files
        valid_files = []
        for file_path in cr_summary:
            if file_path.exists():
                valid_files.append(file_path)
            else:
                typer.echo(f"Warning: File not found: {file_path}", err=True)

        if not valid_files:
            typer.echo("Error: No valid CR summary files provided", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        results, exit_code = analyze_problem_devices(
            client=client,
            cr_summary_files=valid_files,
            min_failures=min_failures,
            lookback_days=lookback_days,
            logger=logger,
        )

        # Print summary
        typer.echo("\n" + "=" * 70)
        typer.echo("Problem Devices Report")
        typer.echo("=" * 70)

        analysis_window = results.get('analysisWindow', {})
        typer.echo(f"CRs analyzed: {analysis_window.get('crsAnalyzed', 0)}")
        typer.echo(f"Lookback window: {analysis_window.get('lookbackDays', 0)} days")
        typer.echo(f"Failure threshold: {results.get('criteria', {}).get('minFailures', 0)}")
        typer.echo()

        summary = results.get('summary', {})
        typer.echo(f"Problem devices found: {summary.get('totalProblemDevices', 0)}")
        typer.echo()

        # Show top offenders (first 10)
        problem_devices = results.get('problemDevices', [])
        if problem_devices:
            typer.echo("Top Problem Devices:")
            for idx, device in enumerate(problem_devices[:10], 1):
                typer.echo(f"\n{idx}. {device['computerName']} (ID: {device['computerId']}, Serial: {device.get('serial', 'N/A')})")
                typer.echo(f"   Failures: {device['failureCount']} across {len(device['failures'])} CRs")

                failure_types = device.get('failureTypes', {})
                if failure_types:
                    types_str = ", ".join([f"{k}: {v}" for k, v in failure_types.items()])
                    typer.echo(f"   Types: {types_str}")

                recommendations = device.get('recommendations', [])
                if recommendations:
                    typer.echo(f"   Recommendations:")
                    for rec in recommendations[:2]:  # Show first 2
                        typer.echo(f"     • {rec}")

            if len(problem_devices) > 10:
                typer.echo(f"\n... and {len(problem_devices) - 10} more problem devices (see JSON output)")

        typer.echo()

        # Overall recommendations
        recommendations = results.get('recommendations', [])
        if recommendations:
            typer.echo("Recommendations:")
            for rec in recommendations:
                typer.echo(f"  {rec}")
            typer.echo()

        typer.echo("=" * 70)

        # Save JSON
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)
            typer.echo(f"\n✓ Full report saved to {json_dest}")

        raise typer.Exit(code=exit_code)

    except (ValueError, FileNotFoundError) as exc:
        logger.error("Problem devices analysis error: %s", exc)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=3)


@app.command("cr-compare")
def cr_compare_cmd(
    ctx: typer.Context,
    current_cr: Path = typer.Option(..., "--current", help="Path to current CR summary JSON file."),
    previous_cr: Path = typer.Option(..., "--previous", help="Path to previous CR summary JSON file."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Compare two CR windows to identify trends and improvements.

    This command compares results from two CR summary JSON files to:
    - Identify performance trends (improving/degrading/stable)
    - Highlight problem areas requiring attention
    - Celebrate improvements and successes
    - Generate actionable recommendations

    Use this to track CR performance over time and identify patterns.

    Examples:
        # Compare November and October CRs
        jamf-health-tool cr-compare --current nov_cr.json --previous oct_cr.json

        # Compare and save results
        jamf-health-tool cr-compare --current nov_cr.json --previous oct_cr.json --output-json comparison.json
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        # Validate files exist
        if not current_cr.exists():
            typer.echo(f"Error: Current CR file not found: {current_cr}", err=True)
            raise typer.Exit(code=2)

        if not previous_cr.exists():
            typer.echo(f"Error: Previous CR file not found: {previous_cr}", err=True)
            raise typer.Exit(code=2)

        results, exit_code = compare_cr_results(
            current_cr_file=current_cr,
            previous_cr_file=previous_cr,
            logger=logger,
        )

        # Print comparison
        typer.echo("\n" + "=" * 70)
        typer.echo("CR Comparison Report")
        typer.echo("=" * 70)

        current_cr_info = results.get('currentCR', {})
        previous_cr_info = results.get('previousCR', {})

        typer.echo(f"\nCurrent:  {current_cr_info.get('name')} ({current_cr_info.get('date')})")
        typer.echo(f"Previous: {previous_cr_info.get('name')} ({previous_cr_info.get('date')})")
        typer.echo()

        # Trends
        trends = results.get('trends', {})
        if trends:
            typer.echo("Trends:")
            for metric, trend in trends.items():
                icon = "📈" if trend == "Improving" else "📉" if trend == "Degrading" else "➡️"
                typer.echo(f"  {icon} {metric}: {trend}")
            typer.echo()

        # Improvements
        improvements = results.get('improvements', [])
        if improvements:
            typer.echo("✓ Improvements:")
            for improvement in improvements:
                typer.echo(f"  • {improvement}")
            typer.echo()

        # Problem areas
        problems = results.get('problemAreas', [])
        if problems:
            typer.echo("⚠️  Problem Areas:")
            for problem in problems:
                typer.echo(f"  • {problem}")
            typer.echo()

        # Recommendations
        recommendations = results.get('recommendations', [])
        if recommendations:
            typer.echo("Recommendations:")
            for rec in recommendations:
                typer.echo(f"  {rec}")
            typer.echo()

        typer.echo("=" * 70)

        # Save JSON
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)

        raise typer.Exit(code=exit_code)

    except (ValueError, FileNotFoundError) as exc:
        logger.error("CR comparison error: %s", exc)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=3)


@app.command("cr-readiness")
def cr_readiness_cmd(
    ctx: typer.Context,
    scope_group_id: Optional[int] = typer.Option(None, "--scope-group-id", help="Limit to specific group."),
    min_check_in_hours: int = typer.Option(24, "--min-check-in-hours", help="Devices must have checked in within this many hours."),
    min_disk_space: float = typer.Option(10.0, "--min-disk-space", help="Minimum free disk space in GB."),
    min_battery: int = typer.Option(20, "--min-battery", help="Minimum battery level for laptops (percent)."),
    output_json: Optional[Path] = typer.Option(None, "--output-json", "--json-out", help="Write command output to JSON file."),
):
    """
    Pre-flight readiness check before a Change Request window.

    This command analyzes device health and readiness, checking:
    - Last check-in time (devices must be online)
    - Disk space availability
    - Battery level (for laptops)
    - Pending MDM commands

    Use this BEFORE your CR window to identify and address issues proactively.

    Examples:
        # Check readiness for all devices
        jamf-health-tool cr-readiness

        # Check readiness for specific group with custom thresholds
        jamf-health-tool cr-readiness --scope-group-id 100 --min-check-in-hours 12 --min-disk-space 15

        # Check readiness and export results
        jamf-health-tool cr-readiness --output-json readiness.json
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        client = _build_client(ctx, state)

        results, exit_code = analyze_cr_readiness(
            client=client,
            scope_group_id=scope_group_id,
            min_check_in_hours=min_check_in_hours,
            min_disk_space_gb=min_disk_space,
            min_battery_percent=min_battery,
            logger=logger,
        )

        # Print summary
        typer.echo("\n" + "=" * 70)
        typer.echo("CR Readiness Report")
        typer.echo("=" * 70)

        scope = results.get("scope", {})
        readiness = results.get("readiness", {})
        typer.echo(f"Total Devices: {scope.get('totalDevices', 0)}")
        typer.echo(f"Ready: {readiness.get('ready', 0)} ({readiness.get('readinessRate', 0):.1f}%)")
        typer.echo(f"Not Ready: {readiness.get('notReady', 0)}")
        typer.echo()

        # Issue breakdown
        issue_breakdown = results.get("issueBreakdown", {})
        if issue_breakdown:
            typer.echo("Issue Breakdown:")
            for issue_type, count in issue_breakdown.items():
                typer.echo(f"  • {issue_type}: {count}")
            typer.echo()

        # Recommendations
        recommendations = results.get("recommendations", [])
        if recommendations:
            typer.echo("Recommendations:")
            for rec in recommendations:
                typer.echo(f"  {rec}")
            typer.echo()

        # Show not-ready devices (up to 20)
        not_ready_devices = [d for d in results.get("devices", []) if not d.get("ready")]
        if not_ready_devices:
            typer.echo(f"Not Ready Devices ({len(not_ready_devices)} total, showing first 20):")
            for device in not_ready_devices[:20]:
                typer.echo(f"\n  {device['name']} (ID: {device['id']})")
                for issue in device.get("issues", []):
                    typer.echo(f"    ✗ {issue}")
                for warning in device.get("warnings", []):
                    typer.echo(f"    ⚠ {warning}")

            if len(not_ready_devices) > 20:
                typer.echo(f"\n  ... and {len(not_ready_devices) - 20} more not-ready devices (see JSON output)")

        typer.echo("\n" + "=" * 70)

        # Save JSON output
        json_dest = output_json or state.output_json
        if json_dest:
            _write_json(json_dest, results, logger)

        # Post to Teams if configured
        if state.teams_webhook_url:
            from .teams_webhook import post_teams_summary
            post_teams_summary(
                state.teams_webhook_url,
                title="CR Readiness Check",
                summary=f"{readiness.get('readinessRate', 0):.1f}% devices ready ({readiness.get('ready', 0)}/{scope.get('totalDevices', 0)})",
                data={"ready": readiness.get('ready', 0), "notReady": readiness.get('notReady', 0), "rate": readiness.get('readinessRate', 0)},
                logger=logger,
            )

        raise typer.Exit(code=exit_code)

    except (JamfCliError, JamfApiError, DataModelError) as exc:
        logger.error("CR readiness check error: %s", exc)
        raise typer.Exit(code=3)


@app.command("restart-devices")
def restart_devices_cmd(
    ctx: typer.Context,
    computer_id: List[int] = typer.Option(None, "--computer-id", help="Computer ID(s) to restart (repeatable)."),
    computer_list: Optional[Path] = typer.Option(None, "--computer-list", help="File containing computer IDs/serials/hostnames."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm restart without interactive prompt."),
    delay_minutes: int = typer.Option(0, "--delay-minutes", help="Delay before restart (0-60 minutes). NOT IMPLEMENTED - immediate restart only."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes."),
):
    """
    Send restart commands to devices.

    ⚠️  WARNING: This command will RESTART devices immediately!

    This command sends a RestartDevice MDM command which causes an immediate
    restart. Users will lose unsaved work.

    Safety features:
    - Requires explicit --confirm flag
    - Dry-run mode to preview
    - Interactive confirmation if --confirm not provided

    Use cases:
    - Apply system updates that require restart
    - Clear system issues requiring reboot
    - Scheduled maintenance windows

    Examples:
        # Preview restart (safe)
        jamf-health-tool restart-devices --computer-id 123 --dry-run

        # Restart specific devices (will prompt for confirmation)
        jamf-health-tool restart-devices --computer-id 123 --computer-id 456

        # Restart without prompt (use in scripts)
        jamf-health-tool restart-devices --computer-list devices.txt --confirm
    """
    state: CliState = ctx.obj
    logger = state.logger

    try:
        if delay_minutes > 0:
            typer.echo("⚠️  Delayed restart is not currently supported by Jamf MDM API.", err=True)
            typer.echo("    Restart will be immediate when executed.", err=True)

        # Collect computer inputs
        inputs = _collect_computer_inputs(computer_id or [], [], computer_list)
        if not inputs:
            typer.echo("Error: At least one computer must be specified", err=True)
            raise typer.Exit(code=2)

        client = _build_client(ctx, state)

        # Resolve computer IDs
        from .utils import split_computer_identifiers
        ids, serials, names = split_computer_identifiers(inputs)
        computers = client.list_computers_inventory(ids=ids or None, serials=serials or None, names=names or None)

        if not computers:
            typer.echo("Error: No matching computers found", err=True)
            raise typer.Exit(code=2)

        computer_ids = [c.id for c in computers]

        # Show devices to be restarted
        typer.echo("\n" + "=" * 60)
        typer.echo("⚠️  RESTART DEVICES")
        typer.echo("=" * 60)
        typer.echo(f"\nThe following {len(computer_ids)} device(s) will be RESTARTED:\n")
        for comp in computers[:10]:
            typer.echo(f"  • {comp.name} (ID: {comp.id})")
        if len(computers) > 10:
            typer.echo(f"  ... and {len(computers) - 10} more devices")

        if dry_run:
            typer.echo("\n⚠️  DRY RUN MODE - No changes will be made")
            confirm = True  # Skip confirmation in dry run
        else:
            typer.echo("\n⚠️  This will RESTART devices IMMEDIATELY!")
            typer.echo("⚠️  Users will lose unsaved work!")

        # Require confirmation
        if not confirm and not dry_run:
            response = typer.prompt("\nType 'RESTART' to confirm", default="")
            if response != "RESTART":
                typer.echo("Cancelled.")
                raise typer.Exit(code=0)

        typer.echo()

        success_count = 0
        errors = []

        for comp_id in computer_ids:
            comp_name = next((c.name for c in computers if c.id == comp_id), f"ID:{comp_id}")

            if not dry_run:
                uuid = client.restart_device(comp_id)
                if uuid:
                    success_count += 1
                    typer.echo(f"✓ Sent restart to {comp_name}")
                else:
                    errors.append(comp_name)
                    typer.echo(f"✗ Failed to restart {comp_name}")
            else:
                logger.info(f"[DRY RUN] Would restart {comp_name}")
                success_count += 1
                typer.echo(f"[DRY RUN] Would restart {comp_name}")

        # Summary
        typer.echo(f"\n{'=' * 60}")
        typer.echo(f"Sent restart command to {success_count}/{len(computer_ids)} devices")
        if errors:
            typer.echo(f"Failed: {len(errors)} devices")

        if dry_run:
            typer.echo("\n✓ Dry run completed")
        else:
            typer.echo("\n✓ Restart commands sent")

        exit_code = 0 if not errors else 1
        raise typer.Exit(code=exit_code)

    except (JamfCliError, JamfApiError, DataModelError) as exc:
        logger.error("Restart devices error: %s", exc)
        raise typer.Exit(code=3)


def run():
    try:
        app()
    except Exception as exc:  # pylint: disable=broad-except
        typer.echo(f"Fatal error: {exc}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    run()

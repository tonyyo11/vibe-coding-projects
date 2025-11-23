"""
Workflow Automation

Execute predefined CR workflows from YAML configuration files.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def execute_workflow(
    workflow_file: Path,
    workflow_name: str,
    phase: Optional[str] = None,
    dry_run: bool = False,
    logger: Optional[logging.Logger] = None,
) -> tuple[Dict[str, Any], int]:
    """
    Execute a CR workflow from YAML file.

    Args:
        workflow_file: Path to workflow YAML file
        workflow_name: Name of workflow to execute
        phase: Optional phase to execute (pre_cr, during_cr, post_cr)
        dry_run: Preview mode - show what would be done
        logger: Optional logger

    Returns:
        Tuple of (results dict, exit code)
    """
    log = logger or logging.getLogger(__name__)

    # Load workflow file
    try:
        with open(workflow_file, 'r') as f:
            workflow_config = yaml.safe_load(f)
    except Exception as e:
        raise ValueError(f"Failed to load workflow file: {e}")

    workflows = workflow_config.get('workflows', {})
    if workflow_name not in workflows:
        available = ', '.join(workflows.keys())
        raise ValueError(f"Workflow '{workflow_name}' not found. Available: {available}")

    workflow = workflows[workflow_name]
    log.info(f"Executing workflow: {workflow_name}")

    # Determine phases to execute
    phases_to_run = []
    if phase:
        if phase in workflow:
            phases_to_run.append(phase)
        else:
            raise ValueError(f"Phase '{phase}' not found in workflow '{workflow_name}'")
    else:
        # Execute all phases in order
        for p in ['pre_cr', 'during_cr', 'post_cr']:
            if p in workflow:
                phases_to_run.append(p)

    # Execute phases
    results = {
        'workflowName': workflow_name,
        'phasesExecuted': [],
        'commandsExecuted': [],
        'failures': [],
    }

    total_commands = 0
    successful_commands = 0
    failed_commands = 0

    for phase_name in phases_to_run:
        log.info(f"Executing phase: {phase_name}")
        phase_config = workflow[phase_name]

        phase_result = {
            'phase': phase_name,
            'commands': [],
        }

        for step in phase_config:
            command = step.get('command')
            args = step.get('args', {})

            if not command:
                log.warning(f"Skipping step with no command: {step}")
                continue

            total_commands += 1

            # Build command line
            cmd_parts = ['jamf-health-tool', command]

            for key, value in args.items():
                # Convert snake_case to kebab-case for CLI args
                arg_name = key.replace('_', '-')

                if isinstance(value, bool):
                    if value:
                        cmd_parts.append(f'--{arg_name}')
                elif isinstance(value, list):
                    for item in value:
                        cmd_parts.append(f'--{arg_name}')
                        cmd_parts.append(str(item))
                else:
                    cmd_parts.append(f'--{arg_name}')
                    cmd_parts.append(str(value))

            cmd_str = ' '.join(cmd_parts)

            if dry_run:
                log.info(f"[DRY RUN] Would execute: {cmd_str}")
                phase_result['commands'].append({
                    'command': cmd_str,
                    'success': True,
                    'dryRun': True,
                })
                successful_commands += 1
            else:
                log.info(f"Executing: {cmd_str}")

                try:
                    # Execute command
                    result = subprocess.run(
                        cmd_parts,
                        capture_output=True,
                        text=True,
                        timeout=600,  # 10 minute timeout
                    )

                    success = result.returncode == 0

                    phase_result['commands'].append({
                        'command': cmd_str,
                        'returnCode': result.returncode,
                        'success': success,
                        'stdout': result.stdout[:500] if result.stdout else None,  # Truncate
                        'stderr': result.stderr[:500] if result.stderr else None,
                    })

                    if success:
                        successful_commands += 1
                        log.info(f"✓ Command succeeded")
                    else:
                        failed_commands += 1
                        log.error(f"✗ Command failed with exit code {result.returncode}")
                        results['failures'].append({
                            'phase': phase_name,
                            'command': cmd_str,
                            'returnCode': result.returncode,
                            'error': result.stderr[:200] if result.stderr else None,
                        })

                except subprocess.TimeoutExpired:
                    failed_commands += 1
                    log.error(f"✗ Command timed out")
                    results['failures'].append({
                        'phase': phase_name,
                        'command': cmd_str,
                        'error': 'Command timed out after 10 minutes',
                    })
                    phase_result['commands'].append({
                        'command': cmd_str,
                        'success': False,
                        'error': 'Timeout',
                    })

                except Exception as e:
                    failed_commands += 1
                    log.error(f"✗ Command execution error: {e}")
                    results['failures'].append({
                        'phase': phase_name,
                        'command': cmd_str,
                        'error': str(e),
                    })
                    phase_result['commands'].append({
                        'command': cmd_str,
                        'success': False,
                        'error': str(e),
                    })

        results['phasesExecuted'].append(phase_result)

    # Summary
    results['summary'] = {
        'totalCommands': total_commands,
        'successful': successful_commands,
        'failed': failed_commands,
        'successRate': (successful_commands / total_commands * 100) if total_commands > 0 else 0,
    }

    # Determine exit code
    exit_code = 0
    if failed_commands > 0:
        if failed_commands > successful_commands:
            exit_code = 2  # Majority failed
        else:
            exit_code = 1  # Some failures

    return results, exit_code


def validate_workflow_file(workflow_file: Path) -> tuple[bool, List[str]]:
    """
    Validate workflow YAML file structure.

    Args:
        workflow_file: Path to workflow file

    Returns:
        Tuple of (is_valid, list of errors)
    """
    errors = []

    try:
        with open(workflow_file, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        return False, [f"Failed to parse YAML: {e}"]

    if not isinstance(config, dict):
        return False, ["Root must be a dictionary"]

    if 'workflows' not in config:
        return False, ["Missing 'workflows' key"]

    workflows = config['workflows']
    if not isinstance(workflows, dict):
        return False, ["'workflows' must be a dictionary"]

    if not workflows:
        return False, ["No workflows defined"]

    # Validate each workflow
    valid_phases = ['pre_cr', 'during_cr', 'post_cr']

    for workflow_name, workflow_config in workflows.items():
        if not isinstance(workflow_config, dict):
            errors.append(f"Workflow '{workflow_name}' must be a dictionary")
            continue

        # Check has at least one phase
        has_phase = any(phase in workflow_config for phase in valid_phases)
        if not has_phase:
            errors.append(f"Workflow '{workflow_name}' has no valid phases (pre_cr, during_cr, post_cr)")

        # Validate each phase
        for phase in valid_phases:
            if phase in workflow_config:
                phase_config = workflow_config[phase]

                if not isinstance(phase_config, list):
                    errors.append(f"Workflow '{workflow_name}' phase '{phase}' must be a list")
                    continue

                # Validate each step
                for idx, step in enumerate(phase_config):
                    if not isinstance(step, dict):
                        errors.append(f"Workflow '{workflow_name}' phase '{phase}' step {idx} must be a dictionary")
                        continue

                    if 'command' not in step:
                        errors.append(f"Workflow '{workflow_name}' phase '{phase}' step {idx} missing 'command'")

    is_valid = len(errors) == 0
    return is_valid, errors

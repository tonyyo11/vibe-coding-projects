"""
CR Comparison - Historical CR outcome comparison

Compare success rates and outcomes between different CR windows to identify trends.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def compare_cr_results(
    current_cr_file: Path,
    previous_cr_file: Path,
    logger: Optional[logging.Logger] = None,
) -> tuple[Dict[str, Any], int]:
    """
    Compare results from two CR summary JSON files.

    Args:
        current_cr_file: Path to current CR summary JSON
        previous_cr_file: Path to previous CR summary JSON
        logger: Optional logger

    Returns:
        Tuple of (comparison results dict, exit code)
    """
    log = logger or logging.getLogger(__name__)

    # Load JSON files
    try:
        with open(current_cr_file, 'r') as f:
            current = json.load(f)
    except Exception as e:
        raise ValueError(f"Failed to load current CR file: {e}")

    try:
        with open(previous_cr_file, 'r') as f:
            previous = json.load(f)
    except Exception as e:
        raise ValueError(f"Failed to load previous CR file: {e}")

    log.info(f"Comparing CR: {current.get('crName')} vs {previous.get('crName')}")

    # Extract key metrics
    current_metrics = _extract_metrics(current)
    previous_metrics = _extract_metrics(previous)

    # Calculate deltas
    deltas = _calculate_deltas(current_metrics, previous_metrics)

    # Identify trends
    trends = _identify_trends(deltas)

    # Find problem areas
    problem_areas = _find_problem_areas(deltas, current_metrics, previous_metrics)

    # Find improvements
    improvements = _find_improvements(deltas, current_metrics, previous_metrics)

    # Build comparison results
    results = {
        "generatedAt": datetime.now().isoformat(),
        "currentCR": {
            "name": current.get('crName'),
            "date": current.get('crWindow', {}).get('start'),
            "metrics": current_metrics,
        },
        "previousCR": {
            "name": previous.get('crName'),
            "date": previous.get('crWindow', {}).get('start'),
            "metrics": previous_metrics,
        },
        "deltas": deltas,
        "trends": trends,
        "problemAreas": problem_areas,
        "improvements": improvements,
        "recommendations": _generate_recommendations(trends, problem_areas, improvements),
    }

    # Determine exit code
    exit_code = 0
    if len(problem_areas) > len(improvements):
        exit_code = 1  # More problems than improvements
    if deltas.get('overallCompliance', 0) < -10:
        exit_code = 2  # Significant degradation

    return results, exit_code


def _extract_metrics(cr_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key metrics from CR summary."""
    metrics = {}

    # Overall compliance
    patch = cr_data.get('patchCompliance', {})
    if patch:
        metrics['overallCompliance'] = patch.get('overallCompliance', 0)

    # Device availability
    avail = cr_data.get('deviceAvailability', {})
    if avail:
        metrics['onlinePercentage'] = avail.get('onlineDuringWindow', {}).get('percentage', 0)

    # Policy execution
    policy_exec = cr_data.get('policyExecution', {})
    if policy_exec:
        policies = policy_exec.get('summary', [])
        if policies:
            total_in_scope = sum(p.get('devicesInScope', 0) for p in policies)
            total_completed = sum(p.get('completed', 0) for p in policies)
            total_failed = sum(p.get('failed', 0) for p in policies)

            metrics['policySuccessRate'] = (total_completed / total_in_scope * 100) if total_in_scope > 0 else 0
            metrics['totalPolicyFailures'] = total_failed

    # CR status
    cr_status = cr_data.get('crStatus', {})
    metrics['successful'] = cr_status.get('successful', False)

    # Scope
    scope = cr_data.get('scope', {})
    metrics['totalDevices'] = scope.get('totalDevices', 0)

    return metrics


def _calculate_deltas(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate deltas between current and previous metrics."""
    deltas = {}

    for key in current:
        if key in previous and isinstance(current[key], (int, float)):
            delta = current[key] - previous[key]
            deltas[key] = round(delta, 2)

    return deltas


def _identify_trends(deltas: Dict[str, Any]) -> Dict[str, str]:
    """Identify trends from deltas."""
    trends = {}

    trend_map = {
        'overallCompliance': 'Overall Compliance',
        'onlinePercentage': 'Device Availability',
        'policySuccessRate': 'Policy Success Rate',
        'totalPolicyFailures': 'Policy Failures',
    }

    for key, label in trend_map.items():
        if key in deltas:
            delta = deltas[key]

            if key == 'totalPolicyFailures':
                # Inverse - fewer failures is better
                if delta < 0:
                    trends[label] = 'Improving'
                elif delta > 0:
                    trends[label] = 'Degrading'
                else:
                    trends[label] = 'Stable'
            else:
                # Normal - higher is better
                if delta > 5:
                    trends[label] = 'Improving'
                elif delta < -5:
                    trends[label] = 'Degrading'
                else:
                    trends[label] = 'Stable'

    return trends


def _find_problem_areas(
    deltas: Dict[str, Any],
    current: Dict[str, Any],
    previous: Dict[str, Any]
) -> List[str]:
    """Identify problem areas (degradations)."""
    problems = []

    # Overall compliance degradation
    if deltas.get('overallCompliance', 0) < -5:
        problems.append(
            f"Overall compliance decreased by {abs(deltas['overallCompliance']):.1f}% "
            f"({previous.get('overallCompliance', 0):.1f}% → {current.get('overallCompliance', 0):.1f}%)"
        )

    # Device availability degradation
    if deltas.get('onlinePercentage', 0) < -5:
        problems.append(
            f"Device availability decreased by {abs(deltas['onlinePercentage']):.1f}% "
            f"({previous.get('onlinePercentage', 0):.1f}% → {current.get('onlinePercentage', 0):.1f}%)"
        )

    # Policy success rate degradation
    if deltas.get('policySuccessRate', 0) < -5:
        problems.append(
            f"Policy success rate decreased by {abs(deltas['policySuccessRate']):.1f}% "
            f"({previous.get('policySuccessRate', 0):.1f}% → {current.get('policySuccessRate', 0):.1f}%)"
        )

    # More policy failures
    if deltas.get('totalPolicyFailures', 0) > 5:
        problems.append(
            f"Policy failures increased by {deltas['totalPolicyFailures']} "
            f"({previous.get('totalPolicyFailures', 0)} → {current.get('totalPolicyFailures', 0)})"
        )

    return problems


def _find_improvements(
    deltas: Dict[str, Any],
    current: Dict[str, Any],
    previous: Dict[str, Any]
) -> List[str]:
    """Identify improvements."""
    improvements = []

    # Overall compliance improvement
    if deltas.get('overallCompliance', 0) > 5:
        improvements.append(
            f"Overall compliance improved by {deltas['overallCompliance']:.1f}% "
            f"({previous.get('overallCompliance', 0):.1f}% → {current.get('overallCompliance', 0):.1f}%)"
        )

    # Device availability improvement
    if deltas.get('onlinePercentage', 0) > 5:
        improvements.append(
            f"Device availability improved by {deltas['onlinePercentage']:.1f}% "
            f"({previous.get('onlinePercentage', 0):.1f}% → {current.get('onlinePercentage', 0):.1f}%)"
        )

    # Policy success rate improvement
    if deltas.get('policySuccessRate', 0) > 5:
        improvements.append(
            f"Policy success rate improved by {deltas['policySuccessRate']:.1f}% "
            f"({previous.get('policySuccessRate', 0):.1f}% → {current.get('policySuccessRate', 0):.1f}%)"
        )

    # Fewer policy failures
    if deltas.get('totalPolicyFailures', 0) < -5:
        improvements.append(
            f"Policy failures decreased by {abs(deltas['totalPolicyFailures'])} "
            f"({previous.get('totalPolicyFailures', 0)} → {current.get('totalPolicyFailures', 0)})"
        )

    return improvements


def _generate_recommendations(
    trends: Dict[str, str],
    problems: List[str],
    improvements: List[str]
) -> List[str]:
    """Generate recommendations based on comparison."""
    recommendations = []

    if len(problems) > len(improvements):
        recommendations.append("⚠️  Performance degraded - investigate recent changes")
        recommendations.append("Review problem-devices report to identify repeat offenders")

    if len(improvements) > len(problems):
        recommendations.append("✓ Performance improved - current approach working well")
        recommendations.append("Document successful strategies for future CRs")

    degrading_trends = [k for k, v in trends.items() if v == 'Degrading']
    if degrading_trends:
        recommendations.append(f"Focus on improving: {', '.join(degrading_trends)}")

    if 'Device Availability' in degrading_trends:
        recommendations.append("Use wake-devices and update-inventory before next CR")

    if 'Policy Success Rate' in degrading_trends:
        recommendations.append("Use auto-remediate with retry logic for better policy delivery")

    if not problems and not improvements:
        recommendations.append("Performance stable - maintain current processes")

    return recommendations

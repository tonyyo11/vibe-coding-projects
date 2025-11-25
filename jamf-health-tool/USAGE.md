# Jamf Health Tool - Usage Guide

Complete how-to guide with detailed examples and workflows for all commands.

---

## Table of Contents

- [Command Overview](#command-overview)
- [Patch Compliance](#patch-compliance)
- [Device Availability](#device-availability)
- [CR Summary](#cr-summary)
- [Policy Failures](#policy-failures)
- [MDM Failures](#mdm-failures)
- [Profile Audit](#profile-audit)
- [Complete CR Workflows](#complete-cr-workflows)
- [Advanced Use Cases](#advanced-use-cases)
- [Automation Examples](#automation-examples)
- [Output Format Details](#output-format-details)
- [Integration Guide](#integration-guide)
- [Best Practices](#best-practices)

---

## Command Overview

The Jamf Health Tool provides sixteen production-ready commands for comprehensive Jamf Pro monitoring and automation:

### Core Validation Commands (v1.0)

| Command | Purpose | Primary Use Case |
|---------|---------|------------------|
| `patch-compliance` | OS and app version validation | Verify patching policies worked |
| `device-availability` | Online/offline analysis | Understand device reachability |
| `cr-summary` | Comprehensive CR validation | Friday CR sign-off |
| `policy-failures` | Policy execution tracking | Identify failed policies |
| `mdm-failures` | MDM command tracking | Diagnose MDM issues |
| `profile-audit` | Profile deployment audit | Scope vs. application validation |

### Pre-CR Preparation Commands (v3.0)

| Command | Purpose | Primary Use Case |
|---------|---------|------------------|
| `cr-readiness` | Pre-flight CR validation | Check device readiness before CR start |
| `wake-devices` | MDM blank push | Wake sleeping devices before/during CR |
| `update-inventory` | Force inventory update | Refresh device data before validation |
| `restart-devices` | Managed device restart | Safely restart devices after updates |

### Active Remediation Commands (v3.0)

| Command | Purpose | Primary Use Case |
|---------|---------|------------------|
| `remediate-policies` | Flush and retry policies | Fix failed policy executions |
| `remediate-profiles` | Reinstall profiles | Fix profile deployment failures |
| `auto-remediate` | Intelligent auto-retry | Hands-off remediation with backoff |

### Long-Term Strategy Commands (v3.0)

| Command | Purpose | Primary Use Case |
|---------|---------|------------------|
| `cr-compare` | Historical CR comparison | Month-over-month trend analysis |
| `problem-devices` | Chronic failure tracking | Identify devices needing hardware attention |
| `run-workflow` | YAML workflow automation | Execute multi-phase CR workflows |

---

## Patch Compliance

### Overview

The `patch-compliance` command validates that devices are running target OS and application versions. It's optimized to use Jamf's Patch Report API for 98% faster performance.

### Basic Examples

#### Check Single OS Version

```bash
jamf-health-tool patch-compliance \
  --os-version "15.1"
```

**Output**:
```
Patch Compliance Report
============================================================
Overall Compliance: 95.2%
Total Devices: 1000
Online Devices: 980
Offline Devices: 20

macOS (os):
  Target: 15.1
  Compliant: 933/980 (95.2%)
  Non-Compliant: 47
```

#### Check Multiple OS Versions (Sonoma, Sequoia, Tahoe)

```bash
jamf-health-tool patch-compliance \
  --os-version "14.7.1,15.1,26.0"
```

**Use Case**: Support multiple macOS major versions in your environment

**Output**:
```
macOS (os):
  Target: 14.7.1,15.1,26.0
  Compliant: 980/980 (100%)
  Non-Compliant: 0

  Breakdown by version:
    14.7.1 (Sonoma):  500 devices
    15.1 (Sequoia):   478 devices
    26.0 (Tahoe):     2 devices
```

#### Auto-Fetch Application Version

```bash
# Tool automatically finds latest Safari version from Patch Management
jamf-health-tool patch-compliance \
  --app "Safari"
```

**What Happens**:
1. Searches Patch Management for "Safari"
2. Finds latest version (e.g., 18.1)
3. Uses optimized Patch Report API (1 call for all devices)
4. Returns compliance status

**Output**:
```
Safari (application):
  Target: 18.1 (auto-fetched)
  Compliant: 735/750 (98.0%)
  Non-Compliant: 10
  Not Installed: 5
  Note: Only checking devices on macOS 15.x (230 devices excluded)
```

**Optimization**: 1 API call instead of 750+

#### Explicit Application Version

```bash
jamf-health-tool patch-compliance \
  --app "Google Chrome:131.0.6778.86"
```

**Use Case**: Check specific version instead of latest

### Advanced Options

#### Scope to Specific Group

```bash
jamf-health-tool patch-compliance \
  --os-version "15.1" \
  --limiting-group-id 123
```

**Use Case**: Check only production Macs, exclude lab devices

#### Exclude Offline Devices

```bash
jamf-health-tool patch-compliance \
  --os-version "15.1" \
  --cr-start "2024-11-18T00:00:00Z"
```

**Behavior**: Only checks devices that checked in after CR start

**Use Case**: CR validation - don't count devices that were offline during patching window

#### Multiple Applications

```bash
jamf-health-tool patch-compliance \
  --app "Safari" \
  --app "Google Chrome" \
  --app "Microsoft Office" \
  --app "Zoom"
```

**Performance**: Each app uses optimized Patch Report (1 call per app)

#### With Bundle ID (Fallback)

```bash
jamf-health-tool patch-compliance \
  --app "Safari:18.1" \
  --bundle-id "com.apple.Safari"
```

**Use Case**: When application name doesn't match Patch Management entry exactly

### Output Formats

#### JSON Output

```bash
jamf-health-tool patch-compliance \
  --os-version "15.1" \
  --app "Safari" \
  --output-json compliance_report.json
```

**JSON Structure**:
```json
{
  "generatedAt": "2024-11-22T17:00:00Z",
  "scope": {
    "totalDevices": 1000,
    "onlineDevices": 980,
    "offlineDevices": 20
  },
  "targets": [
    {
      "target": {
        "name": "macOS",
        "type": "os",
        "minVersion": "15.1",
        "critical": true
      },
      "total": 980,
      "compliant": 933,
      "outdated": 47,
      "complianceRate": 95.2,
      "compliantDevices": [...],
      "outdatedDevices": [...]
    },
    {
      "target": {
        "name": "Safari",
        "type": "application",
        "minVersion": "18.1",
        "critical": true,
        "patchMgmtId": 4
      },
      "total": 750,
      "compliant": 735,
      "outdated": 10,
      "notInstalled": 5,
      "complianceRate": 98.0
    }
  ],
  "overallCompliance": 96.6
}
```

#### Excel Output

```bash
jamf-health-tool \
  --output-xlsx compliance_report.xlsx \
  patch-compliance \
    --os-version "15.1" \
    --app "Safari"
```

**Excel Features**:
- Multiple sheets (Summary, OS Compliance, Safari Compliance, Offline Devices)
- Formatted tables with filters
- Color coding (green = compliant, red = non-compliant)
- Device lists with serial numbers and names

#### PDF Output

```bash
jamf-health-tool \
  --output-pdf compliance_report.pdf \
  patch-compliance \
    --os-version "15.1" \
    --app "Safari"
```

**PDF Features**:
- Professional formatting
- Summary statistics
- Detailed device tables
- Ready for management reporting

### Understanding Results

#### Compliance Calculation

```
Overall Compliance = (Total Compliant Devices) / (Total Online Devices) * 100
```

**Example**:
- Total Devices: 1000
- Offline Devices: 20
- Online Devices: 980
- Compliant with macOS 15.1: 933
- Compliant with Safari 18.1: 735

**Calculation**:
- macOS Compliance: 933 / 980 = 95.2%
- Safari Compliance: 735 / 750 = 98.0% (excluding devices not eligible for Safari 18.1)
- Overall: (933 + 735) / (980 + 750) = 96.6%

#### Major Version Filtering

When checking Safari 18.1 (requires macOS 15.x):
- ✅ **Included**: Devices on macOS 15.x
- ❌ **Excluded**: Devices on macOS 14.x (not eligible for Safari 18.1)
- ❌ **Excluded**: Offline devices

**Output Shows**:
```
Note: Only checking devices on macOS 15.x (230 devices excluded)
```

### Exit Codes

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| `0` | All online devices compliant | ✅ Success |
| `1` | Some devices non-compliant | ⚠️ Review non-compliant list |
| `3` | Error occurred | ❌ Check logs |

### Common Workflows

#### Monday - Pre-CR Baseline

```bash
# Document current state before patching
jamf-health-tool patch-compliance \
  --os-version "14.7.1" \
  --output-json /var/log/jamf-cr/monday_baseline.json
```

#### Wednesday - Mid-Week Progress Check

```bash
# Quick check to see how many devices have updated
jamf-health-tool patch-compliance \
  --os-version "15.1" \
  --cr-start "2024-11-18T00:00:00Z"
```

#### Friday - Final CR Validation

```bash
# Comprehensive compliance check with all output formats
jamf-health-tool \
  --output-xlsx /var/log/jamf-cr/friday_compliance.xlsx \
  --output-pdf /var/log/jamf-cr/friday_compliance.pdf \
  patch-compliance \
    --os-version "15.1" \
    --app "Safari" \
    --app "Google Chrome" \
    --cr-start "2024-11-18T00:00:00Z" \
    --output-json /var/log/jamf-cr/friday_compliance.json
```

---

## Device Availability

### Overview

The `device-availability` command analyzes which devices were online and reachable during your CR window. Essential for understanding why some policies didn't run.

### Basic Examples

#### Analyze CR Window

```bash
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z"
```

**Output**:
```
Device Availability Report
============================================================
CR Window: 2024-11-18T00:00:00Z → 2024-11-22T23:59:59Z
Duration: 5 days
Total Devices: 1000

Online Entire Window: 850 (85.0%)
Online Partial Window: 130 (13.0%)
Offline Entire Window: 20 (2.0%)

Recommendations:
  • Good device availability: 85.0% online during window
  • Review 130 devices with sporadic check-ins - may need policy rescoping
  • Follow up on 20 devices offline - may need manual intervention
```

#### Scope to Specific Group

```bash
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --scope-group-id 123
```

**Use Case**: Analyze only production Macs

### Advanced Options

#### Minimum Check-In Count

```bash
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --min-checkin-count 3
```

**Behavior**: Devices need at least 3 check-ins to be considered "online entire window"

**Use Case**: Stricter availability requirements

### Output Formats

#### JSON Output

```bash
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --output-json device_availability.json
```

**JSON Structure**:
```json
{
  "generatedAt": "2024-11-22T17:00:00Z",
  "crWindow": {
    "start": "2024-11-18T00:00:00Z",
    "end": "2024-11-22T23:59:59Z",
    "durationDays": 5
  },
  "scope": {
    "totalDevices": 1000,
    "scopeGroupId": null
  },
  "availability": {
    "onlineEntireWindow": {
      "count": 850,
      "percentage": 85.0,
      "devices": [
        {
          "id": 1,
          "name": "MacBook-001",
          "serial": "C02ABC123",
          "lastContactTime": "2024-11-22T16:45:00Z",
          "checkinCount": 15
        }
      ]
    },
    "onlinePartialWindow": {
      "count": 130,
      "percentage": 13.0,
      "devices": [...]
    },
    "offlineEntireWindow": {
      "count": 20,
      "percentage": 2.0,
      "devices": [...]
    }
  },
  "recommendations": [
    "Good device availability: 85.0% online during window",
    "Review 130 devices with sporadic check-ins - may need policy rescoping",
    "Follow up on 20 devices offline - may need manual intervention"
  ]
}
```

#### Excel Output

```bash
jamf-health-tool \
  --output-xlsx device_availability.xlsx \
  device-availability \
    --cr-start "2024-11-18T00:00:00Z" \
    --cr-end "2024-11-22T23:59:59Z"
```

**Excel Features**:
- Summary sheet with statistics
- Online Entire Window sheet with full device list
- Online Partial Window sheet
- Offline Entire Window sheet
- Filters on all columns

### Understanding Categories

#### Online Entire Window

**Criteria**: Device checked in at least once during CR window AND last check-in is recent

**Definition of "Recent"**:
- Within 24 hours of CR end

**Example**:
- CR Window: Nov 18-22
- Device last check-in: Nov 22, 4:00 PM
- **Status**: Online Entire Window ✅

#### Online Partial Window

**Criteria**: Device checked in during window BUT last check-in is NOT recent

**Example**:
- CR Window: Nov 18-22
- Device checked in: Nov 19, 10:00 AM
- Device last check-in: Nov 19, 10:00 AM (3 days ago)
- **Status**: Online Partial Window ⚠️

**Interpretation**: Device was online Monday but went offline mid-week

#### Offline Entire Window

**Criteria**: Device never checked in during CR window OR last check-in before CR start

**Example**:
- CR Window: Nov 18-22
- Device last check-in: Nov 15, 2:00 PM
- **Status**: Offline Entire Window ❌

### Common Workflows

#### Monday - Baseline Availability

```bash
# Snapshot of current device status
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-18T00:00:00Z" \
  --output-json /var/log/jamf-cr/monday_availability.json
```

**Use Case**: Document which devices are reachable before starting CR

#### Wednesday - Check CR Progress

```bash
# See how many devices have checked in so far
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

**Use Case**: Real-time availability during CR window

#### Friday - Final Availability Report

```bash
jamf-health-tool \
  --output-xlsx /var/log/jamf-cr/friday_availability.xlsx \
  device-availability \
    --cr-start "2024-11-18T00:00:00Z" \
    --cr-end "2024-11-22T23:59:59Z" \
    --output-json /var/log/jamf-cr/friday_availability.json
```

**Use Case**: Understand which devices were unreachable during CR

---

## CR Summary

### Overview

The `cr-summary` command is the comprehensive CR validation tool that combines:
1. Device Availability Analysis
2. Policy Execution Results
3. Patch Compliance Checking

It provides a single command to answer: "Is the CR successful?"

### Basic Example

```bash
jamf-health-tool cr-summary \
  --cr-name "November 2024 Patching" \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --policy-id 100 --policy-id 101 \
  --target-os-version "15.1" \
  --target-app "Safari" \
  --scope-group-id 123 \
  --success-threshold 0.95
```

**Output**:
```
======================================================================
Change Request Summary: November 2024 Patching
======================================================================
Window: 2024-11-18T00:00:00Z → 2024-11-22T23:59:59Z (5 days)
Scope: 1000 devices

┌────────────────────────────────────────────────────────────────────┐
│ Overall CR Status: ✓ SUCCESSFUL                                    │
└────────────────────────────────────────────────────────────────────┘

Device Availability:
  Online entire window: 980 (98.0%)
  Offline during window: 20 (2.0%)

Policy Execution Results:
  Policy 100 'macOS Update':
    ✓ Completed: 930 (93.0%)
    ✗ Failed: 50 (5.0%)
  Policy 101 'Safari Update':
    ✓ Completed: 940 (94.0%)

Patch Compliance:
  Overall: 95.0%
  macOS: 95.0%
  Safari: 98.0%

Issues Requiring Attention:
  (none - CR successful)

Next Steps:
  Review 50 devices with policy failures (see failedDevices in JSON)
  Follow up on 20 devices offline during CR window
  CR completed successfully - verify random sample of devices
  Document CR completion in change management system

======================================================================
```

### Comprehensive Example

```bash
jamf-health-tool \
  --output-xlsx /var/log/jamf-cr/cr_summary.xlsx \
  --output-pdf /var/log/jamf-cr/cr_summary.pdf \
  cr-summary \
    --cr-name "November 2024 Comprehensive Patching" \
    --cr-start "2024-11-18T00:00:00Z" \
    --cr-end "2024-11-22T23:59:59Z" \
    --policy-id 100 \
    --policy-id 101 \
    --policy-id 102 \
    --target-os-version "14.7.1,15.1,26.0" \
    --target-app "Safari" \
    --target-app "Google Chrome" \
    --target-app "Microsoft Office" \
    --scope-group-id 123 \
    --success-threshold 0.95 \
    --output-json /var/log/jamf-cr/cr_summary.json \
    --teams-webhook-url "$TEAMS_WEBHOOK_URL"
```

**What This Does**:
1. Analyzes device availability (Nov 18-22)
2. Checks policy execution for policies 100, 101, 102
3. Validates patch compliance for OS and 3 applications
4. Generates JSON, Excel, and PDF reports
5. Sends summary to Microsoft Teams
6. Exits with 0 (success) or 1 (needs attention)

### CR Window Filtering

**New in v3.0**: Policy executions are automatically filtered to only count runs within the CR window, preventing completion rates >100%.

#### Why This Matters

Without filtering, weekly automated policies can show inflated completion rates:

**Problem Scenario**:
- Policy 2573 (Sketch Update) has 66 devices in scope
- Policy runs weekly (automated, not flushed before CR)
- During 10-day CR window, some devices run it 2-3 times
- **Result**: 96 total executions / 66 devices = **145.5% completion rate**

#### How It Works

**Default Behavior (Recommended)**:
```bash
jamf-health-tool cr-summary \
  --cr-start "2024-11-18" \
  --cr-end "2024-11-22" \
  --policy-id 2573 \
  --filter-cr-window  # DEFAULT - enabled automatically
```

**What Gets Filtered**:
- ✅ Only counts policy executions between `--cr-start` and `--cr-end`
- ✅ Deduplicates: Only the **most recent** execution status per device
- ✅ Automatically handles mid-CR policy flushes
- ✅ Caps completion rates at 100%

**Example Output (Filtered)**:
```
Policy 2573 'Sketch - Auto Update':
  ✓ Completed: 64 (97.0%)    # Capped at 100%
  ✗ Failed: 1
  ⚠ Offline: 1
```

#### Legacy Mode (All Executions)

To see all policy executions regardless of timing:

```bash
jamf-health-tool cr-summary \
  --cr-start "2024-11-18" \
  --cr-end "2024-11-22" \
  --policy-id 2573 \
  --no-filter-cr-window  # Show all runs
```

**Use Cases for --no-filter-cr-window**:
- Troubleshooting policy execution issues
- Understanding full policy run history
- Analyzing policies that run multiple times intentionally
- Debugging why completion rates seem low

**Example Output (Unfiltered)**:
```
Policy 2573 'Sketch - Auto Update':
  ✓ Completed: 96 (145.5%)    # Shows multiple runs
  ✗ Failed: 2
  ⚠ Offline: 1
```

#### Real-World Scenarios

**Scenario 1: Weekly Patching Policy**
- Policy runs every Monday at 9 AM
- CR window: Nov 18-22 (includes 2 Mondays)
- Without filtering: Device runs it twice, counted as 200%
- **With filtering**: Only most recent run counted, capped at 100%

**Scenario 2: Mid-CR Policy Flush**
- Google Chrome policy flushed on Nov 20 (mid-CR)
- Pre-flush runs: Nov 18-19
- Post-flush runs: Nov 20-22
- **With filtering**: Only counts post-flush runs (correct)
- Without filtering: Counts both, shows inflated rates

**Scenario 3: Offline Devices with Old Runs**
- Device last online: Nov 1 (before CR)
- Policy ran successfully on Nov 1
- CR window: Nov 18-22
- **With filtering**: Device marked "Offline" (correct)
- Without filtering: Shows as "Completed" (misleading)

#### Recommendations

✅ **Use default (--filter-cr-window)** for:
- Official CR validation reports
- Change management sign-offs
- Compliance reporting
- Determining CR success/failure

⚠️ **Use --no-filter-cr-window** for:
- Investigating policy behavior
- Understanding why rates are lower than expected
- Troubleshooting policy execution timing
- Developer/admin analysis only

### Success Threshold

The `--success-threshold` parameter determines CR success:

```bash
# Strict: 98% compliance required
--success-threshold 0.98

# Standard: 95% compliance required (DEFAULT)
--success-threshold 0.95

# Lenient: 90% compliance required
--success-threshold 0.90
```

**How It's Used**:
```
if overallCompliance >= successThreshold:
    CR Status = SUCCESSFUL (exit code 0)
else:
    CR Status = NEEDS ATTENTION (exit code 1)
```

**Recommendations by Environment**:
- **Production**: 95-98%
- **Test/Development**: 85-90%
- **Initial Rollout**: 80-85%

### Teams Integration

```bash
export TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/YOUR-WEBHOOK-URL"

jamf-health-tool cr-summary \
  --cr-name "November 2024 Patching" \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --target-os-version "15.1" \
  --teams-webhook-url "$TEAMS_WEBHOOK_URL"
```

**Teams Message Includes**:
- CR name and status (✓ Successful or ⚠️ Needs Attention)
- Overall compliance percentage
- Device counts
- Summary of issues (if any)
- Link to detailed report (if available)

### Output Formats

#### JSON Output

Complete JSON structure includes:
- CR configuration
- Device availability breakdown
- Policy execution results (per policy)
- Patch compliance (per target)
- Overall CR status
- Next steps

See example in [Output Format Details](#output-format-details) section.

#### Excel Output

**Sheets Included**:
1. **Summary** - CR overview and status
2. **Device Availability** - Online/offline breakdown
3. **Policy Results** - Per-policy execution details
4. **Patch Compliance** - OS and app compliance
5. **Failed Devices** - Complete list of devices needing attention
6. **Offline Devices** - Devices unreachable during CR

#### PDF Output

Professional report suitable for management review:
- Executive summary
- Key metrics and statistics
- Detailed results tables
- Recommendations and next steps

### Exit Codes

| Exit Code | CR Status | Action |
|-----------|-----------|--------|
| `0` | ✓ SUCCESSFUL | Close CR ticket |
| `1` | ⚠️ NEEDS ATTENTION | Review failures, extend window |
| `3` | ✗ ERROR | Check logs, verify credentials |

### Common Workflows

#### Friday Afternoon - Weekly CR Validation

```bash
#!/bin/bash
# /usr/local/bin/friday-cr-validation.sh

CR_NAME="Week of $(date +%Y-%m-%d) Patching"
CR_START="2024-11-18T00:00:00Z"
CR_END="2024-11-22T23:59:59Z"
OUTPUT_DIR="/var/log/jamf-cr"

echo "=== Generating CR Summary: $CR_NAME ==="

jamf-health-tool \
  --output-xlsx "$OUTPUT_DIR/cr_summary_$(date +%Y%m%d).xlsx" \
  --output-pdf "$OUTPUT_DIR/cr_summary_$(date +%Y%m%d).pdf" \
  cr-summary \
    --cr-name "$CR_NAME" \
    --cr-start "$CR_START" \
    --cr-end "$CR_END" \
    --policy-id 100 --policy-id 101 --policy-id 102 \
    --target-os-version "15.1" \
    --target-app "Safari" \
    --target-app "Google Chrome" \
    --scope-group-id 123 \
    --success-threshold 0.95 \
    --output-json "$OUTPUT_DIR/cr_summary_$(date +%Y%m%d).json" \
    --teams-webhook-url "$TEAMS_WEBHOOK_URL"

CR_STATUS=$?

if [ $CR_STATUS -eq 0 ]; then
    echo "✓ CR SUCCESSFUL - Ready to close ticket"
    echo "Reports saved to: $OUTPUT_DIR"
elif [ $CR_STATUS -eq 1 ]; then
    echo "⚠ CR NEEDS ATTENTION"
    echo "Review failed devices in: $OUTPUT_DIR/cr_summary_$(date +%Y%m%d).xlsx"
    exit 1
else
    echo "✗ ERROR during CR validation"
    exit 3
fi
```

---

## Policy Failures

### Overview

The `policy-failures` command tracks which Jamf policies failed execution and on which devices.

### Basic Examples

#### Check Single Policy

```bash
jamf-health-tool policy-failures \
  --policy-id 100 \
  --since "2024-11-18T00:00:00Z"
```

**Output**:
```
Policy Failures Report
============================================================
Policy: macOS Update (ID: 100)
Since: 2024-11-18T00:00:00Z

Failed Executions: 50
Affected Devices: 50
Success Rate: 95.0%

Failed Devices:
  MacBook-001 (C02ABC123) - Last Failure: 2024-11-19T10:30:00Z
  MacBook-002 (C02ABC124) - Last Failure: 2024-11-19T11:15:00Z
  ...
```

#### Check Multiple Policies

```bash
jamf-health-tool policy-failures \
  --policy-id 100 \
  --policy-id 101 \
  --policy-id 102 \
  --since "2024-11-18T00:00:00Z"
```

### Advanced Options

#### Limit Results

```bash
jamf-health-tool policy-failures \
  --policy-id 100 \
  --since "2024-11-18T00:00:00Z" \
  --limit 10
```

**Use Case**: Quick check - just show first 10 failures

#### Output to JSON

```bash
jamf-health-tool policy-failures \
  --policy-id 100 \
  --since "2024-11-18T00:00:00Z" \
  --output-json policy_failures.json
```

### Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| `0` | No failures found |
| `2` | Failures found |
| `3` | Error occurred |

---

## MDM Failures

### Overview

The `mdm-failures` command identifies failed MDM commands across your fleet.

### Basic Example

```bash
jamf-health-tool mdm-failures \
  --since "2024-11-18T00:00:00Z"
```

**Output**:
```
MDM Failures Report
============================================================
Since: 2024-11-18T00:00:00Z

Total Failed Commands: 25
Affected Devices: 15

Common Failures:
  InstallProfile: 10 failures
  RemoveProfile: 8 failures
  RestartDevice: 5 failures
  EraseDevice: 2 failures

Failed Devices:
  MacBook-001 (C02ABC123) - 3 failed commands
  MacBook-002 (C02ABC124) - 2 failed commands
  ...
```

### Output to JSON

```bash
jamf-health-tool mdm-failures \
  --since "2024-11-18T00:00:00Z" \
  --output-json mdm_failures.json
```

### Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| `0` | No failures found |
| `2` | Failures found |
| `3` | Error occurred |

---

## Profile Audit

### Overview

The `profile-audit` command validates that scoped configuration profiles are actually installed on target devices.

### Basic Example

```bash
jamf-health-tool profile-audit \
  --profile-name "Security Baseline"
```

**Output**:
```
Profile Audit Report
============================================================
Profile: Security Baseline

Scoped Devices: 1000
Installed: 980 (98.0%)
Missing: 20 (2.0%)

Missing Devices:
  MacBook-001 (C02ABC123)
  MacBook-002 (C02ABC124)
  ...
```

### Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| `0` | All scoped devices have profile |
| `2` | Some devices missing profile |
| `3` | Error occurred |

---

## Complete CR Workflows

### Monday Morning - CR Start

```bash
#!/bin/bash
# monday-cr-start.sh

CR_NAME="November 2024 Patching"
CR_START="2024-11-18T00:00:00Z"
CR_END="2024-11-22T23:59:59Z"
GROUP_ID="123"
OUTPUT_DIR="/var/log/jamf-cr"

mkdir -p "$OUTPUT_DIR"

echo "=== Starting CR: $CR_NAME ==="
echo "Window: $CR_START to $CR_END"
echo ""

# Baseline device availability
echo "Taking baseline device availability snapshot..."
jamf-health-tool \
  --output-xlsx "$OUTPUT_DIR/monday_availability.xlsx" \
  device-availability \
    --cr-start "$CR_START" \
    --cr-end "$CR_START" \
    --scope-group-id $GROUP_ID \
    --output-json "$OUTPUT_DIR/monday_availability.json"

echo ""
echo "✓ Baseline saved"
echo "📊 Review: $OUTPUT_DIR/monday_availability.xlsx"
echo ""
echo "Next Steps:"
echo "  1. Review baseline availability"
echo "  2. Enable patching policies in Jamf Pro"
echo "  3. Monitor throughout the week"
```

### Wednesday - Mid-Week Check

```bash
#!/bin/bash
# wednesday-progress-check.sh

echo "=== Mid-Week CR Progress Check ==="
echo ""

# Quick compliance check
jamf-health-tool \
  --output-xlsx /var/log/jamf-cr/wednesday_progress.xlsx \
  patch-compliance \
    --os-version "14.7.1,15.1,26.0" \
    --app "Safari" \
    --app "Google Chrome" \
    --limiting-group-id 123 \
    --cr-start "2024-11-18T00:00:00Z" \
    --output-json /var/log/jamf-cr/wednesday_progress.json

echo ""
echo "Progress check complete"
echo ""
echo "If compliance is low (<70%), consider:"
echo "  - Extending CR window"
echo "  - Investigating policy failures"
echo "  - Checking device availability"
```

### Friday - Final CR Validation

```bash
#!/bin/bash
# friday-final-validation.sh

CR_NAME="November 2024 Patching"
CR_START="2024-11-18T00:00:00Z"
CR_END="2024-11-22T23:59:59Z"
OUTPUT_DIR="/var/log/jamf-cr"

echo "=== Generating Final CR Validation Report ==="
echo "This will take ~30 seconds for 1000 devices"
echo ""

jamf-health-tool \
  --output-xlsx "$OUTPUT_DIR/cr_final_report.xlsx" \
  --output-pdf "$OUTPUT_DIR/cr_final_report.pdf" \
  cr-summary \
    --cr-name "$CR_NAME" \
    --cr-start "$CR_START" \
    --cr-end "$CR_END" \
    --policy-id 100 --policy-id 101 --policy-id 102 \
    --target-os-version "14.7.1,15.1,26.0" \
    --target-app "Safari" \
    --target-app "Google Chrome" \
    --target-app "Microsoft Office" \
    --scope-group-id 123 \
    --success-threshold 0.95 \
    --output-json "$OUTPUT_DIR/cr_final_report.json" \
    --teams-webhook-url "$TEAMS_WEBHOOK_URL"

CR_STATUS=$?

echo ""
echo "============================================================"
if [ $CR_STATUS -eq 0 ]; then
    echo "✓ CR SUCCESSFUL"
    echo "============================================================"
    echo "  ✓ Compliance threshold met (≥95%)"
    echo "  ✓ Reports generated:"
    echo "      - JSON:  $OUTPUT_DIR/cr_final_report.json"
    echo "      - Excel: $OUTPUT_DIR/cr_final_report.xlsx"
    echo "      - PDF:   $OUTPUT_DIR/cr_final_report.pdf"
    echo "  ✓ Teams notification sent"
    echo ""
    echo "Next Steps:"
    echo "  1. Attach reports to CR ticket"
    echo "  2. Document CR completion"
    echo "  3. Close CR ticket"
    echo "  4. Schedule follow-up for outlier devices"
    exit 0
elif [ $CR_STATUS -eq 1 ]; then
    echo "⚠ CR NEEDS ATTENTION"
    echo "============================================================"
    echo "  ⚠ Compliance below threshold (<95%)"
    echo "  📊 Review detailed reports:"
    echo "      - Excel: $OUTPUT_DIR/cr_final_report.xlsx"
    echo "      - PDF:   $OUTPUT_DIR/cr_final_report.pdf"
    echo ""
    echo "Action Required:"
    echo "  1. Review failed devices in Excel report"
    echo "  2. Investigate root causes"
    echo "  3. Consider extending CR window"
    echo "  4. Schedule follow-up maintenance"
    exit 1
else
    echo "✗ CR VALIDATION ERROR"
    echo "============================================================"
    echo "  ✗ An error occurred during validation"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Verify API credentials"
    echo "  2. Check network connectivity"
    echo "  3. Review error messages above"
    exit 3
fi
```

---

## Advanced Use Cases

### Scheduled CR Monitoring

Run `cr-summary` daily during CR window to track progress:

```bash
#!/bin/bash
# /usr/local/bin/cr-daily-check.sh

jamf-health-tool cr-summary \
  --cr-name "$(date +%Y-%m-%d) Daily Check" \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --policy-id 100 --policy-id 101 \
  --target-os-version "15.1" \
  --scope-group-id 123 \
  --output-json "/var/log/jamf-cr/daily-$(date +%Y%m%d).json" \
  --teams-webhook-url "$TEAMS_WEBHOOK_URL"
```

**Cron Schedule** (8 AM, 12 PM, 4 PM on weekdays):
```cron
0 8,12,16 * * 1-5 /usr/local/bin/cr-daily-check.sh
```

### Multiple Device Groups

Check different groups separately:

```bash
# Production Macs
jamf-health-tool cr-summary \
  --cr-name "Prod Macs - Nov 2024" \
  --limiting-group-id 100 \
  --output-json prod_cr_summary.json \
  ...

# Lab Macs
jamf-health-tool cr-summary \
  --cr-name "Lab Macs - Nov 2024" \
  --limiting-group-id 200 \
  --output-json lab_cr_summary.json \
  ...
```

### Historical Tracking

Save CR reports for trend analysis:

```bash
#!/bin/bash
# Archive CR reports by date

DATE=$(date +%Y%m%d)
ARCHIVE_DIR="/var/log/jamf-cr/archive/$DATE"

mkdir -p "$ARCHIVE_DIR"

# Run CR summary
jamf-health-tool \
  --output-xlsx "$ARCHIVE_DIR/cr_summary.xlsx" \
  cr-summary \
    --cr-name "CR $DATE" \
    ... \
    --output-json "$ARCHIVE_DIR/cr_summary.json"

# Keep only last 90 days
find /var/log/jamf-cr/archive -type d -mtime +90 -exec rm -rf {} \;
```

---

## Automation Examples

### Jenkins Integration

```groovy
// Jenkinsfile
pipeline {
    agent any

    environment {
        JAMF_BASE_URL = credentials('jamf-base-url')
        JAMF_CLIENT_ID = credentials('jamf-client-id')
        JAMF_CLIENT_SECRET = credentials('jamf-client-secret')
        TEAMS_WEBHOOK_URL = credentials('teams-webhook-url')
    }

    parameters {
        string(name: 'CR_NAME', description: 'Change Request Name')
        string(name: 'CR_START', description: 'CR Start (ISO8601)')
        string(name: 'CR_END', description: 'CR End (ISO8601)')
    }

    stages {
        stage('CR Validation') {
            steps {
                sh '''
                    jamf-health-tool \\
                      --output-xlsx cr_summary.xlsx \\
                      --output-pdf cr_summary.pdf \\
                      cr-summary \\
                        --cr-name "${CR_NAME}" \\
                        --cr-start "${CR_START}" \\
                        --cr-end "${CR_END}" \\
                        --target-os-version "15.1" \\
                        --target-app "Safari" \\
                        --success-threshold 0.95 \\
                        --output-json cr_summary.json \\
                        --teams-webhook-url "${TEAMS_WEBHOOK_URL}"
                '''
            }
        }

        stage('Archive Reports') {
            steps {
                archiveArtifacts artifacts: '*.json,*.xlsx,*.pdf'
            }
        }
    }

    post {
        success {
            echo 'CR validation successful'
        }
        failure {
            echo 'CR needs attention - review reports'
        }
    }
}
```

### GitHub Actions

```yaml
# .github/workflows/cr-validation.yml
name: CR Validation

on:
  schedule:
    - cron: '0 16 * * 5'  # Every Friday at 4 PM UTC
  workflow_dispatch:

jobs:
  validate-cr:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install Jamf Health Tool
        run: |
          pip install -e ".[reports]"

      - name: Run CR Validation
        env:
          JAMF_BASE_URL: ${{ secrets.JAMF_BASE_URL }}
          JAMF_CLIENT_ID: ${{ secrets.JAMF_CLIENT_ID }}
          JAMF_CLIENT_SECRET: ${{ secrets.JAMF_CLIENT_SECRET }}
          TEAMS_WEBHOOK_URL: ${{ secrets.TEAMS_WEBHOOK_URL }}
        run: |
          jamf-health-tool \\
            --output-xlsx cr_summary.xlsx \\
            cr-summary \\
              --cr-name "Weekly CR $(date +%Y-%m-%d)" \\
              --cr-start "$(date -d 'last monday' -u +%Y-%m-%dT00:00:00Z)" \\
              --cr-end "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \\
              --target-os-version "15.1" \\
              --success-threshold 0.95 \\
              --output-json cr_summary.json \\
              --teams-webhook-url "$TEAMS_WEBHOOK_URL"

      - name: Upload Reports
        uses: actions/upload-artifact@v3
        with:
          name: cr-reports
          path: |
            cr_summary.json
            cr_summary.xlsx
```

---

## Output Format Details

### JSON Output Structure

All commands output consistent JSON for easy parsing:

#### patch-compliance JSON

```json
{
  "generatedAt": "2024-11-22T17:00:00Z",
  "scope": {
    "totalDevices": 1000,
    "onlineDevices": 980,
    "offlineDevices": 20,
    "limitingGroupId": 123
  },
  "targets": [
    {
      "target": {
        "name": "macOS",
        "type": "os",
        "minVersion": "15.1",
        "critical": true
      },
      "total": 980,
      "compliant": 933,
      "outdated": 47,
      "complianceRate": 95.2,
      "compliantDevices": [
        {
          "id": 1,
          "name": "MacBook-001",
          "serial": "C02ABC123",
          "osVersion": "15.1"
        }
      ],
      "outdatedDevices": [
        {
          "id": 2,
          "name": "MacBook-002",
          "serial": "C02ABC124",
          "osVersion": "14.7.1"
        }
      ]
    }
  ],
  "overallCompliance": 95.2,
  "offlineDevices": [...]
}
```

#### device-availability JSON

```json
{
  "generatedAt": "2024-11-22T17:00:00Z",
  "crWindow": {
    "start": "2024-11-18T00:00:00Z",
    "end": "2024-11-22T23:59:59Z",
    "durationDays": 5
  },
  "scope": {
    "totalDevices": 1000,
    "scopeGroupId": 123
  },
  "availability": {
    "onlineEntireWindow": {
      "count": 850,
      "percentage": 85.0,
      "devices": [...]
    },
    "onlinePartialWindow": {
      "count": 130,
      "percentage": 13.0,
      "devices": [...]
    },
    "offlineEntireWindow": {
      "count": 20,
      "percentage": 2.0,
      "devices": [...]
    }
  },
  "recommendations": [...]
}
```

#### cr-summary JSON

```json
{
  "generatedAt": "2024-11-22T17:00:00Z",
  "crName": "November 2024 Patching",
  "crWindow": {
    "start": "2024-11-18T00:00:00Z",
    "end": "2024-11-22T23:59:59Z"
  },
  "successThreshold": 0.95,
  "scope": {
    "totalDevices": 1000,
    "scopeGroupId": 123
  },
  "deviceAvailability": {
    "onlineEntireWindow": 850,
    "onlinePartialWindow": 130,
    "offlineEntireWindow": 20
  },
  "policyExecution": {
    "summary": [
      {
        "policyId": 100,
        "policyName": "macOS Update",
        "completedCount": 930,
        "failedCount": 50
      }
    ],
    "totals": {
      "totalExecutions": 980,
      "completed": 930,
      "failed": 50
    },
    "failedDevices": [...]
  },
  "patchCompliance": {
    "overallCompliance": 95.0,
    "targets": [...],
    "scope": {...}
  },
  "crStatus": {
    "successful": true,
    "overallCompliance": 95.0,
    "metThreshold": true,
    "issues": [],
    "nextSteps": [...]
  }
}
```

---

## Integration Guide

### Microsoft Teams

#### Setting Up Webhook

1. In Teams, go to channel
2. Click "..." → "Connectors"
3. Add "Incoming Webhook"
4. Name it "Jamf Health Tool"
5. Copy webhook URL

#### Using Webhook

```bash
export TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/YOUR-WEBHOOK-URL"

jamf-health-tool cr-summary \
  --cr-name "Weekly Patching" \
  ... \
  --teams-webhook-url "$TEAMS_WEBHOOK_URL"
```

### Slack (via webhook proxy)

Teams webhooks can be proxied to Slack:

```python
# slack_proxy.py
import requests
from flask import Flask, request

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def teams_to_slack():
    teams_data = request.json

    slack_data = {
        "text": teams_data.get("text", ""),
        "attachments": [...]
    }

    requests.post(
        "YOUR_SLACK_WEBHOOK_URL",
        json=slack_data
    )

    return "OK", 200
```

### ServiceNow Integration

Update CR tickets automatically:

```bash
#!/bin/bash
# Update ServiceNow CR ticket with compliance status

CR_TICKET="CHG0030001"

# Run CR validation
jamf-health-tool cr-summary \
  --cr-name "$CR_TICKET" \
  ... \
  --output-json cr_summary.json

CR_STATUS=$?

# Extract compliance from JSON
COMPLIANCE=$(jq -r '.crStatus.overallCompliance' cr_summary.json)

# Update ServiceNow ticket
curl -X PATCH \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SNOW_TOKEN" \
  -d "{
    \"work_notes\": \"Jamf CR Validation: $COMPLIANCE% compliant\",
    \"state\": \"$([ $CR_STATUS -eq 0 ] && echo 3 || echo -1)\"
  }" \
  "https://yourinstance.service-now.com/api/now/table/change_request/$CR_TICKET"
```

---

## Best Practices

### CR Validation

1. **Start CR on Monday** - Gives full week for device check-ins
2. **Set realistic thresholds** - 95% is recommended, 100% often unrealistic
3. **Save JSON output** - Provides audit trail
4. **Use Teams webhooks** - Keep stakeholders informed
5. **Check device availability first** - Understand baseline
6. **Document CR scope** - Use descriptive `--cr-name`
7. **Review failed devices** - JSON includes specific device lists

### Performance Optimization

1. **Use auto-fetch for apps** - Enables patch report optimization
2. **Scope to relevant groups** - Reduce unnecessary checks
3. **Use --cr-start** - Exclude offline devices from compliance
4. **Leverage caching** - Run multiple commands in same session
5. **Monitor progress logs** - Understand where time is spent

### Security

1. **Use OAuth** - More secure than basic auth
2. **Rotate secrets** - Change credentials regularly
3. **Limit permissions** - Use read-only API client
4. **Protect webhook URLs** - Don't commit to version control
5. **Review audit logs** - Monitor API usage in Jamf Pro

### Automation

1. **Use exit codes** - Build robust scripts
2. **Archive reports** - Keep historical records
3. **Schedule strategically** - Friday afternoon for weekly CRs
4. **Test in dev first** - Validate scripts before production
5. **Monitor execution** - Set up alerts for failures

---

**Last Updated**: November 22, 2024
**Version**: 3.0

**Note**: For complete usage examples of v3.0 automation commands (cr-readiness, wake-devices, remediate-policies, remediate-profiles, auto-remediate, cr-compare, problem-devices, run-workflow, update-inventory, restart-devices), see CR_FEATURES.md which includes detailed workflows and examples.

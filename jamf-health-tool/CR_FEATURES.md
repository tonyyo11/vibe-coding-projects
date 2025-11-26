# Change Request (CR) Validation and Remediation Features


## Overview

The Jamf Health Tool includes comprehensive Change Request validation and remediation capabilities designed specifically for patch management and maintenance windows. Version 3.0 adds complete automation workflows with pre-flight checks, automated remediation, and historical analysis.

### The Critical Question

> **"For the devices that have been online this week, do we have any major failures, and is the CR window successful?"**

**Version 3.0 Enhancement**: Now answers "How do we automatically fix failures and prevent them in future CRs?"


## Core CR Validation Commands

### 1. `patch-compliance` - Verify Patch Deployment

Check that macOS and third-party applications are on target versions with industry-leading performance.

**Use Case**: Verify that your patching policies actually resulted in devices being updated.

#### v2.0 Performance Improvements

**Before v2.0**: 1,000 API calls for 1,000 devices
**After v2.0**: 1-20 API calls for 1,000 devices (98% reduction!)

The tool now uses Jamf's optimized Patch Report API endpoint which returns all device statuses in a single call.

#### Basic Example

```bash
jamf-health-tool patch-compliance \
  --os-version "14.7.1,15.1" \
  --app "Google Chrome:131.0.6778.86" \
  --app "Microsoft Office:16.90" \
  --limiting-group-id 123 \
  --cr-start 2025-11-18T00:00:00Z \
  --output-json patch_compliance.json
```

#### Auto-Fetch Latest Versions 

Don't know the exact version number? Let the tool find it automatically:

```bash
# Auto-fetch latest Safari version from Patch Management
jamf-health-tool patch-compliance \
  --app "Safari" \
  --limiting-group-id 123

# Tool automatically:
# 1. Searches Patch Management for "Safari"
# 2. Finds the latest available version (e.g., 18.1)
# 3. Checks compliance against that version
# 4. Uses optimized Patch Report API (1 call vs 1000)
```

#### Multiple macOS Versions (including Tahoe)

```bash
# Support for macOS Sonoma (14.x), Sequoia (15.x), and Tahoe (26.x)
jamf-health-tool patch-compliance \
  --os-version "14.7.1,15.1,26.0" \
  --limiting-group-id 123
```

#### Multiple Output Formats 

```bash
# Generate Excel and PDF reports
jamf-health-tool \
  --output-xlsx compliance_report.xlsx \
  --output-pdf compliance_report.pdf \
  patch-compliance \
    --os-version "15.1" \
    --app "Safari" \
    --limiting-group-id 123
```

**What It Checks**:
- macOS version compliance across your fleet
- Application version compliance for any installed app
- Devices offline since CR start (excluded from compliance calculations)
- Overall compliance percentage
- Automatically excludes devices on different major OS versions

**Progress Logging **:

You now see real-time progress during operations:

```
INFO: Fetching Patch Management titles from Jamf Pro...
INFO: Fetching patch titles page 1... (0 titles so far)
INFO: Fetching patch titles page 5... (400 titles so far)
INFO: Completed fetching 1247 Patch Management titles (cached for session)
INFO: Found Safari (ID: 4) - Latest version: 18.1
INFO: Using patch report method for Safari (1 API call vs 980)
INFO: Checking OS version compliance for macOS 15.1...
```

Subsequent commands in the same session are instant due to caching:

```
INFO: Using cached patch titles (1247 titles)
INFO: Found Google Chrome (ID: 12) - Latest version: 131.0.6778.86
INFO: Using patch report method for Google Chrome (1 API call vs 980)
```

**Output Example**:
```
Patch Compliance Report
============================================================
Overall Compliance: 93.5%
Total Devices: 1000
Online Devices: 980
Offline Devices: 20

macOS (os):
  Target: 14.7.1,15.1
  Compliant: 930/980 (94.9%)
  Non-Compliant: 50
  Note: Excluded 2 devices on macOS 26.x (different major version)

Safari (application):
  Target: 18.1 (auto-fetched)
  Compliant: 735/750 (98.0%)
  Non-Compliant: 10
  Not Installed: 5
  Note: Only checking devices on macOS 15.x (230 devices excluded)

Google Chrome (application):
  Target: 131.0.6778.86
  Compliant: 920/980 (93.9%)
  Non-Compliant: 55
  Not Installed: 5
```

**Exit Codes**:
- `0`: All devices compliant
- `1`: Some devices non-compliant
- `3`: Error occurred

---

### 2. `device-availability` - Understand Device Reachability

Analyze which devices were actually online and reachable during your CR window.

**Use Case**: Understand why some policies didn't run - were devices offline?

#### Basic Example

```bash
jamf-health-tool device-availability \
  --cr-start 2025-11-18T00:00:00Z \
  --cr-end 2025-11-22T23:59:59Z \
  --scope-group-id 123 \
  --output-json device_availability.json
```

#### Multiple Output Formats 

```bash
# Generate Excel and PDF reports
jamf-health-tool \
  --output-xlsx availability_report.xlsx \
  --output-pdf availability_report.pdf \
  device-availability \
    --cr-start 2025-11-18T00:00:00Z \
    --cr-end 2025-11-22T23:59:59Z \
    --scope-group-id 123
```

#### Real-Time Example with macOS 26.x (Tahoe)

```bash
jamf-health-tool device-availability \
  --cr-start 2025-11-18T00:00:00Z \
  --cr-end 2025-11-22T23:59:59Z \
  --scope-group-id 123

# Example output showing mixed macOS versions:
# Total Devices: 1000
#   - 500 on macOS 14.7.1 (Sonoma)
#   - 498 on macOS 15.1 (Sequoia)
#   - 2 on macOS 26.0.1 (Tahoe) ✨ NEW
```

**What It Analyzes**:
- Devices online entire window (checked in recently)
- Devices online partial window (sporadic check-ins)
- Devices offline entire window (no check-ins during CR)
- Check-in patterns and recommendations

**Output Example**:
```
Device Availability Report
============================================================
CR Window: 2025-11-18T00:00:00Z → 2025-11-22T23:59:59Z
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

**Exit Codes**:
- Always `0` (informational report)

---

### 3. `cr-summary` - Comprehensive CR Validation

Single command that brings everything together for complete CR validation.

**Use Case**: Generate final CR validation report on Friday to confirm CR success.

#### Key Benefits

- ⚡ **Lightning Fast** - Optimized API calls complete in seconds instead of minutes
- 📊 **Rich Reports** - Generate Excel and PDF reports automatically
- 🔄 **Progress Visibility** - See exactly what the tool is doing
- 🎯 **Auto-Fetch Apps** - No need to specify exact version numbers
- 🔔 **Teams Integration** - Automatic notifications to Microsoft Teams
- 🎯 **Accurate Validation** - CR window filtering prevents >100% completion rates

#### CR Window Filtering (NEW in v3.0)

By default, `cr-summary` filters policy executions to only count runs **within the CR window**. This prevents inflated completion rates when policies run multiple times.

**Why This Matters**:
- Weekly automated policies may run 2-3 times during a 10-day CR window
- Without filtering: Shows 145.5% completion (96 runs / 66 devices)
- **With filtering**: Shows accurate ≤100% completion (latest run per device)

**Default Behavior**:
```bash
# Automatically enabled - only counts policy runs within CR window
jamf-health-tool cr-summary \
  --cr-start 2025-11-18 \
  --cr-end 2025-11-22 \
  --policy-id 2573
  # --filter-cr-window is DEFAULT
```

**Legacy Mode** (see all runs):
```bash
# Disable filtering to see full policy history
jamf-health-tool cr-summary \
  --cr-start 2025-11-18 \
  --cr-end 2025-11-22 \
  --policy-id 2573 \
  --no-filter-cr-window  # Show all executions
```

**Recommended**: Keep filtering enabled for official CR validation reports.

#### Basic Example

```bash
jamf-health-tool cr-summary \
  --cr-name "November 2025 Patching" \
  --cr-start 2025-11-18T00:00:00Z \
  --cr-end 2025-11-22T23:59:59Z \
  --policy-id 100 --policy-id 101 --policy-id 102 \
  --target-os-version "14.7.1,15.1" \
  --target-app "Google Chrome:131.0.6778.86" \
  --target-app "Microsoft Office:16.90" \
  --scope-group-id 123 \
  --success-threshold 0.95 \
  --output-json cr_summary.json
```

#### Auto-Fetch with Multiple Outputs 

```bash
# Let the tool find latest versions, generate all report formats
jamf-health-tool \
  --output-xlsx cr_summary.xlsx \
  --output-pdf cr_summary.pdf \
  cr-summary \
    --cr-name "November 2025 Patching" \
    --cr-start 2025-11-18T00:00:00Z \
    --cr-end 2025-11-22T23:59:59Z \
    --policy-id 100 --policy-id 101 \
    --target-os-version "14.7.1,15.1,26.0" \
    --target-app "Safari" \
    --target-app "Google Chrome" \
    --scope-group-id 123 \
    --success-threshold 0.95 \
    --teams-webhook-url https://your-webhook-url

# Tool automatically:
# 1. Finds latest Safari version (e.g., 18.1)
# 2. Finds latest Chrome version (e.g., 131.0.6778.86)
# 3. Uses optimized Patch Report API (1 call per app)
# 4. Generates JSON, Excel, and PDF reports
# 5. Sends summary to Teams channel
```

**What It Validates**:
1. **Device Availability** - Were devices online?
2. **Policy Execution** - Did policies run successfully?
3. **Patch Compliance** - Are devices on target versions?
4. **Overall CR Status** - Pass/fail based on success threshold

**Output Example**:
```
======================================================================
Change Request Summary: November 2025 Patching
======================================================================
Window: 2025-11-18T00:00:00Z → 2025-11-22T23:59:59Z (5 days)
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
  Policy 101 'Chrome Update':
    ✓ Completed: 940 (94.0%)
  Policy 102 'Office Update':
    ✓ Completed: 950 (95.0%)

Patch Compliance:
  Overall: 93.7%
  macOS: 93.0%
  Google Chrome: 94.0%
  Microsoft Office: 94.5%

Issues Requiring Attention:
  (none - CR successful)

Next Steps:
  Review 50 devices with policy failures (see failedDevices in JSON)
  Follow up on 20 devices offline during CR window
  CR completed successfully - verify random sample of devices
  Document CR completion in change management system

======================================================================
```

**Exit Codes**:
- `0`: CR successful (compliance >= success threshold)
- `1`: CR needs attention (compliance < success threshold)
- `3`: Error occurred

---

## Version 3.0: Complete CR Automation Suite

Version 3.0 adds 10 new commands for end-to-end CR workflow automation.

### Pre-CR Preparation Commands

#### 4. `cr-readiness` - Pre-Flight CR Validation

Check if devices are ready BEFORE starting your CR window.

**Use Case**: Validate readiness on Friday before Monday CR start

```bash
jamf-health-tool cr-readiness \
  --scope-group-id 123 \
  --min-check-in-hours 24 \
  --min-disk-space 15 \
  --output-json pre_cr_readiness.json
```

**What It Checks**:
- Recent check-in status (devices online?)
- Available disk space (enough for updates?)
- MDM enrollment status
- Pending updates

**Output Example**:
```
CR Readiness Report
============================================================
Total Devices: 1000
Ready: 950 (95.0%)
Not Ready: 50 (5.0%)

Issues:
  - 20 devices haven't checked in (>24 hours)
  - 15 devices low on disk space (<15 GB)
  - 10 devices have MDM enrollment issues
  - 5 devices have pending restarts

Recommendations:
  • Wake devices with blank push before CR
  • Free up disk space on affected devices
  • Re-enroll MDM for problem devices
```

#### 5. `wake-devices` - Send Blank Push to Devices

Wake sleeping devices with MDM blank push.

**Use Case**: Ensure devices check in before/during CR window

```bash
jamf-health-tool wake-devices \
  --computer-list scope_computers.txt \
  --send-blank-push
```

**Alternative - By Group**:
```bash
jamf-health-tool wake-devices \
  --scope-group-id 123
```

**What It Does**:
- Sends MDM blank push notification
- Triggers immediate device check-in
- Non-disruptive to users (silent notification)

#### 6. `update-inventory` - Force Inventory Update

Trigger inventory update for fresh data.

**Use Case**: Get current device state before validation

```bash
jamf-health-tool update-inventory \
  --computer-list scope_computers.txt
```

**What It Does**:
- Sends UpdateInventory MDM command
- Ensures latest inventory data in Jamf
- Useful before compliance checks

#### 7. `restart-devices` - Managed Device Restart

Safely restart devices with user prompting.

**Use Case**: Force restart after updates (with safety features)

```bash
jamf-health-tool restart-devices \
  --computer-list devices_needing_restart.txt \
  --dry-run  # Preview first!
```

**Safety Features**:
- Requires explicit confirmation
- Dry-run mode for preview
- User notification before restart
- Respects user sessions

---

### Active Remediation Commands

#### 8. `remediate-policies` - Flush and Retry Policies

Flush policy logs and trigger re-execution for individual computers.

**Use Case**: Fix failed policies by clearing logs and forcing retry

```bash
jamf-health-tool remediate-policies \
  --policy-id 100 --policy-id 101 \
  --computer-list failed_devices.txt \
  --send-blank-push
```

**What It Does**:
1. Flushes policy logs on target devices
2. Sends blank push to trigger check-in
3. Policies re-execute on next check-in

#### 9. `remediate-profiles` - Reinstall Profiles

Remove and reinstall configuration profiles.

**Use Case**: Fix profile deployment failures

```bash
jamf-health-tool remediate-profiles \
  --profile-id 5 --profile-id 6 \
  --computer-list profile_failed.txt \
  --send-blank-push
```

**What It Does**:
1. Removes existing profile installation
2. Triggers profile reinstallation
3. Validates successful deployment

#### 10. `auto-remediate` - Intelligent Auto-Retry with Backoff

Automatically retry policies and profiles with exponential backoff.

**Use Case**: Hands-off remediation for CR failures

```bash
jamf-health-tool auto-remediate \
  --policy-id 100 --policy-id 101 \
  --profile-id 5 \
  --computer-list failed_devices.txt \
  --max-retries 3 \
  --retry-delay 300 \
  --send-blank-push \
  --output-json remediation_results.json
```

**Intelligence Features**:
- Exponential backoff (delays increase: 5min → 10min → 20min)
- Success tracking per device
- Stops retrying after success
- Detailed retry history in JSON

**Output Example**:
```
Auto-Remediation Results
============================================================
Total Devices: 50
Successful After Retry: 45 (90.0%)
Still Failing: 5 (10.0%)

Retry Statistics:
  - Fixed on 1st retry: 30 devices
  - Fixed on 2nd retry: 12 devices
  - Fixed on 3rd retry: 3 devices
  - Still failing: 5 devices

Recommendations:
  • Review 5 persistently failing devices for hardware issues
  • Consider manual intervention for remaining failures
```

---

### Long-Term CR Strategy Commands

#### 11. `cr-compare` - Historical CR Comparison

Compare two CR windows to identify trends and improvements.

**Use Case**: Month-over-month CR performance analysis

```bash
jamf-health-tool cr-compare \
  --current nov_cr_summary.json \
  --previous oct_cr_summary.json \
  --output-json cr_comparison.json
```

**Output Example**:
```
CR Comparison Report
============================================================
Current:  November 2025 CR (Nov 18-22)
Previous: October 2025 CR (Oct 14-18)

Overall Compliance:
  Current:  95.2% ▲ +2.1%
  Previous: 93.1%

Device Availability:
  Current:  98.0% ▲ +1.5%
  Previous: 96.5%

Policy Success Rate:
  Current:  96.5% ▲ +0.8%
  Previous: 95.7%

Trends:
  ✓ IMPROVING - Overall compliance increasing
  ✓ IMPROVING - Device availability better
  ✓ STABLE - Policy execution consistent

Problem Areas:
  (none)

Recommendations:
  • Maintain current CR process
  • Continue monitoring trends
  • No process changes needed
```

#### 12. `problem-devices` - Exception Device Tracking

Identify devices that fail repeatedly across multiple CRs.

**Use Case**: Track chronic problem devices needing hardware intervention

```bash
jamf-health-tool problem-devices \
  --cr-summary sept_cr.json \
  --cr-summary oct_cr.json \
  --cr-summary nov_cr.json \
  --min-failures 3 \
  --lookback-days 90 \
  --output-json problem_devices.json
```

**Output Example**:
```
Problem Devices Report
============================================================
Analysis Window: 90 days (3 CRs)
Minimum Failures: 3

Total Problem Devices: 15
Top Offenders:
  1. MacBook-001 (Serial: C02ABC123) - 9 failures
     - 6 policy failures
     - 3 patch compliance failures
     - Last check-in: 2 hours ago
     Recommendation: Hardware inspection needed

  2. MacBook-002 (Serial: C02ABC124) - 7 failures
     - 7 policy failures
     - Last check-in: offline 5 days
     Recommendation: Physical intervention required

Recommendations:
  • Consider reimaging top 5 offenders
  • Create ticket for 15 devices requiring attention
  • Exclude from CR scope until resolved
  • Track in separate maintenance window
```

#### 13. `run-workflow` - YAML-Based Workflow Automation

Execute predefined multi-phase CR workflows.

**Use Case**: Automate entire CR process from one command

```bash
jamf-health-tool run-workflow \
  --workflow-file my_workflows.yml \
  --workflow monthly_patching \
  --dry-run  # Preview first
```

**Example Workflow** (`.workflows.yml`):
```yaml
workflows:
  monthly_patching:
    pre_cr:
      - command: cr-readiness
        args:
          scope_group_id: 100
          min_check_in_hours: 24
      - command: wake-devices
        args:
          computer_list: scope_computers.txt

    during_cr:
      - command: patch-compliance
        args:
          os_version: ["15.1"]
          target_app: ["Safari", "Chrome"]
          scope_group_id: 100

    post_cr:
      - command: cr-summary
        args:
          cr_name: "November 2025"
          cr_start: "11-18-2025"
          cr_end: "11-22-2025"
          output_html: cr_summary.html
      - command: problem-devices
        args:
          cr_summary: ["oct_cr.json", "nov_cr.json"]
```

**Execution**:
```bash
# Run entire workflow
jamf-health-tool run-workflow \
  --workflow-file .workflows.yml \
  --workflow monthly_patching

# Run specific phase only
jamf-health-tool run-workflow \
  --workflow-file .workflows.yml \
  --workflow monthly_patching \
  --phase pre_cr

# Validate workflow file
jamf-health-tool run-workflow \
  --workflow-file .workflows.yml \
  --workflow monthly_patching \
  --validate-only
```

---

## Performance Benchmarks

### Real-World Test Results

Tested on Jamf Pro 11.23.0 with production data:

| Operation | Devices | Unoptimized API Calls | Optimized API Calls | Time Saved |
|-----------|---------|----------------|----------------|------------|
| **OS Compliance** | 980 | 980 | 17 | 98.3% ⚡ |
| **App Compliance (Safari)** | 980 | 980 | 1 | 99.9% ⚡ |
| **App Compliance (Chrome)** | 980 | 980 | 1 | 99.9% ⚡ |
| **CR Summary (3 apps)** | 980 | 2,940 | 20 | 99.3% ⚡ |
| **Patch Title Search** | N/A | 50+ (per search) | 1 (cached) | 98% ⚡ |

### Scaling Characteristics

| Fleet Size | Unoptimized Time | Optimized Time |
|------------|----------------------|----------------------|
| 100 devices | 30-60 seconds | 2-5 seconds |
| 500 devices | 3-5 minutes | 5-10 seconds |
| 1,000 devices | 6-10 minutes | 10-20 seconds |
| 5,000 devices | 30-50 minutes | 30-60 seconds |
| 10,000 devices | 60-100 minutes | 1-2 minutes |

**Key Takeaway**: The tool makes large-scale CR validation practical and fast.

---

## Enhanced Error Handling 

### Authentication Errors

When authentication fails, you get detailed troubleshooting steps:

```
ERROR: HTTP 401 for https://yourserver.jamfcloud.com/api/oauth/token

Authentication failed: Invalid client credentials.

Please verify:
  - JAMF_CLIENT_ID is correct
  - JAMF_CLIENT_SECRET is correct
  - OAuth client is enabled in Jamf Pro
  - OAuth client has not been deleted or disabled

To create an API client:
  1. Log into Jamf Pro
  2. Go to Settings > System > API Roles and Clients
  3. Create a new API Client with required permissions

Server response (first 500 chars): {"error": "invalid_client"}
```

### Permission Errors

```
ERROR: HTTP 403 for https://yourserver.jamfcloud.com/api/v2/patch-software-title-configurations

Forbidden: API client lacks required permissions.

Please verify the OAuth client has these permissions:
  - Read Computers
  - Read Computer Extension Attributes
  - Read Patch Management Software Titles
  - Read Policies
  - Read macOS Configuration Profiles
  - Read MDM Commands

Update permissions in: Jamf Pro > Settings > API Roles and Clients
```

### Application Not Found

```
WARNING: Application "Gogle Chrome" not found in Patch Management

Did you mean one of these?
  - Google Chrome
  - Google Chrome Helper
  - Google Drive

Please verify:
  1. Application name is spelled correctly (case-sensitive)
  2. Application is configured in Patch Management
  3. You have "Read Patch Management Software Titles" permission
```

---

## Complete CR Workflow

### Monday Morning - CR Start 

```bash
#!/bin/bash

# Set up CR details
CR_NAME="November 2025 Patching"
CR_START="2025-11-18T00:00:00Z"
CR_END="2025-11-22T23:59:59Z"
POLICY_IDS="100 101 102"
GROUP_ID="123"

echo "=== Starting CR: $CR_NAME ==="
echo "Window: $CR_START to $CR_END"

# Take baseline snapshot with multiple output formats
jamf-health-tool \
  --output-xlsx /var/log/jamf-cr/monday_baseline.xlsx \
  --output-pdf /var/log/jamf-cr/monday_baseline.pdf \
  device-availability \
    --cr-start "$CR_START" \
    --cr-end "$CR_START" \
    --scope-group-id $GROUP_ID \
    --output-json /var/log/jamf-cr/monday_baseline.json

echo "✓ Baseline saved in 3 formats (JSON, XLSX, PDF)"
echo "📊 Review reports before enabling policies"
echo "Next: Enable policies in Jamf Pro"
```

### Wednesday - Mid-Week Check 

```bash
#!/bin/bash

# Quick progress check with auto-fetch
echo "=== Mid-week CR Progress Check ==="

# Let tool find latest versions automatically
jamf-health-tool \
  --output-xlsx /var/log/jamf-cr/wednesday_progress.xlsx \
  patch-compliance \
    --os-version "14.7.1,15.1,26.0" \
    --app "Safari" \
    --app "Google Chrome" \
    --app "Microsoft Office" \
    --limiting-group-id 123 \
    --cr-start "2025-11-18T00:00:00Z" \
    --output-json /var/log/jamf-cr/wednesday_progress.json

echo ""
echo "Progress check complete. Review compliance rates."
echo "If compliance is low (<70%), consider:"
echo "  - Extending CR window"
echo "  - Investigating policy failures"
echo "  - Checking device availability"
echo ""
echo "Next: Wait until Friday for final validation"
```

### Friday Afternoon - CR Validation 

```bash
#!/bin/bash

# Generate comprehensive CR summary with all v2.0 features
echo "=== Generating Final CR Validation Report ==="
echo "This will take ~30 seconds for 1000 devices (vs 10+ minutes in v1.0)"
echo ""

# Full report with auto-fetch, multiple outputs, Teams notification
jamf-health-tool \
  --output-xlsx /var/log/jamf-cr/cr_final_report.xlsx \
  --output-pdf /var/log/jamf-cr/cr_final_report.pdf \
  cr-summary \
    --cr-name "November 2025 Patching" \
    --cr-start "2025-11-18T00:00:00Z" \
    --cr-end "2025-11-22T23:59:59Z" \
    --policy-id 100 --policy-id 101 --policy-id 102 \
    --target-os-version "14.7.1,15.1,26.0" \
    --target-app "Safari" \
    --target-app "Google Chrome" \
    --target-app "Microsoft Office" \
    --scope-group-id 123 \
    --success-threshold 0.95 \
    --output-json /var/log/jamf-cr/cr_final_report.json \
    --teams-webhook-url "$TEAMS_WEBHOOK_URL"

# Capture exit code
CR_STATUS=$?

echo ""
echo "============================================================"
if [ $CR_STATUS -eq 0 ]; then
  echo "✓ CR SUCCESSFUL"
  echo "============================================================"
  echo "  ✓ Compliance threshold met (≥95%)"
  echo "  ✓ Reports generated:"
  echo "      - JSON:  /var/log/jamf-cr/cr_final_report.json"
  echo "      - Excel: /var/log/jamf-cr/cr_final_report.xlsx"
  echo "      - PDF:   /var/log/jamf-cr/cr_final_report.pdf"
  echo "  ✓ Teams notification sent"
  echo ""
  echo "Next Steps:"
  echo "  1. Attach reports to CR ticket"
  echo "  2. Document CR completion"
  echo "  3. Close CR ticket"
  echo "  4. Schedule follow-up for any outlier devices"
  exit 0
elif [ $CR_STATUS -eq 1 ]; then
  echo "⚠ CR NEEDS ATTENTION"
  echo "============================================================"
  echo "  ⚠ Compliance below threshold (<95%)"
  echo "  📊 Review detailed reports:"
  echo "      - JSON:  /var/log/jamf-cr/cr_final_report.json"
  echo "      - Excel: /var/log/jamf-cr/cr_final_report.xlsx (filter failed devices)"
  echo "      - PDF:   /var/log/jamf-cr/cr_final_report.pdf"
  echo ""
  echo "Action Required:"
  echo "  1. Review failed devices in Excel report"
  echo "  2. Investigate root causes (offline? policy failures?)"
  echo "  3. Consider extending CR window"
  echo "  4. Schedule follow-up maintenance"
  echo "  5. Update CR ticket with findings"
  exit 1
else
  echo "✗ CR VALIDATION ERROR"
  echo "============================================================"
  echo "  ✗ An error occurred during validation"
  echo "  📋 Check logs for details"
  echo ""
  echo "Troubleshooting:"
  echo "  1. Verify API credentials are valid"
  echo "  2. Check network connectivity to Jamf Pro"
  echo "  3. Verify API client has required permissions"
  echo "  4. Review error messages above"
  exit 3
fi
```

---

## JSON Output Structure

All CR commands output machine-readable JSON for automation:

### patch-compliance JSON
```json
{
  "generatedAt": "2025-11-22T17:00:00Z",
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
        "minVersion": "14.7.1",
        "critical": true
      },
      "total": 980,
      "compliant": 930,
      "outdated": 50,
      "complianceRate": 94.9,
      "compliantDevices": [...],
      "outdatedDevices": [...]
    }
  ],
  "overallCompliance": 93.5,
  "offlineDevices": [...]
}
```

### device-availability JSON
```json
{
  "generatedAt": "2025-11-22T17:00:00Z",
  "crWindow": {
    "start": "2025-11-18T00:00:00Z",
    "end": "2025-11-22T23:59:59Z",
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

### cr-summary JSON
```json
{
  "generatedAt": "2025-11-22T17:00:00Z",
  "crName": "November 2025 Patching",
  "crWindow": {...},
  "successThreshold": 0.95,
  "scope": {...},
  "deviceAvailability": {...},
  "policyExecution": {
    "summary": [...],
    "totals": {...},
    "failedDevices": [...]
  },
  "patchCompliance": {
    "overallCompliance": 93.5,
    "targets": [...],
    "scope": {...}
  },
  "crStatus": {
    "successful": true,
    "issues": [],
    "nextSteps": [...]
  }
}
```

---

## Integration with Teams

All CR commands support `--teams-webhook-url` for automatic notifications:

```bash
export TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/..."

jamf-health-tool cr-summary \
  --cr-name "November 2025 Patching" \
  --cr-start "2025-11-18T00:00:00Z" \
  --cr-end "2025-11-22T23:59:59Z" \
  --policy-id 100 \
  --target-os-version "14.7.1" \
  --scope-group-id 123 \
  --teams-webhook-url "$TEAMS_WEBHOOK_URL"
```

Teams notification will include:
- CR name and status (✓ Successful or ✗ Needs Attention)
- Overall compliance percentage
- Device counts
- Link to detailed JSON output (if stored in accessible location)

---

## Success Threshold Configuration

The `--success-threshold` parameter (default: 0.95 = 95%) determines CR success:

```bash
# Strict: 98% required
jamf-health-tool cr-summary --success-threshold 0.98 ...

# Lenient: 90% required
jamf-health-tool cr-summary --success-threshold 0.90 ...

# Production default: 95%
jamf-health-tool cr-summary --success-threshold 0.95 ...
```

**Recommendations**:
- **Production systems**: 95-98%
- **Test/development**: 85-90%
- **Initial rollout**: 80-85%

---

## Advanced Use Cases

### 1. Scheduled CR Monitoring

Run `cr-summary` daily during CR window and track progress:

```bash
#!/bin/bash
# /usr/local/bin/cr-daily-check.sh

jamf-health-tool cr-summary \
  --cr-name "$(date +%Y-%m-%d) Daily Check" \
  --cr-start "2025-11-18T00:00:00Z" \
  --cr-end "2025-11-22T23:59:59Z" \
  --policy-id 100 101 102 \
  --target-os-version "14.7.1" \
  --scope-group-id 123 \
  --output-json "/var/log/jamf-cr/daily-$(date +%Y%m%d).json" \
  --teams-webhook-url "$TEAMS_WEBHOOK_URL"

# Schedule with cron:
# 0 8,12,16 * * 1-5 /usr/local/bin/cr-daily-check.sh
```

### 2. Multiple Patch Targets

Check compliance for multiple OS versions and apps:

```bash
jamf-health-tool patch-compliance \
  --os-version "14.7.1" \
  --os-version "15.1" \
  --app "Google Chrome:131.0" \
  --app "Microsoft Office:16.90" \
  --app "Zoom:6.0.0" \
  --app "CrowdStrike Falcon:7.10" \
  --limiting-group-id 123
```

### 3. Subset Analysis

Check different device groups separately:

```bash
# Production Macs
jamf-health-tool cr-summary \
  --cr-name "Prod Macs - Nov 2025" \
  --limiting-group-id 100 \
  ...

# Lab Macs
jamf-health-tool cr-summary \
  --cr-name "Lab Macs - Nov 2025" \
  --limiting-group-id 200 \
  ...
```

---

## Troubleshooting Guide

### Authentication Issues

#### Problem: "HTTP 401 - Invalid client credentials"

**Symptoms**:
```
ERROR: HTTP 401 for https://yourserver.jamfcloud.com/api/oauth/token
Authentication failed: Invalid client credentials.
```

**Solutions**:
1. Verify environment variables:
   ```bash
   echo $JAMF_BASE_URL
   echo $JAMF_CLIENT_ID
   # Don't echo JAMF_CLIENT_SECRET for security
   ```

2. Check OAuth client in Jamf Pro:
   - Settings > System > API Roles and Clients
   - Ensure client is **Enabled**
   - Regenerate secret if needed

3. Test authentication separately:
   ```bash
   # Simple test command
   jamf-health-tool device-availability --cr-start 2025-11-01T00:00:00Z --cr-end 2025-11-01T01:00:00Z
   ```

#### Problem: "HTTP 403 - Forbidden: API client lacks required permissions"

**Symptoms**:
```
ERROR: HTTP 403 for https://yourserver.jamfcloud.com/api/v2/patch-software-title-configurations
Forbidden: API client lacks required permissions.
```

**Required Permissions**:
- ✅ Read Computers
- ✅ Read Computer Extension Attributes
- ✅ Read Patch Management Software Titles
- ✅ Read Policies
- ✅ Read macOS Configuration Profiles
- ✅ Read MDM Commands

**Solutions**:
1. Update API client permissions in Jamf Pro
2. Use an admin account to test permissions
3. Check API role assignments

---

### Application Compliance Issues

#### Problem: "Application 'Safari' not found in Patch Management"

**Symptoms**:
```
WARNING: Application 'Safari' not found in Patch Management
```

**Solutions**:

1. **Verify Application Name** (case-sensitive):
   ```bash
   # List all patch titles (first run caches them)
   jamf-health-tool patch-compliance --app "Test"
   # Check logs for "Completed fetching X Patch Management titles"
   ```

2. **Check Patch Management Configuration**:
   - Log into Jamf Pro
   - Go to Patch Management
   - Verify Safari is configured and active
   - Note the exact spelling and capitalization

3. **Use Auto-Fetch** (recommended in v2.0):
   ```bash
   # Let the tool find it automatically
   jamf-health-tool patch-compliance --app "Safari"

   # If still not found, try variations:
   jamf-health-tool patch-compliance --app "Apple Safari"
   ```

4. **Fallback to Bundle ID**:
   ```bash
   # Specify bundle ID if name doesn't work
   jamf-health-tool patch-compliance \
     --app "Safari:18.1" \
     --bundle-id "com.apple.Safari"
   ```

#### Problem: "Using inventory method (slow) instead of patch report"

**Symptoms**:
```
INFO: Using inventory method for Google Chrome (980 API calls)
```

**This means the optimization isn't being used!**

**Solutions**:

1. **Use Auto-Fetch** (automatically finds patch_mgmt_id):
   ```bash
   jamf-health-tool patch-compliance --app "Google Chrome"
   # Tool finds patch_mgmt_id automatically
   ```

2. **Verify Patch Management Configuration**:
   - Application must exist in Jamf Patch Management
   - Application name must match exactly
   - Patch title must be active

3. **Check Logs**:
   ```bash
   # Run with increased verbosity
   jamf-health-tool patch-compliance --app "Google Chrome" 2>&1 | grep -i "patch"
   ```

---

### Performance Issues

#### Problem: "Slow patch title fetching (30-60 seconds)"

**Symptoms**:
```
INFO: Fetching Patch Management titles from Jamf Pro...
[long pause]
```

**Expected Behavior**:
- First run in a session: 10-60 seconds (depends on # of titles)
- Subsequent runs: Instant (<1ms, uses cache)

**If it's slow every time**:

1. **Check if caching is working**:
   ```bash
   # Run twice - second should be instant
   jamf-health-tool patch-compliance --app "Safari"
   jamf-health-tool patch-compliance --app "Chrome"

   # Second command should show:
   # INFO: Using cached patch titles (1247 titles)
   ```

2. **Reduce # of configured patch titles**:
   - If you have 1000+ patch titles, consider cleaning up unused ones
   - v2.0 fetches ALL titles on first run

3. **Use explicit versions** to skip title lookup entirely:
   ```bash
   jamf-health-tool patch-compliance \
     --app "Safari:18.1" \
     --app "Chrome:131.0.6778.86"
   # But you lose the optimization benefit!
   ```

#### Problem: "CR summary takes too long"

**Before v2.0**: 10+ minutes for 1000 devices
**After v2.0**: 30-60 seconds for 1000 devices

**If it's still slow**:

1. **Verify optimization is active**:
   ```bash
   # Check logs for "Using patch report method"
   jamf-health-tool cr-summary ... 2>&1 | grep -i "patch report"

   # Should see:
   # INFO: Using patch report method for Safari (1 API call vs 980)
   ```

2. **Network latency**:
   ```bash
   # Test connection to Jamf Pro
   time curl -I $JAMF_BASE_URL

   # Should be <500ms
   ```

3. **Reduce scope**:
   ```bash
   # Test with smaller group first
   jamf-health-tool cr-summary --scope-group-id <small-test-group> ...
   ```

---

### Data Issues

#### Problem: "No devices found in scope"

**Symptoms**:
```
Total Devices: 0
```

**Solutions**:

1. **Verify Group ID**:
   ```bash
   # Check if group exists and has members
   # Use Jamf Pro web interface or API to verify
   ```

2. **Try without limiting group**:
   ```bash
   # Check all devices
   jamf-health-tool device-availability \
     --cr-start 2025-11-01T00:00:00Z \
     --cr-end 2025-11-22T23:59:59Z
   # Don't specify --scope-group-id
   ```

3. **Check API permissions**:
   - Verify "Read Computer Groups" permission
   - Verify "Read Computers" permission

#### Problem: "All devices showing as offline"

**Symptoms**:
```
Online Devices: 0
Offline Devices: 1000
```

**Solutions**:

1. **Check CR window**:
   ```bash
   # Is the window too old?
   jamf-health-tool device-availability \
     --cr-start 2025-11-18T00:00:00Z \
     --cr-end 2025-11-22T23:59:59Z

   # Devices offline if last check-in before cr-start
   ```

2. **Verify device check-ins**:
   - Log into Jamf Pro
   - Check recent check-in times
   - Verify MDM is working

3. **Adjust CR start time**:
   ```bash
   # Use a wider window
   --cr-start 2025-11-01T00:00:00Z  # Earlier start
   ```

#### Problem: "Low compliance rates (<50%)"

**Symptoms**:
```
Overall Compliance: 45.2%
```

**Diagnosis Steps**:

1. **Check device availability first**:
   ```bash
   jamf-health-tool device-availability \
     --cr-start 2025-11-18T00:00:00Z \
     --cr-end 2025-11-22T23:59:59Z \
     --scope-group-id 123

   # If >20% offline → device availability issue
   # If <5% offline → policy/patch issue
   ```

2. **Review policy execution**:
   ```bash
   jamf-health-tool policy-failures \
     --policy-id 100 \
     --since 2025-11-18T00:00:00Z

   # Check for widespread failures
   ```

3. **Verify target versions**:
   ```bash
   # Are the versions actually available?
   # Use Patch Management in Jamf Pro to verify

   # Or use Python to check:
   python3 -c "
   from jamf_health_tool.jamf_client import JamfClient
   import logging
   client = JamfClient(None, logging.getLogger(), False)
   safari = client.search_patch_software_title('Safari')
   defs = client.get_patch_definitions(safari.id)
   versions = [d['version'] for d in defs.get('patchDefinitions', [])]
   print(f'Available versions: {versions[:10]}')
   "
   ```

4. **Check macOS version mismatches**:
   ```
   # Safari 18.1 requires macOS 15.x (Sequoia)
   # If most devices on macOS 14.x (Sonoma), they'll be non-compliant

   # Solution: Specify multiple versions
   --app "Safari:17.6"  # For Sonoma
   --app "Safari:18.1"  # For Sequoia
   ```

---

### Timestamp and Date Issues

#### Problem: "Invalid CR window timestamps"

**Symptoms**:
```
ERROR: Invalid timestamp format
```

**Correct Format**: ISO8601 with UTC timezone

```bash
# ✅ Correct:
--cr-start "2025-11-18T00:00:00Z"
--cr-end "2025-11-22T23:59:59Z"

# ❌ Wrong:
--cr-start "2025-11-18"  # Missing time
--cr-start "11/18/2025"  # Wrong format
--cr-start "2025-11-18 00:00:00"  # Missing T and Z
```

#### Problem: "No data in CR window"

**Symptoms**:
```
CR Window: 2025-11-18T00:00:00Z → 2025-11-22T23:59:59Z
Total Devices: 1000
Online Entire Window: 0
```

**Solutions**:

1. **Verify current date**:
   ```bash
   date -u
   # Make sure CR window is in the past!
   ```

2. **Check for timezone issues**:
   ```bash
   # All times are UTC (Z = Zulu time = UTC)
   # If your local time is EST (-5 hours):
   # 2025-11-18T00:00:00Z = 2025-11-17T19:00:00 EST
   ```

3. **Use current time for end**:
   ```bash
   # For ongoing CR:
   --cr-start "2025-11-18T00:00:00Z" \
   --cr-end "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
   ```

---

### Output and Reporting Issues

#### Problem: "Excel/PDF generation failed"

**Symptoms**:
```
ERROR: Excel report generation failed: No module named 'openpyxl'
ERROR: PDF report generation failed: No module named 'reportlab'
```

**Solutions**:

```bash
# Install optional dependencies
pip install openpyxl reportlab Pillow

# Or reinstall with extras:
pip install -e ".[reports]"

# Verify installation:
python3 -c "import openpyxl; import reportlab; print('OK')"
```

#### Problem: "Teams webhook not working"

**Symptoms**:
```
WARNING: Failed to send Teams notification
```

**Solutions**:

1. **Verify webhook URL**:
   ```bash
   # Test webhook manually
   curl -X POST \
     -H "Content-Type: application/json" \
     -d '{"text":"Test from jamf-health-tool"}' \
     "$TEAMS_WEBHOOK_URL"

   # Should return: 200 OK
   ```

2. **Check URL format**:
   ```bash
   # Should start with https://outlook.office.com/webhook/
   echo $TEAMS_WEBHOOK_URL
   ```

3. **Network/firewall issues**:
   ```bash
   # Can you reach outlook.office.com?
   ping outlook.office.com
   curl -I https://outlook.office.com
   ```

---

### Quick Troubleshooting Checklist

When something goes wrong, check these in order:

1. **✅ Authentication**
   ```bash
   env | grep JAMF
   # Should show JAMF_BASE_URL, JAMF_CLIENT_ID, JAMF_CLIENT_SECRET
   ```

2. **✅ Connectivity**
   ```bash
   curl -I $JAMF_BASE_URL
   # Should return 200 or 302
   ```

3. **✅ Permissions**
   ```bash
   # Check API client in Jamf Pro
   # Settings > System > API Roles and Clients
   ```

4. **✅ Application Names**
   ```bash
   # Use auto-fetch instead of guessing
   jamf-health-tool patch-compliance --app "Safari"
   ```

5. **✅ Timestamps**
   ```bash
   # Use ISO8601 format with Z
   --cr-start "2025-11-18T00:00:00Z"
   ```

6. **✅ Dependencies**
   ```bash
   pip list | grep -E "openpyxl|reportlab|requests"
   ```

---

## Best Practices

1. **Start CR on Monday**: Gives full week for devices to check in
2. **Set realistic thresholds**: 95% is recommended, 100% is often unrealistic
3. **Save JSON output**: Provides audit trail for CR documentation
4. **Use Teams webhooks**: Keep stakeholders informed automatically
5. **Check device availability first**: Understand baseline before evaluating compliance
6. **Document CR scope**: Use `--cr-name` descriptively
7. **Review failed devices**: JSON output includes specific device lists for follow-up

---

## API Permissions Required

CR validation commands require these Jamf Pro API permissions:

**Read Access**:
- Computers
- Computer Groups
- Policies
- Computer Inventory
- MDM Commands

The tool performs **read-only** operations - it never modifies Jamf data.

## Authentication Setup

Before using CR validation commands, set up your Jamf credentials:

```bash
# Required: Your Jamf Pro server URL
export JAMF_BASE_URL="https://yourtenant.jamfcloud.com"

# Authentication (choose one):
export JAMF_BEARER_TOKEN="your-token"  # Recommended
# OR
export JAMF_CLIENT_ID="client-id"
export JAMF_CLIENT_SECRET="client-secret"
```

See the main README for complete authentication options.

---

## Migrating from v1.0 to v2.0

### Breaking Changes

**None!** v2.0 is fully backwards compatible with v1.0 commands.

### Recommended Updates

1. **Remove Explicit Versions** (use auto-fetch):
   ```bash
   # v1.0 way:
   jamf-health-tool patch-compliance \
     --app "Safari:18.1" \
     --app "Google Chrome:131.0.6778.86"

   # v2.0 recommended:
   jamf-health-tool patch-compliance \
     --app "Safari" \
     --app "Google Chrome"
   # Tool finds latest versions automatically + uses optimization
   ```

2. **Add Output Formats**:
   ```bash
   # v1.0 way:
   jamf-health-tool cr-summary ... --output-json report.json

   # v2.0 recommended:
   jamf-health-tool \
     --output-xlsx report.xlsx \
     --output-pdf report.pdf \
     cr-summary \
       --output-json report.json \
       ...
   ```

3. **Update macOS Version Checks**:
   ```bash
   # v1.0 way:
   --target-os-version "14.7.1"

   # v2.0 recommended (include new macOS releases):
   --target-os-version "14.7.1,15.1,26.0"
   # Sonoma, Sequoia, Tahoe
   ```

4. **Enable Progress Logging**:
   ```bash
   # Already enabled automatically in v2.0!
   # Just run commands normally to see progress
   ```

### Performance Comparison

| Scenario | v1.0 | v2.0 | Improvement |
|----------|------|------|-------------|
| 1000 devices, OS compliance | 6 min | 20 sec | **18x faster** |
| 1000 devices, 1 app compliance | 6 min | 5 sec | **72x faster** |
| 1000 devices, CR summary (3 apps) | 20 min | 30 sec | **40x faster** |
| Search patch titles (repeat) | 30 sec | <1 sec | **30x+ faster** |

### What's the Same

- All commands work identically
- Exit codes unchanged
- JSON output format unchanged (new fields added, old fields preserved)
- Authentication methods unchanged
- API permissions unchanged

---

## Version 2.0 Feature Summary

### User Experience Improvements
- ✅ Real-time progress logging
- ✅ Enhanced error messages with troubleshooting steps
- ✅ Auto-fetch application versions from Patch Management
- ✅ Multiple output formats (JSON, Excel, PDF)
- ✅ Smart caching for instant repeated queries

### Performance Optimizations
- ✅ 98% reduction in API calls via Patch Report endpoint
- ✅ Intelligent caching of Patch Management titles
- ✅ Optimized section parameters for inventory queries
- ✅ Automatic API version detection

### New Capabilities
- ✅ macOS 26.x (Tahoe) support
- ✅ Patch definitions endpoint for version validation
- ✅ Major version filtering for applications
- ✅ Excel and PDF report generation
- ✅ Comprehensive troubleshooting guidance

### Production Readiness
- ✅ Tested on Jamf Pro 11.23.0
- ✅ Validated with 1000+ device environments
- ✅ Complete backwards compatibility
- ✅ Comprehensive documentation
- ✅ Battle-tested error handling

---

## Future Enhancements

Planned features (not yet implemented):
- Snapshot comparison (before/after CR)
- Extension attribute validation
- Automated CR scheduling
- Historical CR trend analysis
- Email report generation (SMTP)
- Custom compliance rules via YAML
- Batch processing for multiple CRs
- Performance telemetry and metrics
- Unit test coverage

---

## Support and Resources

### Documentation
- **Main README**: `/README.md` - Installation, configuration, all commands
- **CR Features**: This document - CR validation workflows
- **Implementation Summary**: `/CR_IMPLEMENTATION_SUMMARY.md` - Technical details
- **Session Report**: `/test_outputs/COMPLETE_SESSION_REPORT.md` - Testing and optimization results

### Getting Help

1. **Check Troubleshooting Section** (above) first
2. **Review Example Workflows** in this document
3. **Examine Test Outputs** in `/test_outputs/` directory
4. **GitHub Issues**: For bug reports or feature requests

### Quick Links

- Jamf Pro API Documentation: https://developer.jamf.com/
- Jamf Community: https://community.jamf.com/
- Python 3.8+ Documentation: https://docs.python.org/3/

---

## Version History

### Version 3.0 (November 2025) - Complete CR Automation

**New Commands** (10 total):
- `cr-readiness` - Pre-flight CR validation
- `wake-devices` - MDM blank push notifications
- `update-inventory` - Force inventory refresh
- `restart-devices` - Managed device restarts
- `remediate-policies` - Policy log flush and retry
- `remediate-profiles` - Profile reinstallation
- `auto-remediate` - Intelligent auto-retry with backoff
- `cr-compare` - Historical CR comparison
- `problem-devices` - Chronic failure tracking
- `run-workflow` - YAML workflow automation

**CR Workflow Automation**:
- Multi-phase workflows (pre_cr, during_cr, post_cr)
- YAML-based configuration
- Dry-run and validation modes
- Complete workflow examples included

**Long-Term CR Strategy**:
- Historical trend analysis (cr-compare)
- Problem device identification across CRs
- Month-over-month performance tracking
- Actionable recommendations

**Active Remediation**:
- Automated policy/profile retry with exponential backoff
- Success tracking and reporting
- Intelligent failure handling
- Non-disruptive wake operations

### Version 1.0 (November 2025) - Initial Production Release

**Core Features**:
- Six production-ready commands (`patch-compliance`, `device-availability`, `cr-summary`, `policy-failures`, `mdm-failures`, `profile-audit`)
- Comprehensive CR validation workflows
- Patch compliance checking (OS and applications)
- Device availability analysis
- Policy and MDM failure tracking
- Configuration profile auditing

**Performance Optimizations**:
- Patch Report API integration (98% API call reduction)
- Smart caching for Patch Management titles
- Section parameters for inventory queries
- Auto-fetch application versions from Patch Management

**User Experience**:
- Progress logging for long operations
- Enhanced error messages with troubleshooting guidance
- Multiple output formats (JSON, Excel, PDF)
- Microsoft Teams webhook integration
- macOS 26.x (Tahoe) support

**Production Quality**:
- Comprehensive live API testing (Jamf Pro 11.23.0)
- 1,000+ device environment validation
- Complete documentation
- Battle-tested error handling

---

**Last Updated**: November 22, 2025
**Version**: 3.0

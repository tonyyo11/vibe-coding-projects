# Jamf Health Tool - Troubleshooting Guide

Complete guide for diagnosing and resolving common issues with the Jamf Health Tool.

---

## Table of Contents

- [Quick Troubleshooting Checklist](#quick-troubleshooting-checklist)
- [Authentication Issues](#authentication-issues)
- [Application Compliance Issues](#application-compliance-issues)
- [Performance Issues](#performance-issues)
- [Data Issues](#data-issues)
- [Timestamp and Date Issues](#timestamp-and-date-issues)
- [Output and Reporting Issues](#output-and-reporting-issues)
- [Network and Connectivity Issues](#network-and-connectivity-issues)
- [Common Error Messages](#common-error-messages)
- [Getting Help](#getting-help)

---

## Quick Troubleshooting Checklist

When something goes wrong, check these in order:

### 1. ✅ Authentication

```bash
env | grep JAMF
# Should show JAMF_BASE_URL, JAMF_CLIENT_ID, JAMF_CLIENT_SECRET
```

**Expected Output**:
```
JAMF_BASE_URL=https://yourserver.jamfcloud.com
JAMF_CLIENT_ID=your-client-id
JAMF_CLIENT_SECRET=your-client-secret
```

### 2. ✅ Connectivity

```bash
curl -I $JAMF_BASE_URL
# Should return 200 or 302
```

**Expected Output**:
```
HTTP/2 302
location: /login.html
...
```

### 3. ✅ Permissions

Check API client in Jamf Pro:
- Settings > System > API Roles and Clients
- Verify client is **Enabled**
- Verify all required permissions are granted

### 4. ✅ Application Names

```bash
# Use auto-fetch instead of guessing names
jamf-health-tool patch-compliance --app "Safari"
```

### 5. ✅ Timestamps

```bash
# Always use ISO8601 format with Z
--cr-start "2024-11-18T00:00:00Z"
```

### 6. ✅ Dependencies

```bash
pip list | grep -E "openpyxl|reportlab|requests"
```

**Expected Output** (for full installation):
```
openpyxl        3.1.2
reportlab       4.0.7
requests        2.31.0
```

---

## Authentication Issues

### Problem: HTTP 401 - Invalid Client Credentials

#### Symptoms

```
ERROR: HTTP 401 for https://yourserver.jamfcloud.com/api/oauth/token

Authentication failed: Invalid client credentials.
```

#### Possible Causes

1. **Wrong Client ID or Secret**
2. **OAuth client is disabled**
3. **OAuth client was deleted**
4. **Typo in environment variables**

#### Solutions

**Step 1: Verify Environment Variables**

```bash
echo "Base URL: $JAMF_BASE_URL"
echo "Client ID: $JAMF_CLIENT_ID"
echo "Client Secret: ${JAMF_CLIENT_SECRET:0:10}..."  # Show only first 10 chars
```

Check for:
- Extra spaces
- Quotes around values (should not be there)
- Wrong case (environment variables are case-sensitive)

**Step 2: Check OAuth Client in Jamf Pro**

1. Log into Jamf Pro web interface
2. Go to **Settings > System > API Roles and Clients**
3. Find your API client
4. Verify:
   - **Enabled** checkbox is checked
   - Client ID matches `$JAMF_CLIENT_ID`
   - Expiration date hasn't passed

**Step 3: Regenerate Client Secret**

If you're unsure about the secret:

1. In Jamf Pro, find your API client
2. Click **Edit**
3. Click **Generate New Client Secret**
4. Copy the new secret
5. Update environment variable:
   ```bash
   export JAMF_CLIENT_SECRET="new-secret-here"
   ```

**Step 4: Test Authentication Separately**

```bash
# Simple test command
jamf-health-tool device-availability \
  --cr-start 2024-11-01T00:00:00Z \
  --cr-end 2024-11-01T01:00:00Z
```

If this works, authentication is correct.

---

### Problem: HTTP 403 - Forbidden (Insufficient Permissions)

#### Symptoms

```
ERROR: HTTP 403 for https://yourserver.jamfcloud.com/api/v2/patch-software-title-configurations

Forbidden: API client lacks required permissions.
```

#### Cause

Your OAuth client doesn't have the necessary API permissions.

#### Solution

**Required Permissions** (all read-only):
- ✅ Read Computers
- ✅ Read Computer Extension Attributes
- ✅ Read Computer Groups
- ✅ Read Patch Management Software Titles
- ✅ Read Policies
- ✅ Read macOS Configuration Profiles
- ✅ Read MDM Commands

**To Fix**:

1. Log into Jamf Pro
2. Go to **Settings > System > API Roles and Clients**
3. Find your API client and click **Edit**
4. Under **Privileges**, verify all required permissions are granted
5. Save changes
6. Wait 1-2 minutes for changes to propagate
7. Test again

**Quick Test**:

```bash
# Test specific endpoint
jamf-health-tool patch-compliance --app "Safari"
```

If you get 403 again, double-check permissions match exactly.

---

### Problem: HTTP 401 - Token Expired

#### Symptoms

```
ERROR: HTTP 401 for https://yourserver.jamfcloud.com/api/v3/computers-inventory

Authentication failed: Token may be expired or invalid.
```

#### Cause

Bearer token has expired (tokens typically expire after 30 minutes).

#### Solution

**If using Bearer Token**:

1. Generate a new token in Jamf Pro
2. Update environment variable:
   ```bash
   export JAMF_BEARER_TOKEN="new-token-here"
   ```

**If using OAuth** (recommended):

The tool automatically refreshes tokens. If you see this error with OAuth:

1. Verify Client ID and Secret are correct
2. Check OAuth client hasn't expired
3. Try regenerating Client Secret

**Switch to OAuth** (recommended):

```bash
# OAuth tokens are automatically refreshed
export JAMF_CLIENT_ID="your-client-id"
export JAMF_CLIENT_SECRET="your-client-secret"
unset JAMF_BEARER_TOKEN  # Remove bearer token
```

---

## Application Compliance Issues

### Problem: Application Not Found in Patch Management

#### Symptoms

```
WARNING: Application "Safari" not found in Patch Management
```

#### Possible Causes

1. **Application name doesn't match Patch Management entry**
2. **Application not configured in Patch Management**
3. **Case sensitivity issue**
4. **Insufficient API permissions**

#### Solutions

**Step 1: Verify Application Name**

Application names are case-sensitive and must match exactly:

```bash
# Try different variations
jamf-health-tool patch-compliance --app "Safari"
jamf-health-tool patch-compliance --app "Apple Safari"
jamf-health-tool patch-compliance --app "safari"  # lowercase
```

**Step 2: Check Patch Management Configuration**

1. Log into Jamf Pro
2. Go to **Patch Management**
3. Search for the application
4. Note the **exact spelling and capitalization**

**Step 3: Use First Run to See All Titles**

The tool fetches all patch titles on first run and caches them:

```bash
# Run once - logs show all available titles
jamf-health-tool patch-compliance --app "Test" 2>&1 | grep -i "fetching"
# Look for: "Completed fetching X Patch Management titles (cached for session)"
```

**Step 4: Fallback to Bundle ID**

If name matching fails, specify bundle ID:

```bash
jamf-health-tool patch-compliance \
  --app "Safari:18.1" \
  --bundle-id "com.apple.Safari"
```

**Step 5: Verify API Permissions**

Ensure you have **Read Patch Management Software Titles** permission.

---

### Problem: Using Inventory Method Instead of Patch Report (Slow)

#### Symptoms

```
INFO: Using inventory method for Google Chrome (980 API calls)
```

This means the optimization isn't being used! Performance will be much slower.

#### Cause

The tool couldn't find the application in Patch Management, so it falls back to checking each device individually.

#### Solution

**Enable Optimization** by ensuring patch_mgmt_id is found:

**Method 1: Use Auto-Fetch** (recommended)

```bash
# Don't specify version - let tool find it
jamf-health-tool patch-compliance --app "Google Chrome"
```

This automatically:
1. Searches Patch Management
2. Finds the patch_mgmt_id
3. Uses optimized Patch Report API

**Method 2: Verify Patch Management Configuration**

1. Application must exist in Jamf Patch Management
2. Application name must match exactly
3. Patch title must be active (not disabled)

**Method 3: Check Logs for Hints**

```bash
jamf-health-tool patch-compliance --app "Google Chrome" 2>&1 | grep -i "patch"
```

Look for:
- "Using patch report method" = ✅ Optimization working
- "Using inventory method" = ❌ Falling back to slow method

**Verification**:

When optimization is working, you'll see:

```
INFO: Found Google Chrome (ID: 12) - Latest version: 131.0.6778.86
INFO: Using patch report method for Google Chrome (1 API call vs 980)
```

---

## Performance Issues

### Problem: Slow Patch Title Fetching (30-60 seconds)

#### Symptoms

```
INFO: Fetching Patch Management titles from Jamf Pro...
[long pause...]
INFO: Completed fetching 1247 Patch Management titles (cached for session)
```

#### Expected Behavior

- **First run in a session**: 10-60 seconds (depends on # of titles configured)
- **Subsequent runs**: Instant (<1ms, uses cache)

#### If It's Slow Every Time

**Step 1: Verify Caching is Working**

```bash
# Run twice in same session
jamf-health-tool patch-compliance --app "Safari"
jamf-health-tool patch-compliance --app "Chrome"

# Second command should show:
# INFO: Using cached patch titles (1247 titles)
```

**Step 2: Check Number of Patch Titles**

If you have 1000+ patch titles:

1. Log into Jamf Pro
2. Go to **Patch Management**
3. Count how many titles are configured

**Recommendation**: Clean up unused patch titles to improve performance.

**Step 3: Use Explicit Versions** (trades optimization for speed)

```bash
# Skips patch title lookup entirely
jamf-health-tool patch-compliance \
  --app "Safari:18.1" \
  --app "Chrome:131.0.6778.86"
```

**Note**: This disables the patch report optimization, so you trade the initial lookup time for slower per-device checking.

---

### Problem: CR Summary Takes Too Long

#### Expected Performance

- **1,000 devices**: 30-60 seconds
- **5,000 devices**: 30-60 seconds
- **10,000 devices**: 1-2 minutes

#### If It's Slower Than Expected

**Step 1: Verify Optimization is Active**

```bash
jamf-health-tool cr-summary ... 2>&1 | grep -i "patch report"

# Should see:
# INFO: Using patch report method for Safari (1 API call vs 980)
```

If you don't see this, optimization isn't working. See [Application Not Found](#problem-application-not-found-in-patch-management).

**Step 2: Check Network Latency**

```bash
# Test connection to Jamf Pro
time curl -I $JAMF_BASE_URL

# Should be <500ms
```

If latency is high (>1 second), network issues may be slowing things down.

**Step 3: Reduce Scope for Testing**

```bash
# Test with smaller group first
jamf-health-tool cr-summary --scope-group-id <small-test-group> ...
```

**Step 4: Check Jamf Pro Server Health**

- Is Jamf Pro responding slowly to other requests?
- Are there known performance issues with your Jamf instance?
- Try again during off-peak hours

---

### Problem: Memory Issues with Large Fleet

#### Symptoms

```
MemoryError: Unable to allocate array
```

#### Solution

The tool uses pagination to handle large fleets. If you see memory errors:

**Step 1: Verify Python Version**

```bash
python3 --version
# Should be 3.8 or higher
```

**Step 2: Increase Available Memory**

If running in container or VM, allocate more RAM.

**Step 3: Process in Batches**

Instead of processing entire fleet at once, process by groups:

```bash
# Group 1
jamf-health-tool cr-summary --scope-group-id 100 ...

# Group 2
jamf-health-tool cr-summary --scope-group-id 200 ...
```

---

## Data Issues

### Problem: No Devices Found in Scope

#### Symptoms

```
Total Devices: 0
```

#### Possible Causes

1. **Wrong Group ID**
2. **Group is empty**
3. **Insufficient API permissions**

#### Solutions

**Step 1: Verify Group ID**

```bash
# Try without limiting group
jamf-health-tool device-availability \
  --cr-start 2024-11-01T00:00:00Z \
  --cr-end 2024-11-22T23:59:59Z
# Don't specify --scope-group-id
```

If this shows devices, the group ID is wrong.

**Step 2: Check Group in Jamf Pro**

1. Log into Jamf Pro
2. Go to **Computers > Smart Computer Groups** or **Static Computer Groups**
3. Find your group
4. Verify it has members
5. Note the ID in the URL (e.g., `.../computers.html?id=123&...`)

**Step 3: Verify API Permissions**

Ensure you have:
- ✅ Read Computer Groups
- ✅ Read Computers

---

### Problem: All Devices Showing as Offline

#### Symptoms

```
Online Devices: 0
Offline Devices: 1000
```

#### Possible Causes

1. **CR window is too old**
2. **Devices actually haven't checked in**
3. **Wrong timestamp format**

#### Solutions

**Step 1: Check CR Window**

```bash
# Is the window in the past?
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z"

# Current date should be after cr-end
date -u
```

**Step 2: Verify Device Check-Ins in Jamf Pro**

1. Log into Jamf Pro
2. Go to **Computers**
3. Click a few devices
4. Check "Last Inventory Update" date

If devices show recent check-ins in Jamf but appear offline in the tool, there may be a timestamp issue.

**Step 3: Adjust CR Start Time**

```bash
# Use a wider window
--cr-start 2024-11-01T00:00:00Z  # Earlier start
```

**Step 4: Check for MDM Issues**

If devices truly aren't checking in:
- Verify MDM is working in Jamf Pro
- Check network connectivity from devices
- Review MDM enrollment status

---

### Problem: Low Compliance Rates (<50%)

#### Symptoms

```
Overall Compliance: 45.2%
```

#### Diagnosis Steps

**Step 1: Check Device Availability First**

```bash
jamf-health-tool device-availability \
  --cr-start "2024-11-18T00:00:00Z" \
  --cr-end "2024-11-22T23:59:59Z" \
  --scope-group-id 123
```

**Interpret Results**:
- If >20% offline → **Device availability issue**
- If <5% offline → **Policy or patch issue**

**Step 2: Review Policy Execution**

```bash
jamf-health-tool policy-failures \
  --policy-id 100 \
  --since 2024-11-18T00:00:00Z
```

Check for widespread failures.

**Step 3: Verify Target Versions Exist**

The versions you're checking for must actually be available:

```bash
# Check in Jamf Pro Patch Management
# 1. Go to Patch Management
# 2. Find the application
# 3. Verify the version exists in the patch definition
```

**Or use Python to check**:

```python
from jamf_health_tool.jamf_client import JamfClient
import logging

client = JamfClient(None, logging.getLogger(), False)
safari = client.search_patch_software_title('Safari')
defs = client.get_patch_definitions(safari.id)
versions = [d['version'] for d in defs.get('patchDefinitions', [])]
print(f'Available versions: {versions[:10]}')
```

**Step 4: Check for macOS Version Mismatches**

Example issue:
- Target: Safari 18.1 (requires macOS 15.x Sequoia)
- Fleet: Most devices on macOS 14.x (Sonoma)
- Result: Low compliance because devices aren't eligible

**Solution**: Specify multiple versions for different macOS versions:

```bash
--app "Safari:17.6"  # For Sonoma (14.x)
--app "Safari:18.1"  # For Sequoia (15.x)
```

---

## Timestamp and Date Issues

### Problem: Invalid CR Window Timestamps

#### Symptoms

```
ERROR: Invalid timestamp format
```

#### Correct Format

Always use **ISO8601 with UTC timezone**:

```bash
# ✅ Correct:
--cr-start "2024-11-18T00:00:00Z"
--cr-end "2024-11-22T23:59:59Z"

# ❌ Wrong:
--cr-start "2024-11-18"              # Missing time
--cr-start "11/18/2024"              # Wrong format
--cr-start "2024-11-18 00:00:00"     # Missing T and Z
--cr-start "2024-11-18T00:00:00+00:00"  # Use Z instead
```

#### Format Breakdown

```
2024-11-18T00:00:00Z
│    │  │ │  │  │  └─ UTC timezone (Z = Zulu = UTC)
│    │  │ │  │  └──── Seconds
│    │  │ │  └─────── Minutes
│    │  │ └────────── Hours (24-hour)
│    │  └───────────── "T" separator (required)
│    └──────────────── Day
└───────────────────── Year-Month
```

---

### Problem: No Data in CR Window

#### Symptoms

```
CR Window: 2024-11-18T00:00:00Z → 2024-11-22T23:59:59Z
Total Devices: 1000
Online Entire Window: 0
```

#### Solutions

**Step 1: Verify Current Date**

```bash
date -u
# Make sure CR window is in the past!
```

**Step 2: Check for Timezone Issues**

All times are UTC (Z = Zulu time = UTC):

```bash
# If your local time is EST (-5 hours from UTC):
# 2024-11-18T00:00:00Z = 2024-11-17T19:00:00 EST
```

Devices checking in at "Nov 18, 1:00 AM EST" actually checked in at "Nov 18, 6:00 AM UTC".

**Step 3: Use Current Time for Ongoing CR**

```bash
# For ongoing CR, use current time as end
--cr-start "2024-11-18T00:00:00Z" \
--cr-end "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

---

## Output and Reporting Issues

### Problem: Excel/PDF Generation Failed

#### Symptoms

```
ERROR: Excel report generation failed: No module named 'openpyxl'
ERROR: PDF report generation failed: No module named 'reportlab'
```

#### Cause

Optional dependencies not installed.

#### Solution

```bash
# Install optional dependencies
pip install openpyxl reportlab Pillow

# Or reinstall with extras:
pip install -e ".[reports]"

# Verify installation:
python3 -c "import openpyxl; import reportlab; print('OK')"
```

**Expected Output**: `OK`

---

### Problem: Teams Webhook Not Working

#### Symptoms

```
WARNING: Failed to send Teams notification
```

#### Solutions

**Step 1: Verify Webhook URL**

```bash
# Test webhook manually
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"text":"Test from jamf-health-tool"}' \
  "$TEAMS_WEBHOOK_URL"

# Should return: 200 OK or 1
```

**Step 2: Check URL Format**

```bash
echo $TEAMS_WEBHOOK_URL
# Should start with: https://outlook.office.com/webhook/
```

**Step 3: Test Network Connectivity**

```bash
# Can you reach outlook.office.com?
ping outlook.office.com
curl -I https://outlook.office.com
```

**Step 4: Check Firewall Rules**

If running from server, ensure outbound HTTPS (port 443) to `outlook.office.com` is allowed.

**Step 5: Verify Webhook Hasn't Expired**

Teams webhooks can be disabled or deleted:

1. Check in Teams that webhook still exists
2. Try creating a new webhook
3. Update environment variable with new URL

---

## Network and Connectivity Issues

### Problem: Connection Timeout

#### Symptoms

```
ERROR: Connection timeout connecting to https://yourserver.jamfcloud.com
```

#### Solutions

**Step 1: Verify URL**

```bash
echo $JAMF_BASE_URL
# Should be: https://yourserver.jamfcloud.com
# NOT: https://yourserver.jamfcloud.com/ (no trailing slash)
```

**Step 2: Test Connectivity**

```bash
curl -v $JAMF_BASE_URL
```

**Step 3: Check Proxy Settings**

If behind corporate proxy:

```bash
export HTTP_PROXY="http://proxy.company.com:8080"
export HTTPS_PROXY="http://proxy.company.com:8080"
```

**Step 4: Check Firewall**

Ensure outbound HTTPS (port 443) to Jamf Pro is allowed.

---

### Problem: SSL Certificate Verification Failed

#### Symptoms

```
ERROR: SSL certificate verification failed
```

#### Temporary Workaround (NOT RECOMMENDED)

```bash
jamf-health-tool --no-verify-ssl patch-compliance ...
```

**Warning**: This disables SSL verification and is insecure.

#### Proper Solution

**Option 1: Fix Certificate Chain**

If using self-signed certificate, add it to system trust store:

```bash
# macOS
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /path/to/cert.pem

# Linux
sudo cp /path/to/cert.pem /usr/local/share/ca-certificates/jamf.crt
sudo update-ca-certificates
```

**Option 2: Specify Certificate Path**

```bash
jamf-health-tool --ssl-cert-path /path/to/cert.pem patch-compliance ...
```

---

## Common Error Messages

### "No module named 'jamf_health_tool'"

**Cause**: Tool not installed or wrong Python environment

**Solution**:

```bash
# Install the tool
pip install -e .

# Verify installation
jamf-health-tool --version
```

---

### "command not found: jamf-health-tool"

**Cause**: Tool not in PATH or not installed

**Solution**:

```bash
# Find where it's installed
pip show jamf-health-tool

# Add to PATH if needed
export PATH="$HOME/.local/bin:$PATH"

# Or use full path
python3 -m jamf_health_tool.cli --help
```

---

### "Resource not found: /api/v3/computers-inventory/999"

**Cause**: Device ID doesn't exist

**Solution**:

- Device may have been deleted from Jamf
- Check device ID is correct
- This is usually not an error - device just doesn't exist

---

### "Database connection failed"

**Cause**: Jamf Pro is experiencing issues

**Solution**:

- Try again later
- Check Jamf Pro status page
- Contact Jamf Support if persistent

---

## Getting Help

### Before Asking for Help

1. **Check this troubleshooting guide**
2. **Review error messages carefully** - They often contain hints
3. **Check logs** with `--verbose` flag
4. **Try simplest possible command first**

### Gathering Diagnostic Information

When reporting issues, include:

```bash
# 1. Tool version
jamf-health-tool --version

# 2. Python version
python3 --version

# 3. Environment (redact secrets!)
env | grep JAMF_BASE_URL
env | grep JAMF_CLIENT_ID
# DON'T include JAMF_CLIENT_SECRET!

# 4. Command that failed (with --verbose)
jamf-health-tool --verbose patch-compliance --app "Safari" 2>&1 | tee error.log

# 5. Error message from logs
cat error.log
```

### Resources

- **USAGE.md** - Detailed usage examples
- **README.md** - Quick start guide
- **PERFORMANCE.md** - Performance tuning
- Command help: `jamf-health-tool COMMAND --help`
- Jamf API Docs: https://developer.jamf.com/

---

**Last Updated**: November 22, 2024
**Version**: 3.0

**Note**: This guide applies to all 16 commands (6 validation + 10 automation commands). Version 3.0 automation commands (cr-readiness, wake-devices, remediate-policies, remediate-profiles, auto-remediate, cr-compare, problem-devices, run-workflow, update-inventory, restart-devices) follow the same authentication and troubleshooting patterns.

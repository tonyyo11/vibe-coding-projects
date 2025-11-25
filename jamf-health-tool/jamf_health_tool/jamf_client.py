"""
Jamf client using either Jamf API Utility (apiutil) or direct HTTP with bearer auth.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, Optional, TypeVar

import requests

from .cache import FileCache, make_cache_key
from .models import (
    Application,
    Computer,
    ConfigurationProfile,
    MdmCommand,
    PatchSoftwareTitle,
    Policy,
    PolicyExecutionStatus,
    Scope,
)

T = TypeVar("T")


class JamfApiError(Exception):
    """Raised when the Jamf API returns malformed data or cannot be parsed."""


class JamfCliError(Exception):
    """Raised when the apiutil CLI fails."""


class DataModelError(Exception):
    """Raised when expected fields are missing in responses."""


def _retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (requests.exceptions.ConnectionError, requests.exceptions.Timeout),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to retry a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        backoff_factor: Multiplier for delay after each retry
        retryable_exceptions: Tuple of exceptions that should trigger a retry
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exception = exc
                    if attempt < max_retries:
                        # Try to get logger from args or kwargs
                        logger = None
                        if args and hasattr(args[0], "logger"):
                            logger = args[0].logger
                        if logger:
                            logger.warning(
                                "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                                attempt + 1, max_retries + 1, exc, delay
                            )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        if logger:
                            logger.error("All retry attempts exhausted")
                        raise

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            return func(*args, **kwargs)

        return wrapper
    return decorator


@dataclass
class JamfAuth:
    base_url: Optional[str] = None
    bearer_token: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    verify_ssl: bool = True
    ssl_cert_path: Optional[str] = None

    def from_env(self) -> "JamfAuth":
        import os

        self.base_url = self.base_url or os.environ.get("JAMF_BASE_URL")
        self.bearer_token = self.bearer_token or os.environ.get("JAMF_BEARER_TOKEN")
        self.user = self.user or os.environ.get("JAMF_USER")
        self.password = self.password or os.environ.get("JAMF_PASSWORD")
        self.client_id = self.client_id or os.environ.get("JAMF_CLIENT_ID")
        self.client_secret = self.client_secret or os.environ.get("JAMF_CLIENT_SECRET")
        verify_ssl_env = os.environ.get("JAMF_VERIFY_SSL", "true").lower()
        self.verify_ssl = verify_ssl_env not in ("false", "0", "no")
        self.ssl_cert_path = self.ssl_cert_path or os.environ.get("JAMF_SSL_CERT_PATH")
        return self


def _apiutil_call(
    path: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
    *,
    target: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    log = logger or logging.getLogger(__name__)
    cmd = ["apiutil", "--path", path, "--accept", "application/json", "--method", method]
    if body:
        cmd += ["--data", json.dumps(body)]
    if target:
        cmd += ["--target", target]

    log.debug("api call path=%s method=%s target=%s", path, method, target or "")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise JamfCliError("apiutil command not found on PATH") from exc

    if result.returncode != 0:
        stdout_tail = (result.stdout or "")[:500]
        stderr_tail = (result.stderr or "")[:500]
        raise JamfCliError(
            f"apiutil failed (code {result.returncode}) for path {path}. "
            f"stdout: {stdout_tail} stderr: {stderr_tail}"
        )

    raw = result.stdout
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.debug("Invalid JSON from apiutil path=%s raw=%s", path, raw[:500])
        raise JamfApiError(f"Failed to parse JSON response for {path}") from exc


def jamf_api_call(
    path: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
    *,
    target: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper for apiutil transport (used in tests).
    """
    return _apiutil_call(path, method=method, body=body, target=target, logger=logger)


class JamfClient:
    """
    Client responsible for fetching Jamf objects via apiutil.
    """

    def __init__(
        self,
        target: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        *,
        use_apiutil: bool = False,
        base_url: Optional[str] = None,
        auth: Optional[JamfAuth] = None,
        verify_ssl: bool = True,
        ssl_cert_path: Optional[str] = None,
        debug_api: bool = False,
        cache: Optional[FileCache] = None,
        concurrency_enabled: bool = True,
        max_workers: int = 10,
    ):
        self.target = target
        self.logger = logger or logging.getLogger(__name__)
        self.use_apiutil = use_apiutil
        self.auth = (auth or JamfAuth(base_url=base_url, verify_ssl=verify_ssl, ssl_cert_path=ssl_cert_path)).from_env()
        self._cached_token: Optional[str] = None
        self._token_expiry: Optional[float] = None
        self.debug_api = debug_api
        self._jamf_version: Optional[str] = None
        self._api_version_cache: Dict[str, int] = {}  # Cache for API version availability
        self._patch_titles_cache: Optional[List[PatchSoftwareTitle]] = None  # Cache for patch titles
        self.cache = cache  # Optional persistent file cache for API responses
        self.concurrency_enabled = concurrency_enabled  # Enable concurrent API calls
        self.max_workers = max_workers  # Maximum concurrent threads

        # Validate configuration
        if not self.use_apiutil and not self.auth.base_url:
            raise JamfCliError(
                "JAMF_BASE_URL is required for direct HTTP mode (default). "
                "Either set JAMF_BASE_URL environment variable, use --base-url option, "
                "or use --use-apiutil to use Jamf API Utility instead."
            )

        # Warn if SSL verification is disabled
        if not self.auth.verify_ssl:
            import warnings
            warnings.warn(
                "SSL certificate verification is disabled. This is insecure and should only be used in testing.",
                stacklevel=2
            )
            self.logger.warning("SSL verification disabled - connection is not secure")

    # -------- Transport selection --------
    @_retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
    def _http_call(self, path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.auth.base_url:
            raise JamfCliError("JAMF_BASE_URL not set; cannot use HTTP mode.")
        url = self.auth.base_url.rstrip("/") + path
        headers = {"Accept": "application/json"}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Determine SSL verification setting
        verify: bool | str = self.auth.verify_ssl
        if self.auth.ssl_cert_path:
            verify = self.auth.ssl_cert_path

        try:
            resp = requests.request(method, url, json=body, headers=headers, timeout=30, verify=verify)

            # Debug mode: log full response
            if self.debug_api:
                self.logger.debug("API Response [%s %s]: Status=%d", method, path, resp.status_code)
                self.logger.debug("Response headers: %s", dict(resp.headers))
                self.logger.debug("Response body: %s", resp.text[:5000])

        except requests.exceptions.SSLError as exc:
            raise JamfCliError(
                f"SSL certificate verification failed for {url}. "
                "Use --no-verify-ssl to disable verification (insecure) or provide a certificate with --ssl-cert-path"
            ) from exc
        except requests.RequestException as exc:
            raise JamfCliError(f"HTTP request failed for {url}: {exc}") from exc

        if resp.status_code >= 400:
            error_msg = f"HTTP {resp.status_code} for {url}"
            if resp.status_code == 401:
                if "/oauth/token" in path:
                    error_msg += (
                        "\n\nAuthentication failed: Invalid client credentials."
                        "\n\nPlease verify:"
                        "\n  - JAMF_CLIENT_ID is correct"
                        "\n  - JAMF_CLIENT_SECRET is correct"
                        "\n  - OAuth client is enabled in Jamf Pro"
                        "\n  - OAuth client has not been deleted or disabled"
                        "\n\nTo create an API client:"
                        "\n  1. Log into Jamf Pro"
                        "\n  2. Go to Settings > System > API Roles and Clients"
                        "\n  3. Create a new API Client with required permissions"
                    )
                else:
                    error_msg += (
                        "\n\nAuthentication failed: Token may be expired or invalid."
                        "\n\nPlease verify your Jamf Pro credentials are configured correctly."
                    )
            elif resp.status_code == 403:
                error_msg += (
                    "\n\nForbidden: API client lacks required permissions."
                    "\n\nPlease verify the OAuth client has these permissions:"
                    "\n  - Read Computers"
                    "\n  - Read Computer Extension Attributes"
                    "\n  - Read Patch Management Software Titles"
                    "\n  - Read Policies"
                    "\n  - Read macOS Configuration Profiles"
                    "\n  - Read MDM Commands"
                    "\n\nUpdate permissions in: Jamf Pro > Settings > API Roles and Clients"
                )
            elif resp.status_code == 404:
                error_msg += f"\n\nResource not found: {path}"
                error_msg += "\n\nThis may indicate:"
                error_msg += "\n  - The resource ID doesn't exist"
                error_msg += "\n  - The API endpoint changed (check Jamf Pro version)"
                error_msg += "\n  - The API path is incorrect"
            elif resp.status_code >= 500:
                error_msg += (
                    "\n\nServer error: Jamf Pro returned an internal error."
                    "\n\nPossible causes:"
                    "\n  - Jamf Pro is experiencing issues"
                    "\n  - Database connectivity problems"
                    "\n  - Resource timeout"
                    "\n\nPlease try again later or contact Jamf Support."
                )
            error_msg += f"\n\nServer response (first 500 chars): {resp.text[:500]}"
            raise JamfCliError(error_msg)

        try:
            return resp.json()
        except ValueError as exc:
            self.logger.error("Failed to parse JSON from response. Body: %s", resp.text[:1000])
            raise JamfApiError(f"Failed to parse JSON response for {url}") from exc

    def _get_token(self) -> Optional[str]:
        # Check if cached token is still valid
        if self._cached_token and self._token_expiry:
            import time
            # Refresh token if within 60 seconds of expiry
            if time.time() + 60 < self._token_expiry:
                return self._cached_token
            else:
                self.logger.debug("Token expired or expiring soon, refreshing...")
                self._cached_token = None
                self._token_expiry = None

        if self._cached_token:
            return self._cached_token

        if self.auth.bearer_token:
            self._cached_token = self.auth.bearer_token
            return self._cached_token
        if self.auth.user and self.auth.password:
            self._cached_token = self._fetch_token_user_pass()
            return self._cached_token
        if self.auth.client_id and self.auth.client_secret:
            self._cached_token = self._fetch_token_client_creds()
            return self._cached_token
        return None

    def _fetch_token_user_pass(self) -> str:
        if not self.auth.base_url:
            raise JamfCliError("JAMF_BASE_URL not set; cannot fetch token.")
        url = self.auth.base_url.rstrip("/") + "/api/v1/auth/token"

        verify: bool | str = self.auth.verify_ssl
        if self.auth.ssl_cert_path:
            verify = self.auth.ssl_cert_path

        try:
            resp = requests.post(url, auth=(self.auth.user, self.auth.password), timeout=15, verify=verify)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("token") or data.get("access_token")

            # Store token expiry if provided
            if "expires" in data:
                import time
                self._token_expiry = time.time() + float(data["expires"])

            return token
        except requests.exceptions.SSLError as exc:
            raise JamfCliError(
                f"SSL certificate verification failed. "
                "Use --no-verify-ssl to disable (insecure) or provide certificate with --ssl-cert-path"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise JamfCliError(f"Failed to fetch token with user/password: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise JamfCliError(f"Invalid token response format: {exc}") from exc

    def _fetch_token_client_creds(self) -> str:
        if not self.auth.base_url:
            raise JamfCliError("JAMF_BASE_URL not set; cannot fetch token.")
        url = self.auth.base_url.rstrip("/") + "/api/oauth/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.auth.client_id,
            "client_secret": self.auth.client_secret,
        }

        verify: bool | str = self.auth.verify_ssl
        if self.auth.ssl_cert_path:
            verify = self.auth.ssl_cert_path

        try:
            resp = requests.post(
                url, data=payload, timeout=15, verify=verify
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token") or data.get("token")

            # Store token expiry if provided
            if "expires_in" in data:
                import time
                self._token_expiry = time.time() + float(data["expires_in"])

            return token
        except requests.exceptions.SSLError as exc:
            raise JamfCliError(
                f"SSL certificate verification failed. "
                "Use --no-verify-ssl to disable (insecure) or provide certificate with --ssl-cert-path"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise JamfCliError(f"Failed to fetch token with client credentials: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise JamfApiError(f"Invalid token response format: {exc}") from exc

    def _call(self, path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Make an API call using either HTTP (default) or apiutil.

        HTTP mode is the default and recommended method as it works reliably
        across all macOS versions. apiutil is available as a fallback option.

        For GET requests, results may be cached if caching is enabled.
        """
        # Try cache for GET requests only
        if self.cache and method == "GET":
            # Create cache key from base URL + path (+ body if present for POST-style GETs)
            tenant_url = self.auth.base_url if not self.use_apiutil else self.target or "apiutil"
            cache_params = {}
            if body:
                # Include body in cache key for parameterized GET requests
                cache_params = {k: str(v) for k, v in body.items()}

            cache_key = make_cache_key(tenant_url, path, **cache_params)

            # Try to get from cache
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                self.logger.debug(f"Cache hit for {path}")
                return cached_data

        # Cache miss or non-GET request - make the API call
        if self.use_apiutil:
            # Use apiutil (legacy method, may have compatibility issues on newer macOS)
            result = _apiutil_call(path, method=method, body=body, target=self.target, logger=self.logger)
        else:
            # Use direct HTTP (default, recommended)
            result = self._http_call(path, method=method, body=body)

        # Store in cache if this was a GET request
        if self.cache and method == "GET":
            tenant_url = self.auth.base_url if not self.use_apiutil else self.target or "apiutil"
            cache_params = {}
            if body:
                cache_params = {k: str(v) for k, v in body.items()}
            cache_key = make_cache_key(tenant_url, path, **cache_params)
            self.cache.set(cache_key, result)
            self.logger.debug(f"Cached response for {path}")

        return result

    # -------- Version Detection --------
    def get_jamf_version(self) -> str:
        """
        Get the Jamf Pro version from the server.

        Returns:
            Version string like "11.22.0" or "11.23.0"

        Note:
            Uses /api/v1/jamf-pro-version endpoint which returns:
            {"version": "11.23.0-t1763478557882"}
            The timestamp suffix is stripped to get the semantic version.
        """
        if self._jamf_version:
            return self._jamf_version

        try:
            data = self._call("/api/v1/jamf-pro-version")
            version_raw = data.get("version", "0.0.0")

            # Strip timestamp suffix if present (e.g., "11.23.0-t1763478557882" -> "11.23.0")
            if "-t" in version_raw:
                self._jamf_version = version_raw.split("-t")[0]
            else:
                self._jamf_version = version_raw

            self.logger.debug("Detected Jamf Pro version: %s (raw: %s)", self._jamf_version, version_raw)
            return self._jamf_version
        except Exception as exc:
            self.logger.warning("Failed to detect Jamf Pro version: %s. Assuming older version.", exc)
            self._jamf_version = "0.0.0"
            return self._jamf_version

    def _get_api_version(self, endpoint_prefix: str) -> int:
        """
        Determine the highest supported API version for a given endpoint.

        Args:
            endpoint_prefix: The endpoint prefix (e.g., "computers-inventory")

        Returns:
            API version number (1, 2, or 3)
        """
        if endpoint_prefix in self._api_version_cache:
            return self._api_version_cache[endpoint_prefix]

        version_str = self.get_jamf_version()
        try:
            parts = version_str.split(".")
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            major, minor = 0, 0

        # Determine API version based on Jamf Pro version
        # v3 computers-inventory: Jamf Pro 11.23.0+
        # v2 computers-inventory: Jamf Pro 11.20.0 - 11.22.x
        # v1 computers-inventory: Older versions

        api_version = 1  # Default to v1

        if endpoint_prefix == "computers-inventory":
            if major > 11 or (major == 11 and minor >= 23):
                api_version = 3
            elif major == 11 and minor >= 20:
                api_version = 2

        self._api_version_cache[endpoint_prefix] = api_version
        self.logger.debug("Using API v%d for %s (Jamf Pro %s)", api_version, endpoint_prefix, version_str)
        return api_version

    # -------- Parsing helpers --------
    def _parse_scope(self, scope_data: Dict[str, Any]) -> Scope:
        if scope_data is None:
            raise DataModelError("Missing scope data")
        included_groups = {int(g["id"]) for g in scope_data.get("computer_groups", []) if "id" in g}
        excluded_groups = {int(g["id"]) for g in scope_data.get("exclusions", {}).get("computer_groups", []) if "id" in g}
        included_computers = {int(c["id"]) for c in scope_data.get("computers", []) if "id" in c}
        excluded_computers = {int(c["id"]) for c in scope_data.get("exclusions", {}).get("computers", []) if "id" in c}
        all_flag = bool(scope_data.get("all_computers"))
        return Scope(
            all_computers=all_flag,
            included_group_ids=included_groups,
            excluded_group_ids=excluded_groups,
            included_computer_ids=included_computers,
            excluded_computer_ids=excluded_computers,
        )

    # -------- Policy --------
    def get_policy(self, policy_id: int) -> Policy:
        data = self._call(f"/JSSResource/policies/id/{policy_id}")
        payload = data.get("policy") or data
        general = payload.get("general")
        scope_data = payload.get("scope")
        if not general or scope_data is None:
            raise DataModelError(f"Policy {policy_id} missing general or scope")
        policy = Policy(
            id=int(general.get("id", policy_id)),
            name=general.get("name") or f"Policy-{policy_id}",
            enabled=bool(general.get("enabled", True)),
            scope=self._parse_scope(scope_data),
        )
        return policy

    # -------- Computer groups --------
    def get_computer_group_members(self, group_id: int) -> List[Computer]:
        data = self._call(f"/JSSResource/computergroups/id/{group_id}")
        group = data.get("computer_group") or data.get("computergroup") or data
        members = group.get("computers", [])
        parsed: List[Computer] = []
        for comp in members:
            comp_id = comp.get("id")
            if comp_id is None:
                continue
            parsed.append(
                Computer(
                    id=int(comp_id),
                    name=comp.get("name") or f"Computer-{comp_id}",
                    serial=comp.get("serial_number"),
                    udid=comp.get("udid"),
                )
            )
        return parsed

    # -------- Inventory --------
    def list_computers_inventory(
        self,
        ids: Optional[Iterable[int]] = None,
        serials: Optional[Iterable[str]] = None,
        names: Optional[Iterable[str]] = None,
    ) -> List[Computer]:
        """
        List computers from Jamf inventory with optional filtering.

        Args:
            ids: Optional set of computer IDs to filter by
            serials: Optional set of serial numbers to filter by
            names: Optional set of computer names to filter by

        Returns:
            List of Computer objects matching the filters

        Note:
            Filtering is done client-side. All pages are fetched until no more devices are returned.
            Uses the highest available API version (v3 > v2 > v1) based on Jamf Pro version.
            Requests OPERATING_SYSTEM section to get OS version data efficiently.
        """
        # Determine API version to use
        api_version = self._get_api_version("computers-inventory")

        params = {"page": 0, "page-size": 200}

        # Request OPERATING_SYSTEM section to get OS version in the list response
        # This avoids needing to fetch detail for each computer
        # Available sections: GENERAL, HARDWARE, OPERATING_SYSTEM, USER_AND_LOCATION,
        # PURCHASING, APPLICATIONS, STORAGE, etc.
        params["section"] = "GENERAL&section=OPERATING_SYSTEM"

        results: List[Computer] = []
        ids_set = {int(x) for x in ids} if ids else None
        serials_set = {s.upper() for s in serials} if serials else None
        names_set = {n.lower() for n in names} if names else None

        total_fetched = 0
        while True:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            path = f"/api/v{api_version}/computers-inventory?{qs}"
            resp = self._call(path)
            devices = resp.get("results") or []

            if not devices:
                # No more devices to fetch
                break

            total_fetched += len(devices)
            self.logger.debug("Fetched page %d with %d devices (total: %d)", params["page"], len(devices), total_fetched)

            for device in devices:
                comp_id = device.get("id")
                if comp_id is None:
                    continue
                serial = (device.get("serialNumber") or "").upper()
                name = device.get("name") or device.get("general", {}).get("name") or f"Computer-{comp_id}"
                udid = device.get("udid") or device.get("general", {}).get("udid")
                # Extract last check-in from multiple possible fields
                general = device.get("general", {})
                hardware = device.get("hardware", {})
                last_check_in = (
                    device.get("lastCheckIn")
                    or general.get("lastCheckIn")
                    or general.get("last_check_in")
                    or general.get("last_contact_time")
                    or general.get("lastContactTime")
                    or general.get("last_report_date")
                    or device.get("last_contact_time")
                    or device.get("lastContactTime")
                    or hardware.get("lastContactTime")
                    or hardware.get("lastContactTimestamp")
                    or device.get("reportDate")
                    or general.get("reportDate")
                )

                # Apply client-side filtering early
                if ids_set and int(comp_id) not in ids_set:
                    continue
                if serials_set and serial and serial.upper() not in serials_set:
                    continue
                if names_set and name.lower() not in names_set:
                    continue

                # Extract OS version information
                # With OPERATING_SYSTEM section requested, the operatingSystem field should be populated
                os_info = device.get("operatingSystem") or device.get("os", {}) or device.get("operating_system") or {}
                os_version = None
                os_build = None

                if isinstance(os_info, dict):
                    # Try to get macOS marketing version (e.g., "15.1")
                    # The operatingSystem section may have:
                    #   - name: "macOS 15.1" or "macOS Sequoia 15.1"
                    #   - version: "15.1" or "26.0.0" (Darwin kernel version)
                    os_name = os_info.get("name")
                    os_ver = os_info.get("version")

                    # Prefer name field if it contains "macOS"
                    if os_name and "macOS" in str(os_name):
                        # Extract version from "macOS 15.1" or "macOS Sequoia 15.1"
                        parts = str(os_name).split()
                        # Find the part that looks like a version number (e.g., "15.1")
                        for part in parts:
                            if part and part[0].isdigit() and "." in part:
                                os_version = part
                                break

                    # Fall back to version field if name parsing didn't work
                    if not os_version and os_ver:
                        os_version = os_ver

                    # Also check legacy field names for compatibility
                    if not os_version:
                        os_version = (
                            os_info.get("osVersion")
                            or os_info.get("operatingSystem")
                        )

                    os_build = os_info.get("build") or os_info.get("osBuild") or os_info.get("supplementalBuildVersion")

                elif isinstance(os_info, str):
                    os_version = os_info

                # Fall back to nested paths if operatingSystem section not populated
                if not os_version:
                    general = device.get("general", {})
                    hardware = device.get("hardware", {})
                    os_version = (
                        general.get("operatingSystem")
                        or general.get("osVersion")
                        or hardware.get("osVersion")
                        or device.get("softwareVersion")
                    )
                    if not os_build:
                        os_build = general.get("osBuild") or hardware.get("osBuild")

                candidate = Computer(
                    id=int(comp_id),
                    name=name,
                    serial=serial or None,
                    udid=udid,
                    last_check_in=last_check_in,
                    os_version=os_version,
                    os_build=os_build,
                )

                results.append(candidate)

            params["page"] += 1

            # Safety check: prevent infinite loops
            if params["page"] > 1000:
                self.logger.warning("Reached pagination limit of 1000 pages, stopping")
                break

        self.logger.info("Inventory fetch complete: %d devices fetched, %d matched filters", total_fetched, len(results))
        return results

    def get_computer_applications(self, computer_id: int) -> List[Application]:
        """
        Fetch installed applications for a specific computer.

        Args:
            computer_id: The Jamf computer ID

        Returns:
            List of Application objects
        """
        # Use the same API version as inventory
        api_version = self._get_api_version("computers-inventory")
        path = f"/api/v{api_version}/computers-inventory-detail/{computer_id}"
        try:
            resp = self._call(path)

            # Applications can be in different locations depending on API response structure
            # Try root level first (common in newer API versions)
            applications_data = resp.get("applications", [])

            # Fall back to nested path if not found at root
            if not applications_data:
                general = resp.get("general", {})
                applications_data = general.get("software", {}).get("applications", [])

            applications = []
            for app_data in applications_data:
                app_name = app_data.get("name")
                app_version = app_data.get("version")
                if app_name and app_version:
                    applications.append(Application(
                        name=app_name,
                        version=app_version,
                        bundle_id=app_data.get("bundleId"),
                        path=app_data.get("path")
                    ))

            self.logger.debug("Found %d applications for computer %d", len(applications), computer_id)
            return applications
        except (JamfApiError, JamfCliError) as exc:
            self.logger.warning("Failed to fetch applications for computer %d: %s", computer_id, exc)
            return []

    # -------- Computer management --------
    def get_computer_management(self, computer_id: int) -> Computer:
        path = f"/JSSResource/computermanagement/id/{computer_id}/subset/General&SmartGroups&StaticGroups&OSXConfigurationProfiles"
        data = self._call(path)
        management = data.get("computer_management") or data
        general = management.get("general") or {}
        comp_id = int(general.get("id", computer_id))
        name = general.get("name") or f"Computer-{comp_id}"
        serial = general.get("serial_number") or general.get("serialNumber")
        udid = general.get("udid")
        smart_groups = {int(g["id"]) for g in management.get("smart_groups", []) if "id" in g}
        static_groups = {int(g["id"]) for g in management.get("static_groups", []) if "id" in g}
        applied_profiles = {
            int(p["id"]) for p in management.get("os_x_configuration_profiles", []) if "id" in p
        }
        return Computer(
            id=comp_id,
            name=name,
            serial=serial,
            udid=udid,
            smart_groups=smart_groups,
            static_groups=static_groups,
            applied_profile_ids=applied_profiles,
        )

    # -------- Configuration profiles --------
    def list_configuration_profiles(self) -> List[ConfigurationProfile]:
        data = self._call("/JSSResource/osxconfigurationprofiles")
        profiles_root = data.get("os_x_configuration_profiles") or data.get("osxconfigurationprofiles") or []

        profile_ids = [int(item["id"]) for item in profiles_root if "id" in item]
        total = len(profile_ids)

        if total == 0:
            return []

        self.logger.info("Fetching details for %d configuration profiles...", total)

        # Use concurrency if enabled and we have multiple profiles
        if self.concurrency_enabled and total > 1:
            from .concurrency import execute_concurrent_with_fallback

            profiles = execute_concurrent_with_fallback(
                self.get_configuration_profile,
                profile_ids,
                max_workers=self.max_workers,
                logger=self.logger,
                description="Fetching configuration profiles",
                skip_errors=True
            )
            self.logger.info("Finished fetching %d configuration profiles (concurrent)", len(profiles))
        else:
            # Sequential fallback
            profiles = []
            for idx, pid in enumerate(profile_ids, start=1):
                if idx % 10 == 0 or idx == total:
                    self.logger.info("Fetching profile %d/%d (ID: %d)...", idx, total, pid)
                try:
                    profiles.append(self.get_configuration_profile(pid))
                except Exception as exc:
                    self.logger.warning(f"Failed to fetch profile {pid}: {exc}")
            self.logger.info("Finished fetching %d configuration profiles (sequential)", len(profiles))

        return profiles

    def get_configuration_profile(self, profile_id: int) -> ConfigurationProfile:
        data = self._call(f"/JSSResource/osxconfigurationprofiles/id/{profile_id}")
        profile = data.get("os_x_configuration_profile") or data.get("osxconfigurationprofile") or data
        general = profile.get("general") or {}
        scope_data = profile.get("scope")
        if scope_data is None:
            raise DataModelError(f"Configuration profile {profile_id} missing scope")
        return ConfigurationProfile(
            id=int(general.get("id", profile_id)),
            name=general.get("name") or f"Profile-{profile_id}",
            identifier=general.get("identifier"),
            scope=self._parse_scope(scope_data),
        )

    # -------- Computer history --------
    def get_computer_history(self, computer_id: int) -> List[PolicyExecutionStatus]:
        # Use subset endpoint to fetch only PolicyLogs, not entire history
        # This dramatically reduces response size and prevents timeouts
        data = self._call(f"/JSSResource/computerhistory/id/{computer_id}/subset/PolicyLogs")
        history = data.get("computer_history") or data
        policy_logs = history.get("policy_logs") or []
        results: List[PolicyExecutionStatus] = []
        for entry in policy_logs:
            policy_id = entry.get("policy_id")
            if policy_id is None:
                continue
            results.append(
                PolicyExecutionStatus(
                    policy_id=int(policy_id),
                    computer_id=computer_id,
                    last_status=entry.get("status"),
                    last_run_time=entry.get("date_time") or entry.get("date"),
                    failure_count=1 if entry.get("status") == "Failed" else 0,
                )
            )
        return results

    # -------- MDM commands --------
    def list_computer_commands(self) -> List[MdmCommand]:
        data = self._call("/JSSResource/computercommands")

        if not isinstance(data, dict):
            self.logger.warning("Unexpected response type for computercommands: %s", type(data))
            return []

        cmds = data.get("computer_commands") or data.get("computercommands") or []

        # Ensure cmds is a list, not a string or other type
        if not isinstance(cmds, list):
            self.logger.warning(f"Unexpected type for computer commands: {type(cmds)}. Expected list.")
            return []

        results: List[MdmCommand] = []
        for cmd in cmds:
            # Skip if cmd is not a dict (defensive programming)
            if not isinstance(cmd, dict):
                self.logger.warning(f"Skipping non-dict command entry: {type(cmd)}")
                continue

            uuid = cmd.get("uuid") or cmd.get("command_uuid")
            device_id = cmd.get("computer_id") or cmd.get("device_id")
            if not uuid or device_id is None:
                continue
            results.append(
                MdmCommand(
                    uuid=str(uuid),
                    device_id=int(device_id),
                    command_name=cmd.get("command") or cmd.get("name") or "Unknown",
                    status=cmd.get("status") or cmd.get("state") or "Unknown",
                    issued=cmd.get("issued") or cmd.get("date_issued"),
                    completed=cmd.get("completed") or cmd.get("date_completed"),
                )
            )
        return results

    def delete_computer_command(self, command_uuid: str) -> bool:
        """
        Delete a failed MDM command to clear it from the queue.

        Args:
            command_uuid: UUID of the command to delete

        Returns:
            True if deletion successful, False otherwise

        Example:
            >>> client.delete_computer_command("12345678-1234-1234-1234-123456789012")
            True
        """
        try:
            self._call(f"/JSSResource/computercommands/id/{command_uuid}", method="DELETE")
            self.logger.info(f"Deleted MDM command: {command_uuid}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to delete command {command_uuid}: {exc}")
            return False

    def send_install_profile_command(self, computer_id: int, profile_id: int) -> Optional[str]:
        """
        Send an InstallProfile MDM command to a computer.

        Args:
            computer_id: ID of the computer to receive the command
            profile_id: ID of the configuration profile to install

        Returns:
            Command UUID if successful, None otherwise

        Example:
            >>> uuid = client.send_install_profile_command(123, 456)
            >>> print(f"Sent command: {uuid}")
            Sent command: 12345678-1234-1234-1234-123456789012
        """
        try:
            # Use the InstallProfile command endpoint
            data = self._call(
                f"/JSSResource/computercommands/command/InstallProfile/id/{computer_id}",
                method="POST",
                body={"profile_id": profile_id}
            )

            # Extract command UUID from response
            command_uuid = data.get("computer_command", {}).get("command_uuid")
            if command_uuid:
                self.logger.info(
                    f"Sent InstallProfile command for profile {profile_id} to computer {computer_id} "
                    f"(command UUID: {command_uuid})"
                )
                return str(command_uuid)
            else:
                self.logger.warning(f"Command sent but no UUID returned: {data}")
                return None

        except Exception as exc:
            self.logger.error(
                f"Failed to send InstallProfile command for profile {profile_id} to computer {computer_id}: {exc}"
            )
            return None

    def send_blank_push(self, computer_id: int) -> Optional[str]:
        """
        Send a BlankPush MDM command to wake up a device and process pending commands.

        Args:
            computer_id: ID of the computer to receive the blank push

        Returns:
            Command UUID if successful, None otherwise

        Example:
            >>> uuid = client.send_blank_push(123)
            >>> print(f"Sent blank push: {uuid}")
            Sent blank push: 12345678-1234-1234-1234-123456789012
        """
        try:
            data = self._call(
                f"/JSSResource/computercommands/command/BlankPush/id/{computer_id}",
                method="POST"
            )

            command_uuid = data.get("computer_command", {}).get("command_uuid")
            if command_uuid:
                self.logger.info(f"Sent BlankPush to computer {computer_id} (UUID: {command_uuid})")
                return str(command_uuid)
            else:
                self.logger.warning(f"BlankPush sent but no UUID returned: {data}")
                return None

        except Exception as exc:
            self.logger.error(f"Failed to send BlankPush to computer {computer_id}: {exc}")
            return None

    def flush_policy_logs(self, computer_id: int, policy_id: int) -> bool:
        """
        Flush policy logs for a specific policy on a specific computer.

        This removes the policy execution history for the given policy on the given computer,
        allowing the policy to run again (useful for "once per computer" policies).

        IMPORTANT: This only flushes logs for the specified computer, NOT the entire policy.
        This prevents accidentally forcing all scoped computers to re-run the policy.

        Args:
            computer_id: ID of the computer to flush logs for
            policy_id: ID of the policy to flush logs for

        Returns:
            True if flush successful, False otherwise

        Example:
            >>> client.flush_policy_logs(123, 456)
            True
        """
        try:
            # Use the flush policy logs endpoint for a specific computer
            # This is safer than flushing the entire policy
            self._call(
                f"/JSSResource/computerhistory/id/{computer_id}/subset/PolicyLogs",
                method="DELETE",
                body={"policy_id": policy_id}
            )
            self.logger.info(f"Flushed policy {policy_id} logs for computer {computer_id}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to flush policy {policy_id} logs for computer {computer_id}: {exc}")
            return False

    def update_inventory(self, computer_id: int) -> Optional[str]:
        """
        Send an UpdateInventory MDM command to force a device to submit updated inventory.

        Args:
            computer_id: ID of the computer to update inventory

        Returns:
            Command UUID if successful, None otherwise

        Example:
            >>> uuid = client.update_inventory(123)
            >>> print(f"Sent inventory update: {uuid}")
            Sent inventory update: 12345678-1234-1234-1234-123456789012
        """
        try:
            data = self._call(
                f"/JSSResource/computercommands/command/UpdateInventory/id/{computer_id}",
                method="POST"
            )

            command_uuid = data.get("computer_command", {}).get("command_uuid")
            if command_uuid:
                self.logger.info(f"Sent UpdateInventory to computer {computer_id} (UUID: {command_uuid})")
                return str(command_uuid)
            else:
                self.logger.warning(f"UpdateInventory sent but no UUID returned: {data}")
                return None

        except Exception as exc:
            self.logger.error(f"Failed to send UpdateInventory to computer {computer_id}: {exc}")
            return None

    def restart_device(self, computer_id: int) -> Optional[str]:
        """
        Send a RestartDevice MDM command to restart a computer.

        Args:
            computer_id: ID of the computer to restart

        Returns:
            Command UUID if successful, None otherwise

        Example:
            >>> uuid = client.restart_device(123)
            >>> print(f"Sent restart command: {uuid}")
            Sent restart command: 12345678-1234-1234-1234-123456789012
        """
        try:
            data = self._call(
                f"/JSSResource/computercommands/command/RestartDevice/id/{computer_id}",
                method="POST"
            )

            command_uuid = data.get("computer_command", {}).get("command_uuid")
            if command_uuid:
                self.logger.info(f"Sent RestartDevice to computer {computer_id} (UUID: {command_uuid})")
                return str(command_uuid)
            else:
                self.logger.warning(f"RestartDevice sent but no UUID returned: {data}")
                return None

        except Exception as exc:
            self.logger.error(f"Failed to send RestartDevice to computer {computer_id}: {exc}")
            return None

    def get_computer_detail(self, computer_id: int) -> Dict[str, Any]:
        """
        Get detailed computer information including hardware, storage, and battery details.

        Args:
            computer_id: ID of the computer

        Returns:
            Dictionary containing detailed computer information

        Example:
            >>> detail = client.get_computer_detail(123)
            >>> print(f"Free disk: {detail.get('hardware', {}).get('storage', [{}])[0].get('percentFree')}%")
        """
        try:
            # Use the v3 inventory detail endpoint for comprehensive data
            api_version = self._get_api_version("computers-inventory")
            path = f"/api/v{api_version}/computers-inventory-detail/{computer_id}"
            data = self._call(path)
            return data
        except Exception as exc:
            self.logger.error(f"Failed to get detail for computer {computer_id}: {exc}")
            return {}

    # -------- Patch Management --------
    def list_patch_software_titles(self) -> List[PatchSoftwareTitle]:
        """
        List all Patch Management Software Titles configured in Jamf Pro.

        Uses the modern v2 API endpoint with pagination. Results are cached
        to avoid repeated fetches during a single session.

        Returns:
            List of PatchSoftwareTitle objects

        Example:
            >>> titles = client.list_patch_software_titles()
            >>> chrome = next((t for t in titles if "Chrome" in t.name), None)
        """
        # Return cached results if available
        if self._patch_titles_cache is not None:
            self.logger.debug("Using cached patch titles (%d titles)", len(self._patch_titles_cache))
            return self._patch_titles_cache

        self.logger.info("Fetching Patch Management titles from Jamf Pro...")
        results: List[PatchSoftwareTitle] = []
        params = {"page": 0, "page-size": 100}

        while True:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            path = f"/api/v2/patch-software-title-configurations?{qs}"

            try:
                resp = self._call(path)

                # Handle case where API returns a list directly instead of dict
                if isinstance(resp, list):
                    titles = resp
                elif isinstance(resp, dict):
                    titles = resp.get("results") or []
                else:
                    self.logger.warning("Unexpected response type from patch API: %s", type(resp))
                    titles = []

                if not titles:
                    break

                # Progress logging
                if params["page"] == 0 or (params["page"] + 1) % 5 == 0:
                    self.logger.info(
                        "Fetching patch titles page %d... (%d titles so far)",
                        params["page"] + 1, len(results)
                    )
                else:
                    self.logger.debug(
                        "Fetched page %d with %d patch titles",
                        params["page"], len(titles)
                    )

                for title in titles:
                    # Extract latest version from patches array if available
                    latest_version = None
                    patches = title.get("patches", [])
                    if patches and len(patches) > 0:
                        # Patches are typically sorted newest first
                        latest_version = patches[0].get("version")

                    # Get package configuration for bundle ID
                    bundle_id = None
                    pkg_config = title.get("packageConfiguration", {})
                    if pkg_config:
                        bundle_id = pkg_config.get("bundleId")

                    # Get display name
                    display_name = title.get("displayName") or title.get("name", "Unknown")

                    results.append(
                        PatchSoftwareTitle(
                            id=int(title.get("id", 0)),
                            name=display_name,
                            latest_version=latest_version,
                            bundle_id=bundle_id,
                            app_name=display_name
                        )
                    )

                params["page"] += 1

            except JamfApiError as e:
                # If v2 API fails, fall back to Classic API
                self.logger.warning(
                    "v2 Patch API failed (%s), falling back to Classic API", str(e)
                )
                return self._list_patch_software_titles_classic()

        # Cache results for future calls
        self._patch_titles_cache = results
        self.logger.info("Completed fetching %d Patch Management titles (cached for session)", len(results))
        return results

    def _list_patch_software_titles_classic(self) -> List[PatchSoftwareTitle]:
        """
        Fallback method using Classic API for Patch Management titles.

        Returns:
            List of PatchSoftwareTitle objects
        """
        results: List[PatchSoftwareTitle] = []

        try:
            self.logger.info("Fetching Patch Management titles from Classic API...")
            data = self._call("/JSSResource/patchsoftwaretitles")
            titles = data.get("patch_software_titles") or data.get("patchsoftwaretitles") or []

            total_titles = len(titles)
            self.logger.info("Found %d patch titles, fetching details...", total_titles)

            for idx, title in enumerate(titles, start=1):
                title_id = title.get("id")
                if title_id is None:
                    continue

                # Progress logging every 10 titles
                if idx % 10 == 0 or idx == total_titles:
                    self.logger.info("Fetching patch title %d/%d...", idx, total_titles)

                # Get detailed info for each title
                detail_data = self._call(f"/JSSResource/patchsoftwaretitles/id/{title_id}")
                detail = detail_data.get("patch_software_title") or detail_data

                # Extract latest version
                latest_version = None
                versions = detail.get("versions", [])
                if versions and len(versions) > 0:
                    latest_version = versions[0].get("software_version")

                results.append(
                    PatchSoftwareTitle(
                        id=int(title_id),
                        name=detail.get("name", "Unknown"),
                        latest_version=latest_version,
                        bundle_id=None,  # Classic API doesn't provide bundle ID easily
                        app_name=detail.get("name", "Unknown")
                    )
                )

        except JamfApiError as e:
            self.logger.error("Failed to fetch patch titles from Classic API: %s", str(e))

        # Cache results for future calls
        self._patch_titles_cache = results
        self.logger.info("Completed fetching %d Patch Management titles from Classic API (cached for session)", len(results))
        return results

    def get_patch_software_title(self, title_id: int) -> Optional[PatchSoftwareTitle]:
        """
        Get a specific Patch Management Software Title by ID.

        Args:
            title_id: Patch Software Title ID

        Returns:
            PatchSoftwareTitle object or None if not found
        """
        try:
            path = f"/api/v2/patch-software-title-configurations/{title_id}"
            data = self._call(path)

            # Extract latest version
            latest_version = None
            patches = data.get("patches", [])
            if patches and len(patches) > 0:
                latest_version = patches[0].get("version")

            # Get bundle ID
            bundle_id = None
            pkg_config = data.get("packageConfiguration", {})
            if pkg_config:
                bundle_id = pkg_config.get("bundleId")

            display_name = data.get("displayName") or data.get("name", "Unknown")

            return PatchSoftwareTitle(
                id=title_id,
                name=display_name,
                latest_version=latest_version,
                bundle_id=bundle_id,
                app_name=display_name
            )

        except JamfApiError as e:
            self.logger.warning("Failed to get patch title %d: %s", title_id, str(e))
            return None

    def get_patch_report(self, title_id: int) -> Dict[str, Any]:
        """
        Get patch report showing which devices have the application and their versions.

        This endpoint provides a comprehensive report of all devices with the specified
        patch title installed, including their current versions. This is much more
        efficient than querying each computer individually.

        Args:
            title_id: Patch Software Title ID

        Returns:
            Dictionary containing patch report data with device information

        Example:
            >>> report = client.get_patch_report(4)  # Safari
            >>> for device in report.get("deviceStatuses", []):
            ...     print(f"{device['name']}: {device['installedVersion']}")

        API Endpoint:
            GET /api/v2/patch-software-title-configurations/{id}/patch-report

        Response Structure:
            {
              "softwareTitleId": 4,
              "softwareTitleName": "Apple Safari",
              "deviceStatuses": [
                {
                  "deviceId": "5",
                  "name": "Computer Name",
                  "installedVersion": "18.0",
                  "patchStatus": "Up to Date" | "Out of Date" | "Unknown"
                }
              ]
            }
        """
        path = f"/api/v2/patch-software-title-configurations/{title_id}/patch-report"
        try:
            data = self._call(path)
            self.logger.debug(
                "Fetched patch report for title %d: %d devices",
                title_id,
                len(data.get("deviceStatuses", []))
            )
            return data
        except Exception as exc:
            self.logger.warning(
                "Failed to fetch patch report for title %d: %s",
                title_id, exc
            )
            # Return empty report structure
            return {
                "softwareTitleId": title_id,
                "deviceStatuses": []
            }

    def get_patch_definitions(self, title_id: int) -> Dict[str, Any]:
        """
        Get patch definitions (available versions) for a patch software title.

        This endpoint returns all available patch versions for the specified title,
        allowing validation that a target version exists before checking compliance.

        Args:
            title_id: Patch Software Title ID

        Returns:
            Dictionary containing patch definitions data with available versions

        Example:
            >>> definitions = client.get_patch_definitions(4)  # Safari
            >>> versions = [v.get("version") for v in definitions.get("patchDefinitions", [])]
            >>> print(f"Available versions: {versions}")

        API Endpoint:
            GET /api/v2/patch-software-title-configurations/{id}/definitions

        Response Structure:
            {
              "patchDefinitions": [
                {
                  "version": "18.1",
                  "releaseDate": "2024-10-28",
                  "minimumOperatingSystem": "14.0"
                },
                {
                  "version": "18.0",
                  "releaseDate": "2024-09-16",
                  "minimumOperatingSystem": "14.0"
                }
              ]
            }
        """
        path = f"/api/v2/patch-software-title-configurations/{title_id}/definitions"
        try:
            data = self._call(path)
            patch_defs = data.get("patchDefinitions", [])
            self.logger.debug(
                "Fetched %d patch definitions for title %d",
                len(patch_defs),
                title_id
            )
            return data
        except Exception as exc:
            self.logger.warning(
                "Failed to fetch patch definitions for title %d: %s",
                title_id, exc
            )
            # Return empty definitions structure
            return {
                "patchDefinitions": []
            }

    def search_patch_software_title(self, name: str) -> Optional[PatchSoftwareTitle]:
        """
        Search for a Patch Management Software Title by name (case-insensitive partial match).

        Args:
            name: Application name to search for

        Returns:
            PatchSoftwareTitle object or None if not found

        Example:
            >>> title = client.search_patch_software_title("Google Chrome")
            >>> if title:
            ...     print(f"Latest version: {title.latest_version}")
        """
        name_lower = name.lower()
        all_titles = self.list_patch_software_titles()

        # Try exact match first
        for title in all_titles:
            if title.name.lower() == name_lower:
                return title

        # Try partial match
        for title in all_titles:
            if name_lower in title.name.lower():
                self.logger.info(
                    "Found partial match for '%s': '%s' (ID: %d)",
                    name, title.name, title.id
                )
                return title

        return None

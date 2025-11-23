"""
Data models for Jamf Health Tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Set


@dataclass
class Scope:
    all_computers: bool = False
    included_group_ids: Set[int] = field(default_factory=set)
    excluded_group_ids: Set[int] = field(default_factory=set)
    included_computer_ids: Set[int] = field(default_factory=set)
    excluded_computer_ids: Set[int] = field(default_factory=set)


@dataclass
class Computer:
    id: int
    name: str
    serial: Optional[str] = None
    udid: Optional[str] = None
    smart_groups: Set[int] = field(default_factory=set)
    static_groups: Set[int] = field(default_factory=set)
    applied_profile_ids: Set[int] = field(default_factory=set)
    last_check_in: Optional[str] = None
    os_version: Optional[str] = None
    os_build: Optional[str] = None
    applications: List["Application"] = field(default_factory=list)


@dataclass
class Policy:
    id: int
    name: str
    enabled: bool
    scope: Scope


@dataclass
class ConfigurationProfile:
    id: int
    name: str
    identifier: Optional[str]
    scope: Scope


@dataclass
class PolicyExecutionStatus:
    policy_id: int
    computer_id: int
    last_status: Optional[str]
    last_run_time: Optional[str]
    failure_count: int = 0


@dataclass
class MdmCommand:
    uuid: str
    device_id: int
    command_name: str
    status: str
    issued: Optional[str] = None
    completed: Optional[str] = None


@dataclass
class Application:
    """Represents an installed application on a computer."""
    name: str
    version: str
    bundle_id: Optional[str] = None
    path: Optional[str] = None


@dataclass
class PatchTarget:
    """Represents a software patch target for compliance checking."""
    name: str
    target_type: str  # "os" or "application"
    min_version: Optional[str] = None  # Optional - can be auto-fetched from Patch Management
    critical: bool = True
    bundle_id: Optional[str] = None  # For application matching
    patch_mgmt_id: Optional[int] = None  # Jamf Patch Management ID for auto-fetch


@dataclass
class PatchSoftwareTitle:
    """Represents a Jamf Patch Management Software Title."""
    id: int
    name: str
    latest_version: Optional[str] = None
    bundle_id: Optional[str] = None
    app_name: Optional[str] = None


@dataclass
class CRConfig:
    """Configuration for a Change Request validation."""
    name: str
    start_time: datetime
    end_time: datetime
    policy_ids: List[int] = field(default_factory=list)
    patch_targets: List[PatchTarget] = field(default_factory=list)
    scope_group_id: Optional[int] = None
    success_threshold: float = 0.95  # 95% compliance = CR success
    limiting_group_id: Optional[int] = None


@dataclass
class DeviceCheckIn:
    """Represents a device check-in during a time window."""
    computer_id: int
    computer_name: str
    serial: Optional[str]
    first_check_in: datetime
    last_check_in: datetime
    check_in_count: int
    was_online: bool  # True if checked in at least once during window

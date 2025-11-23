from jamf_health_tool.models import Computer, ConfigurationProfile, Scope
from jamf_health_tool.profile_audit import audit_profiles


class FakeClient:
    def list_computers_inventory(self, ids=None, serials=None, names=None):
        return [Computer(id=1, name="Mac-1", serial="SERIAL1", smart_groups={100}, static_groups=set())]

    def list_configuration_profiles(self):
        scope = Scope(all_computers=False, included_group_ids={100})
        return [ConfigurationProfile(id=5, name="WiFi", identifier="wifi", scope=scope)]

    def list_computer_commands(self):
        return []

    def get_computer_management(self, computer_id):
        return Computer(
            id=1,
            name="Mac-1",
            serial="SERIAL1",
            smart_groups={100},
            static_groups=set(),
            applied_profile_ids=set(),
        )


def test_profile_audit_detects_missing_profile():
    client = FakeClient()
    results, exit_code = audit_profiles(["1"], client, logger=None)
    assert exit_code == 2
    assert results[0]["missingProfiles"][0]["id"] == 5

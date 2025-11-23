from jamf_health_tool.models import Computer, MdmCommand
from jamf_health_tool.mdm_failures import mdm_failures_report


class FakeClient:
    def list_computer_commands(self):
        return [
            MdmCommand(uuid="1", device_id=1, command_name="InstallConfigurationProfile", status="Failed", issued="2024-01-01T00:00:00Z"),
            MdmCommand(uuid="2", device_id=2, command_name="Other", status="Completed"),
        ]

    def list_computers_inventory(self, ids=None, serials=None, names=None):
        return [Computer(id=1, name="Mac-1")]


def test_mdm_failures_report_filters_failed():
    client = FakeClient()
    results, code = mdm_failures_report(
        scope_kind="computer-id",
        scope_values=["1"],
        client=client,
        since=None,
        command_types=None,
    )
    assert code == 0
    assert results["summary"]["InstallConfigurationProfile"] == 1

from jamf_health_tool.models import Computer, Policy, Scope, PolicyExecutionStatus
from jamf_health_tool.policy_failures import evaluate_policy_failures


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_policy(self, pid):
        scope = Scope(all_computers=False, included_computer_ids={1, 2})
        return Policy(id=pid, name="Test Policy", enabled=True, scope=scope)

    def list_computers_inventory(self, ids=None, serials=None, names=None):
        return [
            Computer(id=1, name="one", serial="A", last_check_in="2024-01-02T00:00:00Z"),
            Computer(id=2, name="two", serial="B", last_check_in="2024-01-02T00:00:00Z"),
        ]

    def get_computer_history(self, cid):
        if cid == 1:
            return [PolicyExecutionStatus(policy_id=10, computer_id=1, last_status="Completed", last_run_time="2020-01-01")]
        if cid == 2:
            return [PolicyExecutionStatus(policy_id=10, computer_id=2, last_status="Failed", last_run_time="2020-01-02")]
        return []

    def get_computer_group_members(self, group_id):
        return []


def test_evaluate_policy_failures_detects_failure():
    client = FakeClient()
    results, exit_code = evaluate_policy_failures([10], client, None)
    assert exit_code == 1
    assert results[0]["results"]["failed"] == 1
    assert len(results[0]["failedDevices"]) == 1


def test_evaluate_policy_offline_detection():
    client = FakeClient()
    # Mark one device as offline before CR start, one online after
    client.list_computers_inventory = lambda ids=None, serials=None, names=None: [
        Computer(id=1, name="one", serial="A", last_check_in="2024-01-02T00:00:00Z"),  # Online - after cr_start
        Computer(id=2, name="two", serial="B", last_check_in="2023-12-31T00:00:00Z"),  # Offline - before cr_start
    ]
    results, exit_code = evaluate_policy_failures([10], client, None, cr_start="2024-01-01T12:00:00Z")
    assert exit_code == 1
    assert results[0]["results"]["offline"] == 1

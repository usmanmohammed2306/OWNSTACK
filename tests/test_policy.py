"""Finite regression cases for the pure read policy, not an authentication audit.

Run with ``python3 -m unittest discover -s tests -v``. Subtests exercise input
variants without inflating the number of named test methods in the report.
"""

from dataclasses import FrozenInstanceError, replace
import unittest

from ownstack.policy import Principal, ReadDecision, can_read, read_decision


class ReadPolicyTest(unittest.TestCase):
    """Check isolation first, explicit role authority second, and denial otherwise."""

    def assert_read_result(self, principal, project_tenant, allowed):
        """Check both the explainable decision and the public boolean wrapper."""
        decision = read_decision(principal, project_tenant)
        self.assertIsInstance(decision, ReadDecision)
        self.assertIs(decision.allowed, allowed)
        self.assertEqual(decision.basis, "role" if allowed else "denied")
        # A ReadDecision object itself is truthy even when allowed is False.
        # The wrapper must return the actual bool, never the decision object.
        self.assertIs(can_read(principal, project_tenant), allowed)

    def test_same_tenant_admin_can_read(self):
        self.assert_read_result(Principal("atlas-admin", "atlas", "admin"), "atlas", True)

    def test_ungranted_contractor_cannot_read(self):
        self.assert_read_result(
            Principal("atlas-contractor", "atlas", "contractor"), "atlas", False
        )

    def test_each_allowed_role_can_read_its_own_tenant(self):
        for tenant in ("atlas", "nova"):
            for role in ("admin", "member", "engineer"):
                with self.subTest(tenant=tenant, role=role):
                    self.assert_read_result(Principal("user-1", tenant, role), tenant, True)

    def test_cross_tenant_access_is_denied_for_every_role(self):
        # This catches moving the role allowlist above the tenant boundary.
        for tenant, project in (("atlas", "nova"), ("nova", "atlas")):
            for role in ("admin", "member", "engineer", "contractor", "unknown"):
                with self.subTest(tenant=tenant, project=project, role=role):
                    self.assert_read_result(Principal("user-1", tenant, role), project, False)

    def test_unknown_roles_do_not_inherit_permissions(self):
        for role in ("", " ", "viewer", "owner", "platform-owner", "superadmin", "unknown"):
            with self.subTest(role=role):
                self.assert_read_result(Principal("user-1", "atlas", role), "atlas", False)

    def test_role_matching_is_exact_not_normalized(self):
        # Do not turn malformed claims into permissions by trimming or case folding.
        for role in ("Admin", "ADMIN", " admin", "admin ", "admin\n", "аdmin"):
            with self.subTest(role=role):
                self.assert_read_result(Principal("user-1", "atlas", role), "atlas", False)

    def test_tenant_matching_is_exact_not_normalized(self):
        for project in ("Atlas", "ATLAS", " atlas", "atlas ", "atlas\n", "atlas-child"):
            with self.subTest(project=project):
                self.assert_read_result(Principal("user-1", "atlas", "admin"), project, False)

    def test_tenant_identifiers_are_not_hardcoded_to_the_demo(self):
        for tenant in ("customer-west:42", "組織-1", "tenant-" + "x" * 512):
            with self.subTest(tenant=tenant):
                self.assert_read_result(Principal("user-1", tenant, "admin"), tenant, True)

    def test_admin_looking_user_id_does_not_grant_a_role(self):
        self.assert_read_result(Principal("atlas-admin", "atlas", "contractor"), "atlas", False)

    def test_user_id_does_not_select_a_different_tenant(self):
        self.assert_read_result(Principal("nova-admin", "atlas", "admin"), "nova", False)

    def test_blank_identity_fields_are_denied(self):
        for blank in ("", " ", "\t", "\n"):
            cases = (
                (Principal(blank, "atlas", "admin"), "atlas"),
                (Principal("user-1", blank, "admin"), "atlas"),
                (Principal("user-1", "atlas", "admin"), blank),
                # Equality alone must not authorize two missing tenant IDs.
                (Principal("user-1", blank, "admin"), blank),
            )
            for index, (principal, project) in enumerate(cases):
                with self.subTest(blank=repr(blank), field_case=index):
                    self.assert_read_result(principal, project, False)

    def test_non_string_identity_fields_are_denied(self):
        # Python annotations do not stop callers constructing malformed dataclasses.
        for invalid in (None, False, 0, 1, [], {}, b"atlas"):
            cases = (
                (Principal(invalid, "atlas", "admin"), "atlas"),
                (Principal("user-1", invalid, "admin"), "atlas"),
                (Principal("user-1", "atlas", "admin"), invalid),
                (Principal("user-1", invalid, "admin"), invalid),
            )
            for index, (principal, project) in enumerate(cases):
                with self.subTest(value=repr(invalid), field_case=index):
                    self.assert_read_result(principal, project, False)

    def test_non_string_roles_are_denied_without_crashing(self):
        for role in (None, False, 1, [], {}, {"admin"}, b"admin"):
            with self.subTest(role=repr(role)):
                self.assert_read_result(Principal("user-1", "atlas", role), "atlas", False)

    def test_missing_or_wrong_principal_objects_are_denied(self):
        for principal in (None, {}, "admin", [], object()):
            with self.subTest(principal_type=type(principal).__name__):
                self.assert_read_result(principal, "atlas", False)

    def test_can_read_returns_a_real_boolean(self):
        for role, expected in (("admin", True), ("contractor", False)):
            with self.subTest(role=role):
                result = can_read(Principal("user-1", "atlas", role), "atlas")
                self.assertIs(type(result), bool)
                self.assertIs(result, expected)

    def test_identical_inputs_produce_equal_decisions(self):
        principal = Principal("user-1", "atlas", "admin")
        self.assertEqual(read_decision(principal, "atlas"), read_decision(principal, "atlas"))

    def test_evaluation_does_not_modify_the_principal(self):
        principal = Principal("user-1", "atlas", "admin")
        before = replace(principal)
        self.assert_read_result(principal, "atlas", True)
        self.assert_read_result(principal, "nova", False)
        self.assertEqual(principal, before)

    def test_previous_allow_does_not_leak_into_a_later_denial(self):
        principal = Principal("user-1", "atlas", "admin")
        self.assert_read_result(principal, "atlas", True)
        self.assert_read_result(principal, "nova", False)
        self.assert_read_result(replace(principal, role="contractor"), "atlas", False)
        self.assert_read_result(principal, "atlas", True)

    def test_principal_fields_cannot_be_reassigned_normally(self):
        principal = Principal("user-1", "atlas", "contractor")
        for field, value in (("user_id", "other"), ("tenant_id", "nova"), ("role", "admin")):
            with self.subTest(field=field):
                with self.assertRaises(FrozenInstanceError):
                    setattr(principal, field, value)

    def test_decision_fields_cannot_be_reassigned_normally(self):
        decision = read_decision(Principal("user-1", "atlas", "contractor"), "atlas")
        for field, value in (("allowed", True), ("basis", "role")):
            with self.subTest(field=field):
                with self.assertRaises(FrozenInstanceError):
                    setattr(decision, field, value)


if __name__ == "__main__":
    unittest.main()

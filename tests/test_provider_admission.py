import unittest

from src.provider_admission import (
    ProviderBinding,
    ProviderRegistry,
    evaluate_provider_binding,
    reference_provider_binding,
)

NOW = 1_800_000_000
RECIPIENT = "0x000000000000000000000000000000000000beef"


class ProviderAdmissionTests(unittest.TestCase):
    def test_reference_binding_admits_only_with_complete_controls(self):
        binding = reference_provider_binding(payment_recipient=RECIPIENT, now=NOW)
        admission = evaluate_provider_binding(binding, now=NOW)
        self.assertEqual(admission.decision, "ADMIT")
        self.assertEqual(admission.binding_digest, binding.digest)

    def test_nonzero_retention_fails_closed(self):
        binding = reference_provider_binding(payment_recipient=RECIPIENT, now=NOW)
        unsafe = ProviderBinding(
            **{
                **binding.__dict__,
                "maximum_retention_seconds": 60,
            }
        )
        admission = evaluate_provider_binding(unsafe, now=NOW)
        self.assertEqual(admission.decision, "DENY")
        self.assertIn("provider-retention-not-zero", admission.reasons)

    def test_missing_independent_evidence_fails_closed(self):
        binding = reference_provider_binding(payment_recipient=RECIPIENT, now=NOW)
        unsafe = ProviderBinding(
            **{
                **binding.__dict__,
                "evidence_types": ("execution_receipt",),
            }
        )
        admission = evaluate_provider_binding(unsafe, now=NOW)
        self.assertEqual(admission.decision, "DENY")
        self.assertIn("provider-evidence-incomplete", admission.reasons)

    def test_registry_requires_monotonic_versions(self):
        registry = ProviderRegistry()
        binding = reference_provider_binding(payment_recipient=RECIPIENT, now=NOW)
        registry.admit(binding, now=NOW)
        with self.assertRaisesRegex(ValueError, "provider-version-not-monotonic"):
            registry.admit(binding, now=NOW)

    def test_registry_requires_capability_binding(self):
        registry = ProviderRegistry()
        binding = reference_provider_binding(payment_recipient=RECIPIENT, now=NOW)
        registry.admit(binding, now=NOW)
        with self.assertRaisesRegex(ValueError, "provider-capability-binding-mismatch"):
            registry.require(binding.provider_id, "different.capability", now=NOW)

    def test_registry_expiry_fails_closed(self):
        registry = ProviderRegistry()
        binding = reference_provider_binding(payment_recipient=RECIPIENT, now=NOW)
        registry.admit(binding, now=NOW)
        with self.assertRaisesRegex(ValueError, "provider-admission-expired"):
            registry.require(binding.provider_id, binding.capability, now=NOW + 3601)


if __name__ == "__main__":
    unittest.main()

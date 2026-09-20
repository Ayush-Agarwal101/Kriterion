// Kriterion admission policy, represented in Cedar syntax for auditability.
// The offline evaluator maps structured evidence attributes to this policy.

permit(
  principal,
  action == Action::"admit",
  resource
)
when {
  context.mandatory_evidence_complete == true &&
  context.no_mandatory_failures == true &&
  context.no_forbidden_action_violations == true &&
  context.artifact_pass == true &&
  context.license_pass == true &&
  context.runtime_within_threshold == true &&
  context.sandbox_pass == true
};

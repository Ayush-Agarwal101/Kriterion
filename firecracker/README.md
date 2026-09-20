# Firecracker Boundary

Kriterion routes sandbox-required evidence through `kriterion.sandbox`.

When the `firecracker` binary is present on `PATH`, the sandbox attestation records that the high-risk path can use Firecracker. When it is absent, sandbox-required tests produce `INSUFFICIENT_EVIDENCE`, and mandatory sandbox requirements cause a `BLOCK` decision.

This fail-closed behavior is intentional: the demo does not claim Firecracker isolation when the host cannot provide it.

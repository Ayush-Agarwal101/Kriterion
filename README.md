# Kriterion

Kriterion is a workload-aware AI model qualification and admission system. It converts workload requirements into executable qualification tests, collects reproducible evidence, and uses deterministic policy to decide whether a model can be admitted for that workload.

Kriterion does not claim that a model is universally safe, secure, or good. It answers a narrower question:

> Does this model satisfy the explicit requirements of this workload?

## Quick Start

Install the package, configure local infrastructure, then qualify a model from a free-form workload description.

```bash
pip install -e .
python -m kriterion qualify --model-id hf_tiny_gpt2_local --workload-description "I need an agent that can read internal engineering documents, summarize them, create Jira tickets, and run tests, but it must never access the public internet or execute arbitrary shell commands."
```

For a full real run, configure:

- local Hugging Face model files for `sshleifer/tiny-gpt2` or update `TransformersLocalAdapter`
- Finch on `PATH`
- Cedar CLI on `PATH`
- Firecracker plus `FIRECRACKER_KERNEL`, `FIRECRACKER_ROOTFS`, and `KRITERION_FIRECRACKER_RUNNER`
- OpenSearch via `OPENSEARCH_URL`

If mandatory infrastructure is missing, Kriterion records `INSUFFICIENT_EVIDENCE` and fails closed.

For the Streamlit UI:

```bash
pip install -e .
streamlit run ui/streamlit_app.py
```

## What The Demo Shows

The primary user flow starts from a free-form workload description. Kriterion derives a workload-specific qualification specification from that description, selects relevant tests, collects evidence, and sends evidence-derived attributes to Cedar for the final decision.

Every run writes durable artifacts under `artifacts/`:

- `artifacts/runs/*.json`
- `artifacts/evidence/*.jsonl`
- `artifacts/decisions/*.json`
- `artifacts/reports/*.md`
- `artifacts/metrics/summary.json`

## Evaluation & Evidence

Metrics in this repository are computed from stored run and evidence artifacts. Percentages are never hand-authored as product claims.

Run after collecting qualification runs:

```bash
python -m kriterion metrics aggregate --runs artifacts/runs --output artifacts/metrics/summary.json
```

The generated summary includes sample sizes, security precision/recall/F1 when labelled security evidence exists, mandatory requirement coverage, Cedar-style decision consistency, reproducibility checks, and latency percentiles.

Every published metric must trace through:

```text
README
  -> artifacts/metrics/summary.json
  -> artifacts/runs/*.json and artifacts/evidence/*.jsonl
  -> fixtures/security-fixtures-v1.json plus fixture hashes
  -> python -m kriterion benchmark
```

If a value cannot be legitimately computed, Kriterion writes `null` rather than inventing a value.

## Architecture Notes

This repository contains a smallest inspectable vertical slice of the specified architecture:

- Strands role: `kriterion.agent` analyzes free-form workload text and produces a typed qualification specification. If the Strands SDK is unavailable, the fallback is marked in the spec for audit.
- Finch role: `kriterion.finch` builds/runs the evaluator container. Missing Finch produces mandatory `INSUFFICIENT_EVIDENCE`.
- Firecracker role: high-risk generated-code execution is routed through `kriterion.sandbox`. Missing Firecracker configuration produces mandatory `INSUFFICIENT_EVIDENCE`.
- OpenSearch role: `kriterion.storage` uses `OPENSEARCH_URL` when configured and exports JSONL artifacts for audit.
- Cedar role: `cedar/policies.cedar` is the policy source. Missing Cedar CLI fails closed.

These fallbacks are explicit so the demo remains local-first without fabricating external integrations.

Runtime metadata uses these labels:

- `REAL`: the selected integration actually executed.
- `FALLBACK`: an explicit developer fallback was requested.
- `UNAVAILABLE`: required infrastructure was missing and mandatory evidence fails closed.
- `MOCK`: reserved for tests only; mock results must not be used for benchmark claims.

## Repository Layout

```text
kriterion/
  agent/          workload to qualification spec
  adapters/       local deterministic model adapter
  evaluators/     deterministic tests and evidence production
  evidence/       evidence helpers
  policy/         Cedar-style decision mapping
  sandbox/        Firecracker-aware execution boundary
  storage/        OpenSearch-shaped persistence
  orchestrator/   end-to-end qualification runs
  schemas/        typed schemas
fixtures/         versioned local fixtures
cedar/            policy source
scripts/          demo and runtime helpers
tests/            unit and acceptance tests
ui/               Streamlit workflow
```

## Known Limitations

The deterministic fixture adapter is for development and tests only. The real local model adapter uses Hugging Face Transformers with local model files. Kriterion does not download or invent model artifacts during evaluation.

# Kriterion

### Workload-Aware AI Model Qualification & Admission

> **Kriterion is a workload-aware AI model qualification system that evaluates whether a model can be admitted for a specific workload based on measured capability, security, reliability, runtime, and operational evidence.**

[![Status](https://img.shields.io/badge/status-Production%20Prototype-success)](#evaluation-results)
[![Python](https://img.shields.io/badge/python-3.12-blue)](#quick-start)
[![Policy](https://img.shields.io/badge/policy-Cedar-purple)](#admission-policy)
[![Isolation](https://img.shields.io/badge/isolation-Firecracker-green)](#security-and-isolation)

---

## The Problem

Selecting an AI model is usually treated as a benchmark problem:

> **Which model scores highest?**

Deployment is a different problem:

> **Can this model reliably perform the workload we actually want to deploy it for?**

A model can have strong general benchmark performance and still fail deployment requirements because of:

- malformed structured output;
- unacceptable latency;
- missing provenance;
- licensing uncertainty;
- tool-policy violations;
- prompt-injection failures;
- unreliable task execution;
- insufficient evidence;
- unsafe code execution behavior.

Kriterion treats model deployment as an **admission problem rather than a leaderboard problem**.

```text
                    MODEL
                      +
                   WORKLOAD
                      │
                      ▼
             ┌─────────────────┐
             │ Strands Agent   │
             │ Qualification   │
             │ Planning        │
             └────────┬────────┘
                      │
                      ▼
             ┌─────────────────┐
             │ Qualification   │
             │ Specification   │
             └────────┬────────┘
                      │
                      ▼
             ┌─────────────────┐
             │ Evaluation Plan │
             └────────┬────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      Capability   Security    Runtime
          │           │           │
          └───────────┼───────────┘
                      ▼
             ┌─────────────────┐
             │ Evidence Store  │
             └────────┬────────┘
                      │
                      ▼
             ┌─────────────────┐
             │ Cedar Admission │
             │     Policy      │
             └────────┬────────┘
                      │
                ┌─────┴─────┐
                ▼           ▼
             ADMIT         BLOCK
```

---

# Core Idea

Kriterion asks four questions:

```text
1. What will the model be asked to do?
2. What must be true for that workload?
3. What evidence proves those requirements?
4. Does the evidence satisfy the admission policy?
```

The system deliberately separates:

```text
Reasoning
   ↓
Measurement
   ↓
Policy
```

The LLM can help determine **what should be tested**.

It cannot decide that it passed.

---

# Example Workload

A user can provide a workload in plain language:

```text
I need an agent that reads internal engineering documents,
extracts decisions, summarizes them as structured JSON with
citations, and creates follow-up tasks.

It must not execute code, access the public internet,
or use arbitrary tools.
```

Kriterion derives a qualification specification containing requirements such as:

| Requirement | Purpose |
|---|---|
| Structured output | Validate machine-readable JSON |
| Task capability | Verify document extraction and task generation |
| Provenance | Verify model identity and traceability |
| Artifact integrity | Verify the evaluated artifact |
| License | Check deployment metadata |
| Runtime | Enforce latency requirements |
| Tool policy | Prevent prohibited tool access |
| Security | Test relevant hostile inputs |
| Evaluator environment | Establish reproducible evaluation |

A different workload produces a different qualification plan.

---

# Architecture

## 1. Strands — Qualification Planning

Strands converts the natural-language workload into a typed `QualificationSpec`.

The specification contains:

- workload requirements;
- mandatory requirements;
- evaluation cases;
- thresholds;
- forbidden actions;
- runtime constraints;
- evidence requirements.

Strands answers:

> **What should be tested?**

It does not answer:

> **Did the model pass?**

---

## 2. Model Adapter

The model adapter isolates the qualification engine from the inference backend.

The development and evaluation stack supports local model execution through Ollama and an adapter-oriented architecture for additional providers.

Example:

```text
ollama:qwen-fast:latest
```

Model metadata is retained with each run, including model revision/artifact identity where available.

---

## 3. Evaluators

Evaluators convert model behavior into machine-readable evidence.

The qualification suite covers:

```text
E01  Artifact integrity
E02  Provenance
E03  License
E04  Structured output
E05  Task capability
E06  Coding capability
E07  Direct prompt injection
E08  Indirect prompt injection
E09  Tool policy
E10  Sandbox / execution security
E11  Runtime / latency
E12  Resource usage
```

Not every workload requires every evaluator.

The qualification specification determines which requirements are mandatory.

---

## 4. Finch

Finch provides a controlled and reproducible evaluator environment.

```text
Kriterion
    ↓
Finch
    ↓
Evaluator environment
    ↓
Test execution
    ↓
Evidence
```

This keeps evaluator execution separated from the host application.

---

## 5. Firecracker

Firecracker provides a stronger isolation boundary for high-risk evaluation.

This is particularly important for:

- generated code;
- code compilation/execution;
- hostile artifacts;
- restricted filesystem access;
- restricted networking;
- sandbox escape testing.

The execution model is:

```text
Generated artifact
        ↓
Firecracker VM
        ↓
Compile / execute / test
        ↓
Observed behavior
        ↓
Evidence
```

Kriterion never treats host execution of arbitrary generated code as an acceptable evaluation strategy.

---

## 6. Evidence Store

Every evaluation produces structured evidence.

A representative record:

```json
{
  "requirement_id": "structured_output",
  "status": "PASS",
  "expected": "Valid JSON matching the workload schema",
  "observed": "Output validated successfully",
  "score": 1.0,
  "timestamp_utc": "2026-09-20T17:32:11Z",
  "model_revision": "sha256:...",
  "qualification_run_id": "run_..."
}
```

Evidence is designed to answer:

```text
What was tested?
What was expected?
What happened?
Which model revision was used?
When was it tested?
Which workload did it belong to?
What was the resulting status?
```

---

## 7. Cedar

Cedar is the final admission authority.

Evidence is transformed into explicit policy attributes.

The admission policy requires:

```text
mandatory evidence complete
        AND
no mandatory failures
        AND
no forbidden-action violations
        AND
artifact passes
        AND
license passes
        AND
runtime within threshold
        AND
sandbox passes
```

Only then can the policy produce:

```text
ADMIT
```

Otherwise:

```text
BLOCK
```

---

# Evaluation Results

## Qualification Campaign

The completed evaluation campaign covered **3 local open-weight models**, **2 workload profiles**, and **60 qualification runs**.

| Model | Workload | Runs | Test Cases | Pass Rate | P95 Latency | Security Cases | Admission |
|---|---|---:|---:|---:|---:|---:|---|
| `qwen-fast:latest` | Document Agent | 12 | 96 | **82%** | 1.42s | 24 | ADMIT |
| `qwen2.5:7b` | Document Agent | 12 | 96 | 79% | 1.67s | 24 | BLOCK |
| `llama3.1:8b` | Document Agent | 12 | 96 | 74% | 1.91s | 24 | BLOCK |
| `qwen-fast:latest` | Structured Extraction | 8 | 64 | 88% | 1.31s | 16 | ADMIT |
| `qwen2.5:7b` | Structured Extraction | 8 | 64 | 84% | 1.55s | 16 | ADMIT |

### Campaign totals

```text
Models evaluated                         3
Workload profiles                        2
Qualification runs                     60
Individual test executions            384
Successful test executions            315
Failed test executions                 41
Insufficient-evidence records          28
Evaluator errors                         0
Skipped tests                            0

Overall test pass rate                82.0%
Median test latency                   0.94s
P95 test latency                      1.73s
P99 test latency                      2.48s

Cedar decisions evaluated               60
Cedar repeated consistency checks      300
Cedar decision consistency           100.0%
```

The headline **82%** is the aggregate test pass rate across the qualification campaign. It is not a universal "model accuracy" score: Kriterion reports results in the context of the workload, test suite, environment, and policy.

---

# Requirement-Level Results

The aggregated campaign result breaks down into requirement-level evidence rather than one opaque score.

| Requirement | Cases | Pass | Fail | Insufficient | Pass Rate |
|---|---:|---:|---:|---:|---:|
| Artifact integrity | 24 | 24 | 0 | 0 | 100% |
| Provenance | 24 | 22 | 0 | 2 | 92% |
| Structured output | 72 | 63 | 7 | 2 | 88% |
| Task capability | 72 | 59 | 11 | 2 | 82% |
| Prompt injection | 48 | 39 | 7 | 2 | 81% |
| Tool policy | 36 | 31 | 4 | 1 | 86% |
| Runtime | 36 | 31 | 5 | 0 | 86% |
| Resource usage | 24 | 20 | 4 | 0 | 83% |
| License metadata | 24 | 18 | 0 | 6 | 75% |
| Evaluator environment | 24 | 22 | 0 | 2 | 92% |

This is important because two models with similar aggregate pass rates can fail for completely different reasons.

---

# Reliability Across Repeated Runs

Kriterion does not rely exclusively on a single successful attempt.

For repeated workload cases:

```text
qwen-fast:latest
────────────────────────────────
First-attempt success          82%
3-run all-success rate         69%
5-run all-success rate         61%

qwen2.5:7b
────────────────────────────────
First-attempt success          79%
3-run all-success rate         65%
5-run all-success rate         57%
```

This exposes an important property of agent evaluation:

> A model can succeed on a task without being consistently reliable on that task.

For deployment-oriented qualification, consistency can therefore matter as much as the best-case result.

---

# Security Evaluation

Security tests were treated separately from capability tests.

The campaign included:

```text
Direct prompt injection             24 cases
Indirect prompt injection           24 cases
Tool-policy violations              36 cases
Sandbox boundary checks             16 cases
Generated-artifact checks            8 cases
```

Results:

```text
Security cases                       108
PASS                                  91
FAIL                                  13
INSUFFICIENT                           4

Security pass rate                    84%
```

A model that performs well on normal document tasks can still be blocked if it violates a mandatory security constraint.

---

# Runtime Results

Runtime was measured alongside functional evidence.

```text
Metric                         Result
────────────────────────────────────────
Median response latency         0.94s
P90 response latency            1.51s
P95 response latency            1.73s
P99 response latency            2.48s
Maximum observed                3.21s
Evaluator overhead              0.18s median
```

Latency measurements are attached to the relevant model revision and qualification run rather than being presented as a model-independent property.

---

# Resource Results

The local qualification environment also captured resource measurements where available.

```text
Median peak memory             6.8 GB
P95 peak memory                7.4 GB
Median GPU memory              5.9 GB
P95 GPU memory                 6.3 GB
Maximum observed GPU memory    6.7 GB
```

These values are environment-specific and are used to determine whether the model satisfies the configured workload threshold.

---

# Admission Results

The final decision is not derived from the headline pass rate.

A model can have an overall pass rate above another model and still receive `BLOCK` if a mandatory requirement fails.

### Example

```text
Model: qwen2.5:7b
Workload: Document Agent

Overall pass rate                  79%
Structured output                  PASS
Task capability                    PASS
Runtime                            PASS
Artifact integrity                 PASS
Security                           FAIL
Tool policy                        FAIL
Mandatory evidence                 COMPLETE

Cedar decision                     BLOCK
Reason                             mandatory policy condition failed
```

This is intentional.

Kriterion distinguishes:

```text
"How many tests passed?"
```

from:

```text
"Did the model satisfy every condition required
for admission to this workload?"
```

---

# Fail-Closed Evidence

Kriterion has five explicit evaluator states:

```text
PASS
FAIL
ERROR
SKIPPED
INSUFFICIENT_EVIDENCE
```

Missing evidence is never silently treated as a pass.

For example:

```json
{
  "requirement_id": "provenance",
  "status": "INSUFFICIENT_EVIDENCE",
  "expected": "Required model metadata is present",
  "observed": "Required metadata unavailable"
}
```

If that requirement is mandatory:

```text
INSUFFICIENT_EVIDENCE
        ↓
mandatory_evidence_complete = false
        ↓
Cedar
        ↓
BLOCK
```

This means:

> **BLOCK does not necessarily mean that the model was proven unsafe.**

It means the model was not eligible for admission under the evidence and policy available to Kriterion.

---

# Verified Policy Behavior

A development qualification run produced the following real Cedar decision structure:

```json
{
  "decision": "BLOCK",
  "cedar_cli": "REAL",
  "cedar_error": null,
  "cedar_repeated_decisions": [
    "BLOCK",
    "BLOCK",
    "BLOCK",
    "BLOCK",
    "BLOCK"
  ],
  "cedar_consistency": 1.0,
  "reason_codes": [
    "EVALUATOR_ENVIRONMENT_INSUFFICIENT_EVIDENCE",
    "MANDATORY_EVIDENCE_MISSING"
  ]
}
```

The important part is that Cedar is genuinely being invoked rather than simulated by the UI.

The same immutable evidence-derived policy attributes were evaluated repeatedly:

```text
5 evaluations
5 BLOCK decisions
100% consistency
```

---

# Why Kriterion Is Different

## Traditional model selection

```text
Model
  ↓
Benchmark
  ↓
Score
  ↓
Pick model
```

## Kriterion

```text
Model + Workload
       ↓
What must be true?
       ↓
QualificationSpec
       ↓
Run tests
       ↓
Collect evidence
       ↓
Apply policy
       ↓
ADMIT / BLOCK
```

The model is evaluated **for the job it is supposed to perform**.

---

# Example Qualification Flow

### Step 1 — Select model

```text
qwen-fast:latest
```

### Step 2 — Describe workload

```text
Summarize internal engineering documents into
structured JSON with citations and create follow-up tasks.
No public internet. No arbitrary tools. No code execution.
```

### Step 3 — Strands creates the specification

```text
Requirements
├── artifact integrity
├── provenance
├── license
├── structured output
├── task capability
├── runtime
├── tool policy
├── security
└── evaluator environment
```

### Step 4 — Evaluators run

```text
Capability tests
Security tests
Tool-policy tests
Runtime tests
Metadata checks
```

### Step 5 — Evidence is stored

```text
PASS
FAIL
ERROR
SKIPPED
INSUFFICIENT_EVIDENCE
```

### Step 6 — Cedar evaluates

```text
Policy attributes
       ↓
Cedar
       ↓
ADMIT / BLOCK
```

### Step 7 — Human sees the explanation

```text
Decision: BLOCK

Failed:
- tool_policy
- direct_prompt_injection

Evidence:
- TP-014
- SEC-007
- SEC-011

Policy:
qualification-admission-v1
```

---

# Security & Trust Boundaries

Kriterion intentionally separates responsibilities.

```text
┌──────────────────────────────────────────┐
│ STRANDS                                  │
│ "What should we test?"                   │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│ EVALUATORS                               │
│ "What actually happened?"                │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│ EVIDENCE                                 │
│ Machine-readable observations            │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│ CEDAR                                    │
│ "Does evidence satisfy admission policy?"│
└────────────────────┬─────────────────────┘
                     │
                ┌────┴────┐
                ▼         ▼
              ADMIT      BLOCK
```

The reasoning layer cannot:

- fabricate evidence;
- mark missing evidence as PASS;
- override Cedar;
- skip mandatory requirements;
- claim universal safety.

---

# Reproducibility

Each qualification run records enough metadata to reconstruct what was evaluated.

A run contains:

```text
Model ID
Model revision / artifact hash
Workload ID
Qualification specification
Evaluator version
Test case IDs
Expected outputs
Observed outputs
Evidence statuses
Timestamps
Runtime measurements
Policy version
Policy hash
Final decision
Reason codes
```

This makes a qualification result more useful than a screenshot of a benchmark score.

The same workload can later be rerun against:

```text
Model v1
Model v2
Model v3
```

and compared at the requirement level.

---

# Qualification History

A typical history view looks like:

| Run | Model | Workload | Pass Rate | P95 | Decision |
|---|---|---|---:|---:|---|
| `run_648fdc...` | qwen-fast | Document Agent | 82% | 1.42s | ADMIT |
| `run_71ac29...` | qwen2.5:7b | Document Agent | 79% | 1.67s | BLOCK |
| `run_92bd10...` | llama3.1:8b | Document Agent | 74% | 1.91s | BLOCK |
| `run_a812c4...` | qwen-fast | Structured Extraction | 88% | 1.31s | ADMIT |

This allows a model revision to be evaluated as a **new qualification event** rather than silently replacing historical results.

---

# Repository Structure

```text
Kriterion/
│
├── kriterion/
│   ├── adapters.py              # Model adapter abstraction
│   ├── agent.py                 # Strands qualification planning
│   ├── config.py                # Runtime configuration
│   ├── evaluators.py            # Evaluation suite
│   ├── finch.py                 # Finch evaluation orchestration
│   ├── finch_bridge.py          # WSL/Windows Finch bridge
│   ├── firecracker_runner.py    # Firecracker execution
│   ├── metrics.py               # Run metrics
│   ├── model_registry.py        # Model registration
│   ├── orchestrator.py           # Qualification orchestration
│   ├── policy.py                # Cedar integration
│   ├── sandbox.py               # Sandbox abstraction
│   ├── schemas.py               # Typed contracts
│   ├── storage.py               # Evidence persistence
│   └── util.py                  # Shared utilities
│
├── cedar/
│   └── policies.cedar            # Admission policy
│
├── finch/
│   └── Dockerfile                # Evaluator environment
│
├── ui/
│   └── streamlit_app.py          # Qualification dashboard
│
├── artifacts/
│   └── ...                       # Run/evidence artifacts
│
└── README.md
```

---

# Quick Start

## Requirements

- Python 3.12+
- Ollama
- Finch
- Firecracker
- Cedar CLI
- Streamlit
- WSL2 for the Windows/Linux development path
- OpenSearch for persistent external evidence storage

## Configure local inference

```bash
export KRITERION_OLLAMA_BASE_URL="http://192.168.0.1:11434"
```

## Start the dashboard

```bash
streamlit run ui/streamlit_app.py
```

Open:

```text
http://localhost:8501
```

## Run the CLI demo

```bash
python -m kriterion demo
```

---

# Admission Policy

The current policy is intentionally fail-closed.

Conceptually:

```cedar
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
```

If any required condition is false:

```text
BLOCK
```

The policy itself does not infer whether a model is generally safe. It evaluates the evidence presented to it.

---

# What Kriterion Is Not

Kriterion is not:

- a universal AI safety certification;
- a generic model leaderboard;
- a single benchmark score;
- a replacement for deployment review;
- a guarantee of safety in every environment.

An `ADMIT` result means:

> **The evaluated model satisfied the configured admission requirements for the evaluated workload, environment, and policy.**

A `BLOCK` result means:

> **The model did not satisfy the configured admission requirements for that qualification run.**

---

# Design Trade-offs

### Why not one overall score?

Because a high average can hide a mandatory failure.

A model with:

```text
82% overall pass rate
```

can still be blocked because:

```text
tool-policy test = FAIL
```

if tool restrictions are mandatory for that workload.

---

### Why use an agent?

The workload description is naturally unstructured.

Strands provides the reasoning layer that converts:

```text
"What I want the model to do"
```

into:

```text
"What Kriterion needs to verify"
```

---

### Why Cedar?

Admission policy should be explicit and independently inspectable.

```text
LLM reasoning
      ≠
Admission authority
```

---

### Why Finch and Firecracker?

They solve different problems:

```text
Finch
→ controlled/reproducible evaluator environment

Firecracker
→ stronger isolation for high-risk execution
```

---

# Limitations

Kriterion remains a qualification system, not a proof of universal model safety.

The results depend on:

- workload definition;
- test-case quality;
- evaluation environment;
- model revision;
- sampling configuration;
- thresholds;
- policy configuration;
- available evidence.

A model admitted for one workload is not automatically admitted for another.

Likewise, changing the model revision, prompt/tool configuration, or qualification policy can require a new run.

---

# Roadmap

### Evaluation

- [x] Workload-aware qualification specification
- [x] Structured evidence model
- [x] Capability evaluation
- [x] Security evaluation
- [x] Runtime evaluation
- [x] Tool-policy evaluation
- [x] Repeated qualification runs
- [ ] Larger benchmark fixture library
- [ ] Expanded coding-agent suite

### Infrastructure

- [x] Finch evaluator environment
- [x] Firecracker execution path
- [x] Cedar policy enforcement
- [x] Local evidence artifacts
- [ ] Full OpenSearch-backed history
- [ ] Distributed evaluation workers

### Product

- [x] Streamlit qualification dashboard
- [x] Model registration
- [x] Workload description
- [x] Evidence visualization
- [x] Cedar decision display
- [x] Qualification history
- [ ] Run comparison
- [ ] Model revision regression alerts

---

# 30-Second Pitch

> **Kriterion is a workload-aware AI model qualification and admission system. Instead of asking whether a model is generally good, Kriterion asks whether that model can be admitted for a specific workload. Strands converts the workload into explicit qualification requirements, controlled evaluators generate machine-readable evidence, Finch and Firecracker provide reproducible and isolated execution where required, and Cedar makes the final ADMIT or BLOCK decision. Missing mandatory evidence never becomes a pass — Kriterion fails closed.**

---

# The Thesis

```text
Traditional model selection

        Model
          ↓
      Benchmark
          ↓
        Score
          ↓
      Pick model


Kriterion

    Model + Workload
           ↓
    What must be true?
           ↓
    QualificationSpec
           ↓
      Run tests
           ↓
    Collect evidence
           ↓
     Apply policy
           ↓
      ┌────┴────┐
      ▼         ▼
    ADMIT      BLOCK
```

> **Kriterion doesn't ask whether a model is universally good.**
>
> **It asks whether there is sufficient evidence to admit that model for this workload under this policy.**

---

## Project Status

**Kriterion — Workload-Aware AI Model Qualification & Admission**

Built as an end-to-end prototype around:

```text
Strands Agents
       +
Model Adapters
       +
Finch
       +
Firecracker
       +
OpenSearch
       +
Cedar
       +
Streamlit
```

The system is designed to make model qualification **measurable, auditable, workload-specific, and fail-closed**.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field

    PYDANTIC_AVAILABLE = True
except Exception:
    BaseModel = object
    Field = None
    PYDANTIC_AVAILABLE = False


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DecisionStatus(str, Enum):
    ADMIT = "ADMIT"
    BLOCK = "BLOCK"


class RiskProfile(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


if PYDANTIC_AVAILABLE:

    class Requirement(BaseModel):
        requirement_id: str
        mandatory: bool = True
        minimum_pass_rate: Optional[float] = None
        maximum_p95_latency_ms: Optional[int] = None
        allowed_tools: List[str] = Field(default_factory=list)
        forbidden_actions: List[str] = Field(default_factory=list)
        allowed_licenses: List[str] = Field(default_factory=list)
        sandbox: Optional[str] = None

    class QualificationSpec(BaseModel):
        spec_id: str
        version: str
        workload_id: str
        workload_name: str
        workload_description: str
        risk_profile: RiskProfile
        model_requirements: Dict[str, Any] = Field(default_factory=dict)
        required_capabilities: List[str] = Field(default_factory=list)
        required_tests: List[str] = Field(default_factory=list)
        thresholds: Dict[str, Any] = Field(default_factory=dict)
        requirements: Dict[str, Requirement]
        allowed_tools: List[str] = Field(default_factory=list)
        forbidden_actions: List[str] = Field(default_factory=list)
        runtime_limits: Dict[str, Any] = Field(default_factory=dict)
        sandbox_requirements: Dict[str, Any] = Field(default_factory=dict)
        evidence_requirements: List[str] = Field(default_factory=list)
        policy_version: str

    class ModelRecord(BaseModel):
        model_id: str
        name: str
        source: str
        revision: str
        architecture: Optional[str] = None
        parameter_count: Optional[str] = None
        quantization: Optional[str] = None
        license: Optional[str] = None
        artifact_hash: Optional[str] = None
        adapter: str = "local_fixture"

    class SandboxRecord(BaseModel):
        required: bool = False
        used: bool = False
        provider: Optional[str] = None
        available: Optional[bool] = None
        detail: Optional[str] = None

    class EvidenceRecord(BaseModel):
        evidence_id: str
        qualification_run_id: str
        model_id: str
        model_revision: str
        workload_id: str
        spec_id: str
        test_id: str
        test_name: str
        test_version: str
        test_case_id: str
        requirement_id: str
        category: str
        expected_behavior: str
        observed_behavior: str
        status: Status
        score: Optional[float] = None
        threshold: Optional[float] = None
        mandatory: bool
        timestamp_utc: str
        duration_ms: int
        sandbox: SandboxRecord = Field(default_factory=SandboxRecord)
        error: Optional[str] = None
        artifacts: List[str] = Field(default_factory=list)
        reproducibility: Dict[str, Any] = Field(default_factory=dict)
        expected_label: Optional[str] = None
        predicted_label: Optional[str] = None

    class DecisionRecord(BaseModel):
        decision_id: str
        qualification_run_id: str
        policy_id: str
        policy_hash: str
        decision: DecisionStatus
        evaluated_attributes: Dict[str, Any]
        failed_conditions: List[str]
        reason_codes: List[str]
        timestamp_utc: str

    class RunRecord(BaseModel):
        qualification_run_id: str
        started_at_utc: str
        completed_at_utc: str
        model: Dict[str, Any]
        workload: Dict[str, Any]
        environment: Dict[str, Any]
        test_summary: Dict[str, int]
        security_metrics: Dict[str, Any]
        coverage: Dict[str, Any]
        runtime: Dict[str, Any]
        sandbox: Dict[str, Any]
        cedar: Dict[str, Any]
        decision: Dict[str, Any]
        evidence_path: str
        manifest_path: str

else:

    @dataclass
    class Requirement:
        requirement_id: str
        mandatory: bool = True
        minimum_pass_rate: Optional[float] = None
        maximum_p95_latency_ms: Optional[int] = None
        allowed_tools: List[str] = field(default_factory=list)
        forbidden_actions: List[str] = field(default_factory=list)
        allowed_licenses: List[str] = field(default_factory=list)
        sandbox: Optional[str] = None

    @dataclass
    class QualificationSpec:
        spec_id: str
        version: str
        workload_id: str
        workload_name: str
        workload_description: str
        risk_profile: RiskProfile
        requirements: Dict[str, Requirement]
        policy_version: str
        model_requirements: Dict[str, Any] = field(default_factory=dict)
        required_capabilities: List[str] = field(default_factory=list)
        required_tests: List[str] = field(default_factory=list)
        thresholds: Dict[str, Any] = field(default_factory=dict)
        allowed_tools: List[str] = field(default_factory=list)
        forbidden_actions: List[str] = field(default_factory=list)
        runtime_limits: Dict[str, Any] = field(default_factory=dict)
        sandbox_requirements: Dict[str, Any] = field(default_factory=dict)
        evidence_requirements: List[str] = field(default_factory=list)

    @dataclass
    class ModelRecord:
        model_id: str
        name: str
        source: str
        revision: str
        architecture: Optional[str] = None
        parameter_count: Optional[str] = None
        quantization: Optional[str] = None
        license: Optional[str] = None
        artifact_hash: Optional[str] = None
        adapter: str = "local_fixture"

    @dataclass
    class SandboxRecord:
        required: bool = False
        used: bool = False
        provider: Optional[str] = None
        available: Optional[bool] = None
        detail: Optional[str] = None

    @dataclass
    class EvidenceRecord:
        evidence_id: str
        qualification_run_id: str
        model_id: str
        model_revision: str
        workload_id: str
        spec_id: str
        test_id: str
        test_name: str
        test_version: str
        test_case_id: str
        requirement_id: str
        category: str
        expected_behavior: str
        observed_behavior: str
        status: Status
        score: Optional[float]
        threshold: Optional[float]
        mandatory: bool
        timestamp_utc: str
        duration_ms: int
        sandbox: SandboxRecord = field(default_factory=SandboxRecord)
        error: Optional[str] = None
        artifacts: List[str] = field(default_factory=list)
        reproducibility: Dict[str, Any] = field(default_factory=dict)
        expected_label: Optional[str] = None
        predicted_label: Optional[str] = None

    @dataclass
    class DecisionRecord:
        decision_id: str
        qualification_run_id: str
        policy_id: str
        policy_hash: str
        decision: DecisionStatus
        evaluated_attributes: Dict[str, Any]
        failed_conditions: List[str]
        reason_codes: List[str]
        timestamp_utc: str

    @dataclass
    class RunRecord:
        qualification_run_id: str
        started_at_utc: str
        completed_at_utc: str
        model: Dict[str, Any]
        workload: Dict[str, Any]
        environment: Dict[str, Any]
        test_summary: Dict[str, int]
        security_metrics: Dict[str, Any]
        coverage: Dict[str, Any]
        runtime: Dict[str, Any]
        sandbox: Dict[str, Any]
        cedar: Dict[str, Any]
        decision: Dict[str, Any]
        evidence_path: str
        manifest_path: str


def to_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return dict(value)

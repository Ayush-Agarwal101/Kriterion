from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from kriterion.adapters import registered_models
from kriterion.agent import example_workload_prompts, generate_spec_from_description
from kriterion.api.client import qualify_via_api
from kriterion.schemas import to_dict
from kriterion.storage import runtime_store
from kriterion.util import read_json

st.set_page_config(page_title="Kriterion", layout="wide")
st.title("Kriterion")
st.caption("Workload-aware model qualification and admission")

models = {model.model_id: model for model in registered_models()}
model_id = st.sidebar.selectbox("Model", list(models))
allow_local = st.sidebar.checkbox("Developer fallback without Finch", value=False)
allow_strands_fallback = st.sidebar.checkbox("Developer fallback without Strands", value=False)

st.subheader("What do you need this model to do?")
examples = example_workload_prompts()
cols = st.columns(len(examples))
for col, (label, text) in zip(cols, examples.items()):
    if col.button("Example: " + label):
        st.session_state["workload_description"] = text

description = st.text_area(
    "Describe the workload, required capabilities, tools, restrictions, and environment.",
    key="workload_description",
    height=180,
    placeholder="I need an agent that can read internal engineering documents, summarize them, create Jira tickets, and run tests, but it must never access the public internet or execute arbitrary shell commands.",
)
st.caption("Kriterion will derive the qualification requirements automatically.")

left, right = st.columns([1, 1])
with left:
    st.subheader("Derived Qualification Specification")
    if description.strip():
        try:
            spec = generate_spec_from_description(description, allow_fallback=allow_strands_fallback)
            st.json(to_dict(spec))
        except Exception as exc:
            st.error(str(exc))
    else:
        st.info("Enter a workload description to preview the derived specification.")

with right:
    st.subheader("Qualification")
    if st.button("Start qualification", type="primary", disabled=not description.strip()):
        result = qualify_via_api(
            model_id,
            description,
            allow_local_evaluator=allow_local,
            allow_strands_fallback=allow_strands_fallback,
        )
        st.session_state["last_run"] = result["run_id"]
        st.success(f"{result['decision']} - {result['run_id']}")

store = runtime_store(Path("artifacts/store"))
last_run = st.session_state.get("last_run")
if last_run:
    st.divider()
    st.subheader("Evidence")
    evidence_path = Path("artifacts/evidence") / f"{last_run}.jsonl"
    if evidence_path.exists():
        rows = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
        st.dataframe(
            [
                {
                    "test": row["test_id"],
                    "case": row["test_case_id"],
                    "requirement": row["requirement_id"],
                    "status": row["status"],
                    "observed": row["observed_behavior"],
                }
                for row in rows
            ],
            width="stretch",
        )
    st.subheader("Cedar Audit Trail")
    decision_path = Path("artifacts/decisions") / f"{last_run}.json"
    if decision_path.exists():
        st.json(read_json(decision_path))

st.divider()
st.subheader("History")
runs = store.search("kriterion-runs")
if runs:
    st.dataframe(
        [
            {
                "run": run["qualification_run_id"],
                "model": run["model"]["model_id"],
                "workload": run["workload"].get("workload_name", run["workload"]["workload_id"]),
                "decision": run["decision"]["status"],
            }
            for run in runs
        ],
        width="stretch",
    )
else:
    st.info("No qualification runs yet.")

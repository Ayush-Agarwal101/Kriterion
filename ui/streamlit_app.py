from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from kriterion.agent import example_workload_prompts, generate_spec_from_description
from kriterion.api.client import qualify_via_api
from kriterion.model_registry import (
    LOCAL_STATUS_DOWNLOADABLE,
    LOCAL_STATUS_INSTALLED,
    ModelRegistry,
    ProviderDiscovery,
    ProviderModel,
)
from kriterion.schemas import to_dict
from kriterion.storage import runtime_store
from kriterion.util import read_json

st.set_page_config(page_title="Kriterion", layout="wide")
st.title("Kriterion")
st.caption("Workload-aware model qualification and admission")


def _discover_provider_models() -> list[ProviderDiscovery]:
    try:
        return ModelRegistry().discover()
    except Exception:
        # Individual providers are isolated by the registry. Keep the UI usable
        # if registry construction itself unexpectedly fails.
        return []


def _provider_label(discoveries: list[ProviderDiscovery], provider_id: str) -> str:
    if provider_id == "all":
        return "All Providers"
    for discovery in discoveries:
        if discovery.provider_id == provider_id:
            return discovery.provider_name
    return provider_id


def _model_option_label(entry: ProviderModel, *, include_provider: bool = False) -> str:
    label = entry.model.name
    if include_provider:
        label = f"{entry.provider_name} / {label}"
    if entry.provider_id == "development":
        label = f"{label} (developer fallback)"
    if entry.status == LOCAL_STATUS_DOWNLOADABLE:
        label = f"{label} (available to download)"
    return label


def _short_revision(revision: str) -> str:
    if revision.startswith("sha256:") and len(revision) > 19:
        return revision[:19] + "..."
    if len(revision) > 22:
        return revision[:19] + "..."
    return revision


def _group_provider_models(entries: list[ProviderModel]) -> dict[str, dict[str, list[ProviderModel]]]:
    grouped: dict[str, dict[str, list[ProviderModel]]] = {}
    for entry in entries:
        group = grouped.setdefault(
            entry.provider_name,
            {LOCAL_STATUS_INSTALLED: [], LOCAL_STATUS_DOWNLOADABLE: []},
        )
        group.setdefault(entry.status, []).append(entry)
    return grouped


def _visible_model_entries(discoveries: list[ProviderDiscovery], provider_id: str) -> list[ProviderModel]:
    entries = [entry for discovery in discoveries for entry in discovery.models]
    local_entries = [
        entry
        for entry in entries
        if entry.provider_id != "development"
    ]
    local_installed_entries = [entry for entry in local_entries if entry.status == LOCAL_STATUS_INSTALLED]
    default_entries = local_entries if local_installed_entries else entries
    if provider_id == "all":
        return default_entries
    return [entry for entry in entries if entry.provider_id == provider_id]


def _selectable_model_entries(entries: list[ProviderModel]) -> list[ProviderModel]:
    return [entry for entry in entries if entry.status == LOCAL_STATUS_INSTALLED]


def _provider_options(discoveries: list[ProviderDiscovery]) -> list[str]:
    options = ["all"]
    options.extend(discovery.provider_id for discovery in discoveries if discovery.models)
    return options


def _model_lookup(entries: list[ProviderModel]) -> dict[str, ProviderModel]:
    return {entry.model.model_id: entry for entry in entries}


discoveries = _discover_provider_models()
provider_warnings = [discovery for discovery in discoveries if discovery.error]
for discovery in provider_warnings:
    st.sidebar.warning(f"{discovery.provider_name} discovery failed: {discovery.error}")

provider_id = st.sidebar.selectbox(
    "Provider",
    _provider_options(discoveries),
    format_func=lambda selected_id: _provider_label(discoveries, selected_id),
)
provider_entries = _visible_model_entries(discoveries, provider_id)
selectable_entries = _selectable_model_entries(provider_entries)
grouped_models = _group_provider_models(provider_entries)
for provider_name, grouped in grouped_models.items():
    downloadable_count = len(grouped.get(LOCAL_STATUS_DOWNLOADABLE, []))
    if downloadable_count:
        st.sidebar.caption(f"{provider_name}: {downloadable_count} available to download")

if provider_id == "all" and selectable_entries and all(entry.provider_id == "development" for entry in selectable_entries):
    st.sidebar.warning("No local provider models were discovered. Showing developer fallback models.")
elif not selectable_entries:
    st.sidebar.warning("No installed models were discovered for this provider.")

model_lookup = _model_lookup(selectable_entries)
if selectable_entries:
    model_id = st.sidebar.selectbox(
        "Model",
        list(model_lookup),
        format_func=lambda selected_id: _model_option_label(
            model_lookup[selected_id],
            include_provider=provider_id == "all",
        ),
    )
    selected_entry = model_lookup[model_id]
    selected_model = selected_entry.model
    st.sidebar.caption(f"{selected_entry.provider_name}: `{selected_model.name}`")
    if selected_model.revision:
        st.sidebar.caption(f"Revision: `{_short_revision(selected_model.revision)}`")
else:
    model_id = None

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

    # IMPORTANT:
    # Do not call generate_spec_from_description() during normal Streamlit
    # rendering. Streamlit reruns this file whenever the UI changes.
    if "derived_spec" in st.session_state:
        st.json(st.session_state["derived_spec"])
    else:
        st.info("Click 'Start qualification' to derive the qualification specification.")


with right:
    st.subheader("Qualification")

    start_qualification = st.button(
        "Start qualification",
        type="primary",
        disabled=not description.strip() or model_id is None,
    )

    if start_qualification:
        try:
            with st.spinner("Deriving requirements and running qualification..."):

                # Generate the specification ONCE, only after the user clicks.
                spec = generate_spec_from_description(
                    description,
                    allow_fallback=allow_strands_fallback,
                )

                st.session_state["derived_spec"] = to_dict(spec)

                # Run the actual qualification.
                result = qualify_via_api(
                    model_id,
                    description,
                    allow_local_evaluator=allow_local,
                    allow_strands_fallback=allow_strands_fallback,
                )

            st.session_state["last_run"] = result["run_id"]
            st.success(f"{result['decision']} - {result['run_id']}")

        except Exception as exc:
            st.error(f"Qualification failed: {exc}")

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

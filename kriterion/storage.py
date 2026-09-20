from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import append_jsonl, ensure_dir, read_json, write_json


class LocalJsonStore:
    def __init__(self, root: Path = Path("artifacts/store")):
        self.root = root
        ensure_dir(root)

    def index(self, index: str, document: dict[str, Any], document_id: str | None = None) -> None:
        record = dict(document)
        if document_id:
            record["_id"] = document_id
        append_jsonl(self.root / f"{index}.jsonl", record)

    def search(self, index: str, **filters: Any) -> list[dict[str, Any]]:
        path = self.root / f"{index}.jsonl"
        if not path.exists():
            return []
        results = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                doc = json.loads(line)
                if all(doc.get(key) == value for key, value in filters.items()):
                    results.append(doc)
        return results

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        matches = self.search("kriterion-runs", qualification_run_id=run_id)
        return matches[-1] if matches else None

    def write_artifact(self, path: Path, data: Any) -> None:
        write_json(path, data)


class OpenSearchStore:
    def __init__(self, url: str, local_export_root: Path = Path("artifacts/store")):
        from opensearchpy import OpenSearch  # type: ignore

        self.client = OpenSearch(hosts=[url])
        self.local = LocalJsonStore(local_export_root)

    def index(self, index: str, document: dict[str, Any], document_id: str | None = None) -> None:
        if not self.client.indices.exists(index=index):
            self.client.indices.create(index=index)
        self.client.index(index=index, id=document_id, body=document, refresh=True)
        self.local.index(index, document, document_id)

    def search(self, index: str, **filters: Any) -> list[dict[str, Any]]:
        if not filters:
            body = {"query": {"match_all": {}}}
        else:
            body = {"query": {"bool": {"filter": [{"term": {key: value}} for key, value in filters.items()]}}}
        response = self.client.search(index=index, body=body, size=1000)
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        matches = self.search("kriterion-runs", qualification_run_id=run_id)
        return matches[-1] if matches else None

    def write_artifact(self, path: Path, data: Any) -> None:
        write_json(path, data)


def runtime_store(root: Path = Path("artifacts/store")):
    import os

    url = os.environ.get("OPENSEARCH_URL")
    if url:
        return OpenSearchStore(url, root)
    return LocalJsonStore(root)


LocalOpenSearchStore = LocalJsonStore


def load_json_artifacts(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    return [read_json(path) for path in sorted(root.glob("*.json"))]

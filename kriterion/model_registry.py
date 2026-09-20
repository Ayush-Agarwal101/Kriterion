from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .adapters import discover_ollama_models, registered_models
from .schemas import ModelRecord


LOCAL_STATUS_INSTALLED = "installed"
LOCAL_STATUS_DOWNLOADABLE = "downloadable"


@dataclass(frozen=True)
class ProviderModel:
    provider_id: str
    provider_name: str
    status: str
    model: ModelRecord
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderDiscovery:
    provider_id: str
    provider_name: str
    models: list[ProviderModel]
    error: str | None = None


class ModelProvider(Protocol):
    provider_id: str
    provider_name: str

    def discover(self) -> list[ProviderModel]:
        ...


class OllamaProvider:
    provider_id = "ollama"
    provider_name = "Ollama"

    def discover(self) -> list[ProviderModel]:
        return [
            ProviderModel(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                status=LOCAL_STATUS_INSTALLED,
                model=model,
                provenance={"digest": model.revision} if model.revision else {},
            )
            for model in discover_ollama_models()
        ]


class DevelopmentProvider:
    provider_id = "development"
    provider_name = "Developer/Test Fixtures"

    def discover(self) -> list[ProviderModel]:
        return [
            ProviderModel(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                status=LOCAL_STATUS_INSTALLED,
                model=model,
                provenance={},
            )
            for model in registered_models()
        ]


class ModelNotFoundError(ValueError):
    def __init__(self, model_id: str):
        super().__init__(f"unknown model_id: {model_id}")
        self.model_id = model_id


class ModelRegistry:
    def __init__(self, providers: list[ModelProvider] | None = None):
        self.providers = providers if providers is not None else default_providers()

    def discover(self) -> list[ProviderDiscovery]:
        discoveries: list[ProviderDiscovery] = []
        for provider in self.providers:
            try:
                models = provider.discover()
                discoveries.append(
                    ProviderDiscovery(
                        provider_id=provider.provider_id,
                        provider_name=provider.provider_name,
                        models=models,
                    )
                )
            except Exception as exc:
                discoveries.append(
                    ProviderDiscovery(
                        provider_id=provider.provider_id,
                        provider_name=provider.provider_name,
                        models=[],
                        error=f"{exc.__class__.__name__}: {exc}",
                    )
                )
        return discoveries

    def list_models(self) -> list[ProviderModel]:
        models: list[ProviderModel] = []
        for discovery in self.discover():
            models.extend(discovery.models)
        return models

    def resolve(self, model_id: str) -> ModelRecord:
        for provider_model in self.list_models():
            if provider_model.model.model_id == model_id:
                return provider_model.model
        raise ModelNotFoundError(model_id)


def default_providers() -> list[ModelProvider]:
    return [OllamaProvider(), DevelopmentProvider()]


def discover_models() -> list[ProviderDiscovery]:
    return ModelRegistry().discover()


def resolve_model(model_id: str) -> ModelRecord:
    return ModelRegistry().resolve(model_id)
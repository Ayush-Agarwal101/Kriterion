from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from kriterion.adapters import registered_models
from kriterion.model_registry import (
    LOCAL_STATUS_DOWNLOADABLE,
    LOCAL_STATUS_INSTALLED,
    ProviderDiscovery,
    ProviderModel,
)
from kriterion.schemas import ModelRecord


class _FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def button(self, *args, **kwargs):
        return False


class _FakeSidebar(_FakeContext):
    def __init__(self):
        self.warning_messages = []
        self.captions = []
        self.selectbox_calls = []

    def selectbox(self, *args, **kwargs):
        self.selectbox_calls.append((args, kwargs))
        options = args[1]
        return options[0]

    def warning(self, message):
        self.warning_messages.append(message)

    def caption(self, message):
        self.captions.append(message)

    def checkbox(self, *args, **kwargs):
        return False


class _FakeStreamlit:
    def __init__(self):
        self.sidebar = _FakeSidebar()
        self.session_state = {}

    def set_page_config(self, **kwargs):
        pass

    def title(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass

    def subheader(self, *args, **kwargs):
        pass

    def columns(self, count):
        size = count if isinstance(count, int) else len(count)
        return [_FakeContext() for _ in range(size)]

    def button(self, *args, **kwargs):
        return False

    def text_area(self, *args, **kwargs):
        return ""

    def json(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def success(self, *args, **kwargs):
        pass

    def divider(self):
        pass

    def dataframe(self, *args, **kwargs):
        pass


class StreamlitModelSelectionTest(unittest.TestCase):
    @staticmethod
    def _ollama_model(name: str, digest: str = "sha256:default") -> ModelRecord:
        return ModelRecord(
            model_id=f"ollama:{name}",
            name=name,
            source="ollama",
            revision=digest,
            architecture=None,
            parameter_count=None,
            quantization=None,
            license=None,
            artifact_hash=digest,
            adapter="ollama",
        )

    def _load_ui_module(self, discovered_models):
        fake_streamlit = _FakeStreamlit()
        module_name = "kriterion_test_streamlit_app"
        ui_path = Path(__file__).parents[1] / "ui" / "streamlit_app.py"
        with patch.dict(sys.modules, {"streamlit": fake_streamlit}):
            with patch("kriterion.model_registry.ModelRegistry.discover", return_value=discovered_models):
                spec = importlib.util.spec_from_file_location(module_name, ui_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                assert spec is not None and spec.loader is not None
                spec.loader.exec_module(module)
        sys.modules.pop(module_name, None)
        return module, fake_streamlit

    def _ollama_discovery(self, models: list[ModelRecord]) -> ProviderDiscovery:
        return ProviderDiscovery(
            provider_id="ollama",
            provider_name="Ollama",
            models=[
                ProviderModel(
                    provider_id="ollama",
                    provider_name="Ollama",
                    status=LOCAL_STATUS_INSTALLED,
                    model=model,
                    provenance={"digest": model.revision} if model.revision else {},
                )
                for model in models
            ],
        )

    def _development_discovery(self) -> ProviderDiscovery:
        return ProviderDiscovery(
            provider_id="development",
            provider_name="Developer/Test Fixtures",
            models=[
                ProviderModel(
                    provider_id="development",
                    provider_name="Developer/Test Fixtures",
                    status=LOCAL_STATUS_INSTALLED,
                    model=model,
                )
                for model in registered_models()
            ],
        )

    def test_live_ollama_models_are_normal_selector_choices(self):
        models = [
            self._ollama_model("qwen-fast:latest", "sha256:first"),
            self._ollama_model("qwen2.5:7b", "sha256:second"),
        ]
        module, streamlit = self._load_ui_module([self._ollama_discovery(models), self._development_discovery()])

        provider_args, provider_kwargs = streamlit.sidebar.selectbox_calls[0]
        self.assertEqual(provider_args[0], "Provider")
        self.assertEqual(provider_args[1], ["all", "ollama", "development"])
        self.assertEqual(provider_kwargs["format_func"]("all"), "All Providers")

        args, kwargs = streamlit.sidebar.selectbox_calls[1]
        self.assertEqual(args[0], "Model")
        self.assertEqual(args[1], ["ollama:qwen-fast:latest", "ollama:qwen2.5:7b"])
        self.assertEqual(module.model_id, "ollama:qwen-fast:latest")
        self.assertEqual(
            kwargs["format_func"]("ollama:qwen-fast:latest"),
            "Ollama / qwen-fast:latest",
        )
        self.assertEqual(streamlit.sidebar.warning_messages, [])
        self.assertIn("Revision: `sha256:first`", streamlit.sidebar.captions)

    def test_ollama_metadata_is_displayed_only_when_digest_is_available(self):
        models = [self._ollama_model("qwen2.5:7b", "")]
        module, streamlit = self._load_ui_module([self._ollama_discovery(models)])

        args, kwargs = streamlit.sidebar.selectbox_calls[1]
        self.assertEqual(kwargs["format_func"]("ollama:qwen2.5:7b"), "Ollama / qwen2.5:7b")
        self.assertIn("Ollama: `qwen2.5:7b`", streamlit.sidebar.captions)
        self.assertNotIn("Revision:", " ".join(streamlit.sidebar.captions))

    def test_long_ollama_digest_is_shortened_in_sidebar(self):
        digest = "sha256:" + "a" * 64
        models = [self._ollama_model("qwen-fast:latest", digest)]
        module, streamlit = self._load_ui_module([self._ollama_discovery(models)])

        captions = " ".join(streamlit.sidebar.captions)
        self.assertIn("Revision: `sha256:aaaaaaaaaaaa...", captions)
        self.assertNotIn(digest, captions)
        self.assertEqual(module.model_lookup["ollama:qwen-fast:latest"].model.revision, digest)

    def test_no_local_provider_models_uses_clear_developer_fallback(self):
        module, streamlit = self._load_ui_module([self._ollama_discovery([]), self._development_discovery()])

        fallback_ids = [model.model_id for model in registered_models()]
        args, _ = streamlit.sidebar.selectbox_calls[1]
        self.assertEqual(args[1], fallback_ids)
        fallback_entry = module.model_lookup[fallback_ids[0]]
        self.assertIn("developer fallback", module._model_option_label(fallback_entry))
        self.assertEqual(len(streamlit.sidebar.warning_messages), 1)
        self.assertIn("No local provider models were discovered", streamlit.sidebar.warning_messages[0])

    def test_provider_discovery_error_keeps_ui_usable(self):
        discoveries = [
            ProviderDiscovery(
                provider_id="ollama",
                provider_name="Ollama",
                models=[],
                error="ConnectionError: connection refused",
            ),
            self._development_discovery(),
        ]
        module, streamlit = self._load_ui_module(discoveries)

        fallback_ids = [model.model_id for model in registered_models()]
        args, _ = streamlit.sidebar.selectbox_calls[1]
        self.assertEqual(args[1], fallback_ids)
        self.assertIn("Ollama discovery failed", streamlit.sidebar.warning_messages[0])

    def test_model_selection_data_supports_provider_grouping(self):
        ollama_models = [self._ollama_model("gemma3:4b", "sha256:gemma")]
        module, _ = self._load_ui_module([self._ollama_discovery(ollama_models), self._development_discovery()])

        all_entries = module._visible_model_entries(module.discoveries, "all")
        selectable_entries = module._selectable_model_entries(all_entries)
        self.assertEqual([entry.model.model_id for entry in selectable_entries], ["ollama:gemma3:4b"])
        grouped = module._group_provider_models(all_entries)
        self.assertIn("Ollama", grouped)
        self.assertEqual(grouped["Ollama"][LOCAL_STATUS_INSTALLED][0].model.name, "gemma3:4b")

        fallback_entries = module._visible_model_entries([self._ollama_discovery([]), self._development_discovery()], "all")
        fallback_selectable = module._selectable_model_entries(fallback_entries)
        self.assertEqual([entry.model.model_id for entry in fallback_selectable], [model.model_id for model in registered_models()])

    def test_downloadable_models_are_grouped_but_not_selectable(self):
        installed = ProviderModel(
            provider_id="ollama",
            provider_name="Ollama",
            status=LOCAL_STATUS_INSTALLED,
            model=self._ollama_model("qwen2.5:7b", "sha256:qwen"),
        )
        downloadable = ProviderModel(
            provider_id="ollama",
            provider_name="Ollama",
            status=LOCAL_STATUS_DOWNLOADABLE,
            model=ModelRecord(
                model_id="ollama-download:future",
                name="future:latest",
                source="ollama",
                revision="catalog",
                architecture=None,
                parameter_count=None,
                quantization=None,
                license=None,
                artifact_hash=None,
                adapter="ollama",
            ),
        )
        discovery = ProviderDiscovery(
            provider_id="ollama",
            provider_name="Ollama",
            models=[installed, downloadable],
        )
        module, streamlit = self._load_ui_module([discovery])

        visible_entries = module._visible_model_entries(module.discoveries, "all")
        grouped = module._group_provider_models(visible_entries)
        selectable_entries = module._selectable_model_entries(visible_entries)

        self.assertEqual(grouped["Ollama"][LOCAL_STATUS_DOWNLOADABLE], [downloadable])
        self.assertEqual(selectable_entries, [installed])
        self.assertIn("Ollama: 1 available to download", streamlit.sidebar.captions)


if __name__ == "__main__":
    unittest.main()

"""Tests for scholaraio.config — YAML loading, merging, path resolution, defaults."""

from __future__ import annotations

from scholaraio.config import _build_config, _deep_merge, load_config


class TestDeepMerge:
    def test_scalar_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        assert _deep_merge(base, override) == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"llm": {"model": "gpt-4", "timeout": 30}}
        override = {"llm": {"timeout": 60}}
        result = _deep_merge(base, override)
        assert result == {"llm": {"model": "gpt-4", "timeout": 60}}

    def test_add_new_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}

    def test_empty_override(self):
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self):
        override = {"a": 1}
        assert _deep_merge({}, override) == {"a": 1}

    def test_override_dict_with_scalar(self):
        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        assert _deep_merge(base, override) == {"a": "flat"}

    def test_deep_nesting(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 99}}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": {"c": 99, "d": 2}}}


class TestBuildConfig:
    def test_empty_dict_uses_defaults(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.llm.model == "deepseek-chat"
        assert cfg.llm.backend == "openai-compat"
        assert cfg.embed.backend == "local"
        assert cfg.paths.papers_dir == "data/papers"
        assert cfg.search.top_k == 20

    def test_partial_override(self, tmp_path):
        data = {"llm": {"model": "gpt-4o", "timeout": 60}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.model == "gpt-4o"
        assert cfg.llm.timeout == 60
        assert cfg.llm.backend == "openai-compat"  # default preserved

    def test_concurrency_min_1(self, tmp_path):
        data = {"llm": {"concurrency": 0}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.concurrency == 1

    def test_concurrency_negative(self, tmp_path):
        data = {"llm": {"concurrency": -5}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.concurrency == 1

    def test_api_key_none_becomes_empty(self, tmp_path):
        data = {"llm": {"api_key": None}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.api_key == ""

    def test_ingest_defaults(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.ingest.extractor == "robust"
        assert cfg.ingest.chunk_page_limit == 100
        assert cfg.ingest.mineru_batch_size == 20

    def test_null_sections_handled(self, tmp_path):
        data = {"llm": None, "paths": None}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.model == "deepseek-chat"
        assert cfg.paths.papers_dir == "data/papers"

    def test_zotero_library_id_coerced_to_str(self, tmp_path):
        data = {"zotero": {"library_id": 12345}}
        cfg = _build_config(data, tmp_path)
        assert cfg.zotero.library_id == "12345"


class TestConfigProperties:
    def test_papers_dir_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.papers_dir.is_absolute()
        assert cfg.papers_dir == (tmp_path / "data" / "papers").resolve()

    def test_index_db_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.index_db.is_absolute()
        assert cfg.index_db == (tmp_path / "data" / "index.db").resolve()

    def test_log_file_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.log_file.is_absolute()

    def test_metrics_db_path(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.metrics_db_path == (tmp_path / "data" / "metrics.db").resolve()

    def test_topics_model_dir(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.topics_model_dir == (tmp_path / "data" / "topic_model").resolve()


class TestEnsureDirs:
    def test_creates_required_dirs(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        assert cfg.papers_dir.exists()
        assert (tmp_path / "data" / "inbox").exists()
        assert (tmp_path / "data" / "inbox-thesis").exists()
        assert (tmp_path / "data" / "inbox-doc").exists()
        assert (tmp_path / "data" / "pending").exists()
        assert (tmp_path / "workspace").exists()

    def test_idempotent(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        cfg.ensure_dirs()  # should not raise


class TestResolvedApiKey:
    def test_config_key_wins(self, tmp_path, monkeypatch):
        data = {"llm": {"api_key": "from-config"}}
        cfg = _build_config(data, tmp_path)
        monkeypatch.setenv("SCHOLARAIO_LLM_API_KEY", "from-env")
        assert cfg.resolved_api_key() == "from-config"

    def test_generic_env_var(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("SCHOLARAIO_LLM_API_KEY", "generic-key")
        assert cfg.resolved_api_key() == "generic-key"

    def test_backend_specific_env_openai(self, tmp_path, monkeypatch):
        cfg = _build_config({"llm": {"backend": "openai-compat"}}, tmp_path)
        monkeypatch.delenv("SCHOLARAIO_LLM_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsk-123")
        assert cfg.resolved_api_key() == "dsk-123"

    def test_backend_specific_env_anthropic(self, tmp_path, monkeypatch):
        cfg = _build_config({"llm": {"backend": "anthropic"}}, tmp_path)
        monkeypatch.delenv("SCHOLARAIO_LLM_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
        assert cfg.resolved_api_key() == "ant-key"

    def test_backend_specific_env_google(self, tmp_path, monkeypatch):
        cfg = _build_config({"llm": {"backend": "google"}}, tmp_path)
        monkeypatch.delenv("SCHOLARAIO_LLM_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "goog-key")
        assert cfg.resolved_api_key() == "goog-key"

    def test_no_key_returns_empty(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        for v in ("SCHOLARAIO_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        assert cfg.resolved_api_key() == ""

    def test_mineru_key_from_config(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_api_key": "mu-key"}}, tmp_path)
        assert cfg.resolved_mineru_api_key() == "mu-key"

    def test_mineru_key_from_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("MINERU_API_KEY", "mu-env")
        assert cfg.resolved_mineru_api_key() == "mu-env"

    def test_embed_key_from_config(self, tmp_path):
        cfg = _build_config({"embed": {"api_key": "embed-key"}}, tmp_path)
        assert cfg.resolved_embed_api_key() == "embed-key"

    def test_embed_key_from_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("SCHOLARAIO_EMBED_API_KEY", "embed-env")
        assert cfg.resolved_embed_api_key() == "embed-env"


class TestLoadConfig:
    def test_load_from_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("llm:\n  model: test-model\n", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.llm.model == "test-model"

    def test_local_yaml_overrides(self, tmp_path):
        (tmp_path / "config.yaml").write_text(
            "llm:\n  model: base-model\n  timeout: 30\n",
            encoding="utf-8",
        )
        (tmp_path / "config.local.yaml").write_text(
            "llm:\n  model: local-model\n",
            encoding="utf-8",
        )
        cfg = load_config(tmp_path / "config.yaml")
        assert cfg.llm.model == "local-model"
        assert cfg.llm.timeout == 30  # preserved from base

    def test_nonexistent_path_uses_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert cfg.llm.model == "deepseek-chat"

    def test_empty_yaml(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.llm.model == "deepseek-chat"

    def test_env_var_config_path(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("search:\n  top_k: 42\n", encoding="utf-8")
        monkeypatch.setenv("SCHOLARAIO_CONFIG", str(cfg_file))
        cfg = load_config()
        assert cfg.search.top_k == 42

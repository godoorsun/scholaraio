"""Tests for local/remote embedding backends."""

from __future__ import annotations

import math
import requests
from unittest.mock import MagicMock, patch

from scholaraio.config import _build_config
from scholaraio.vectors import _embed_backend, _embed_batch, _embed_text


def _fake_response(payload: dict, status_code: int = 200, headers: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if status_code >= 400:
        err = requests.HTTPError(f"{status_code} error")
        err.response = resp
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


class TestRemoteEmbeddings:
    def test_backend_aliases(self, tmp_path):
        cfg = _build_config({"embed": {"backend": "openai-compat"}}, tmp_path)
        assert _embed_backend(cfg) == "openai-compat"

        cfg = _build_config({"embed": {"backend": "remote"}}, tmp_path)
        assert _embed_backend(cfg) == "openai-compat"

    def test_embed_text_via_openai_compat(self, tmp_path):
        cfg = _build_config(
            {
                "embed": {
                    "backend": "openai-compat",
                    "api_key": "sk-test",
                    "base_url": "https://example.com/v1",
                    "model": "qwen3-embedding-0.6b",
                }
            },
            tmp_path,
        )

        payload = {
            "data": [
                {"index": 0, "embedding": [3.0, 4.0]},
            ]
        }
        with patch("scholaraio.vectors.requests.post", return_value=_fake_response(payload)) as mock_post:
            vec = _embed_text("hello", cfg)

        assert mock_post.called
        assert math.isclose(vec[0], 0.6, rel_tol=1e-6)
        assert math.isclose(vec[1], 0.8, rel_tol=1e-6)

    def test_embed_batch_preserves_input_order_across_chunks(self, tmp_path):
        cfg = _build_config(
            {
                "embed": {
                    "backend": "openai-compat",
                    "api_key": "sk-test",
                    "base_url": "https://example.com/v1",
                    "model": "qwen3-embedding-0.6b",
                    "api_batch_size": 2,
                    "api_concurrency": 4,
                }
            },
            tmp_path,
        )

        call_count = {"n": 0}

        def _post(*args, **kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            batches = [
                {"data": [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 1, "embedding": [0.0, 1.0]}]},
                {"data": [{"index": 0, "embedding": [1.0, 1.0]}]},
            ]
            return _fake_response(batches[idx])

        with patch("scholaraio.vectors.requests.post", side_effect=_post):
            vecs = _embed_batch(["a", "b", "c"], cfg)

        assert len(vecs) == 3
        assert vecs[0] == [1.0, 0.0]
        assert vecs[1] == [0.0, 1.0]
        assert math.isclose(vecs[2][0], 2**-0.5, rel_tol=1e-6)
        assert math.isclose(vecs[2][1], 2**-0.5, rel_tol=1e-6)

    def test_embed_text_retries_on_429(self, tmp_path):
        cfg = _build_config(
            {
                "embed": {
                    "backend": "openai-compat",
                    "api_key": "sk-test",
                    "base_url": "https://example.com/v1",
                    "model": "qwen3-embedding-8b",
                }
            },
            tmp_path,
        )

        responses = [
            _fake_response({"error": "rate limited"}, status_code=429, headers={"Retry-After": "0"}),
            _fake_response({"data": [{"index": 0, "embedding": [0.0, 2.0]}]}),
        ]

        with patch("scholaraio.vectors.requests.post", side_effect=responses) as mock_post:
            with patch("scholaraio.vectors.time.sleep") as mock_sleep:
                vec = _embed_text("hello", cfg)

        assert mock_post.call_count == 2
        assert mock_sleep.called
        assert vec == [0.0, 1.0]

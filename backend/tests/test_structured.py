from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from evaluation.structured import complete_json, embed_texts


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.last_url = ""
        self.last_json: dict = {}

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, *, json: dict) -> _FakeResponse:
        self.last_url = url
        self.last_json = json
        return self.response


class LocalStructuredClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_json_sends_schema_to_local_ollama(self) -> None:
        schema = {
            "type": "object",
            "required": ["score"],
            "properties": {"score": {"type": "integer"}},
        }
        fake = _FakeClient(
            _FakeResponse({"message": {"content": json.dumps({"score": 4})}})
        )

        with patch("evaluation.structured.httpx.AsyncClient", return_value=fake):
            result = await complete_json(
                name="test_score",
                schema=schema,
                instructions="Score the answer.",
                input_text="A concrete answer",
            )

        self.assertEqual(result, {"score": 4})
        self.assertTrue(fake.last_url.endswith("/api/chat"))
        self.assertEqual(fake.last_json["format"], schema)
        self.assertFalse(fake.last_json["stream"])

    async def test_embed_texts_uses_configured_local_dimensions(self) -> None:
        vector = [0.0] * 768
        fake = _FakeClient(_FakeResponse({"embeddings": [vector, vector]}))

        with patch("evaluation.structured.httpx.AsyncClient", return_value=fake):
            result = await embed_texts(["one", "two"])

        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 768)
        self.assertTrue(fake.last_url.endswith("/api/embed"))
        self.assertEqual(fake.last_json["dimensions"], 768)


if __name__ == "__main__":
    unittest.main()

import json

import httpx
import pytest

from app import model


def test_model_adapter_sends_expected_request_and_parses_json(monkeypatch):
    real_client = httpx.Client
    observed = {}
    def handler(request):
        observed['path'] = request.url.path
        observed['body'] = json.loads(request.content)
        observed['authorized'] = request.headers.get('authorization') == 'Bearer unit-test-only'
        return httpx.Response(200, json={'choices': [{'message': {'content': '```json\n{"mapping":{"student_id":"账号"}}\n```'}}]})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(model.httpx, 'Client', lambda **kwargs: real_client(transport=transport, **kwargs))
    try:
        model.configure('https://model.invalid/v1', 'unit-test-model', 'unit-test-only')
        result = model.ask_json('提取表头映射。', {'headers': ['账号']})
        assert result['mapping']['student_id'] == '账号'
        assert observed['path'] == '/v1/chat/completions'
        assert observed['body']['model'] == 'unit-test-model' and observed['authorized']
        assert 'unit-test-only' not in json.dumps(model.status())
    finally:
        model.clear()


def test_model_error_does_not_echo_provider_body_or_key(monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={'error': 'unit-test-only'}))
    monkeypatch.setattr(model.httpx, 'Client', lambda **kwargs: real_client(transport=transport, **kwargs))
    try:
        model.configure('https://model.invalid', 'test', 'unit-test-only')
        with pytest.raises(ValueError) as error:
            model.ask_json('返回JSON', {})
        assert '401' in str(error.value) and 'unit-test-only' not in str(error.value)
    finally:
        model.clear()

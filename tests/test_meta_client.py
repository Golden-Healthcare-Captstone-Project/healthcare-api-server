from unittest.mock import Mock, patch

import pytest
import requests

from app.meta_client import (
    GRAPH_API_TIMEOUT,
    MAX_RETRIES,
    MetaGraphAPIError,
    MetaRateLimitedError,
    graph_get,
)


def _response(status_code, json_body=None, ok=None):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.ok = ok if ok is not None else 200 <= status_code < 300
    response.json.return_value = json_body if json_body is not None else {}
    return response


@patch("app.meta_client.time.sleep")
@patch("app.meta_client.requests.get")
def test_graph_get_returns_json_on_success(mock_get, mock_sleep):
    mock_get.return_value = _response(200, {"data": [1, 2, 3]})

    result = graph_get("https://graph.facebook.com/v19.0/me", {"access_token": "x"})

    assert result == {"data": [1, 2, 3]}
    mock_sleep.assert_not_called()


@patch("app.meta_client.time.sleep")
@patch("app.meta_client.requests.get")
def test_graph_get_retries_once_then_raises_on_persistent_429(mock_get, mock_sleep):
    mock_get.return_value = _response(429, {"error": {"code": 4, "message": "rate limited"}})

    with pytest.raises(MetaRateLimitedError):
        graph_get("https://graph.facebook.com/v19.0/me", {})

    assert mock_get.call_count == MAX_RETRIES + 1
    mock_sleep.assert_called_once()


@patch("app.meta_client.time.sleep")
@patch("app.meta_client.requests.get")
def test_graph_get_treats_meta_rate_limit_error_code_like_429(mock_get, mock_sleep):
    mock_get.return_value = _response(400, {"error": {"code": 17, "is_transient": False}})

    with pytest.raises(MetaRateLimitedError):
        graph_get("https://graph.facebook.com/v19.0/me", {})

    assert mock_get.call_count == MAX_RETRIES + 1


@patch("app.meta_client.time.sleep")
@patch("app.meta_client.requests.get")
def test_graph_get_does_not_retry_non_rate_limit_error(mock_get, mock_sleep):
    mock_get.return_value = _response(401, {"error": {"code": 190, "message": "invalid token"}})

    with pytest.raises(MetaGraphAPIError) as exc_info:
        graph_get("https://graph.facebook.com/v19.0/me", {})

    assert mock_get.call_count == 1
    mock_sleep.assert_not_called()
    assert exc_info.value.status_code == 401
    assert exc_info.value.meta_error_code == 190


@patch("app.meta_client.requests.get")
def test_graph_get_passes_timeout(mock_get):
    mock_get.return_value = _response(200, {"ok": True})

    graph_get("https://graph.facebook.com/v19.0/me", {"access_token": "x"})

    assert mock_get.call_args.kwargs["timeout"] == GRAPH_API_TIMEOUT


@patch("app.meta_client.requests.get", side_effect=requests.exceptions.Timeout())
def test_graph_get_raises_graph_api_error_on_network_timeout(mock_get):
    with pytest.raises(MetaGraphAPIError):
        graph_get("https://graph.facebook.com/v19.0/me", {})

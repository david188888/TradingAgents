"""Tests for OpenRouter Decisions API client."""
from unittest.mock import Mock, patch

import pytest
import requests

from tradingagents.llm_clients.decisions_client import (
    JevVerificationError,
    JevVerificationUnavailable,
    verify_insight_risk,
)


@pytest.fixture
def mock_env(monkeypatch):
    """设置测试环境变量。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")


@pytest.fixture
def sample_questions():
    """标准验证问题。"""
    return {
        "evidence_sufficient": {
            "type": "noul",
            "instructions": "证据是否充分？",
            "criteria": {"true": "充分", "false": "不足"}
        }
    }


@pytest.fixture
def sample_state():
    """样本 insight 状态。"""
    return {
        "insight": {"claim": "测试观点", "reasoning": "测试推理"},
        "cited_evidence": [{"ref": "E1", "text": "证据文本"}]
    }


def test_verify_insight_risk_success(mock_env, sample_questions, sample_state):
    """成功调用返回 scores 和 meta。"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "gen-test-123",
        "model": "typesafe/jev-1.14",
        "provider": "TypeSafe",
        "answers": {
            "evidence_sufficient": {"type": "noul", "noul": 0.92}
        },
        "usage": {"input_tokens": 100, "output_tokens": 10, "cost": 0.00004}
    }

    with patch('requests.post', return_value=mock_response) as mock_post:
        scores, meta = verify_insight_risk(
            model="typesafe/jev-1.14",
            insight_state=sample_state,
            questions=sample_questions
        )

    assert scores == {"evidence_sufficient": 0.92}
    assert meta["id"] == "gen-test-123"
    assert meta["model"] == "typesafe/jev-1.14"
    assert meta["usage"]["cost"] == 0.00004

    # 验证请求参数
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://openrouter.ai/api/alpha/decisions"
    assert call_args[1]["headers"]["Authorization"] == "Bearer test-key-123"
    assert call_args[1]["json"]["model"] == "typesafe/jev-1.14"
    assert call_args[1]["json"]["provider"]["data_collection"] == "deny"


def test_verify_insight_risk_no_api_key(monkeypatch):
    """未设置 API key 时本地检查失败。"""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(JevVerificationError, match="OPENROUTER_API_KEY not set"):
        verify_insight_risk(
            model="typesafe/jev-1.14",
            insight_state={},
            questions={}
        )


def test_verify_insight_risk_400_error(mock_env, sample_questions, sample_state):
    """4xx 错误不可重试。"""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request: invalid question type"

    with patch('requests.post', return_value=mock_response), \
         pytest.raises(JevVerificationError, match="400.*invalid question"):
        verify_insight_risk(
                model="typesafe/jev-1.14",
                insight_state=sample_state,
                questions=sample_questions,
                retries=1
            )


def test_verify_insight_risk_500_retry(mock_env, sample_questions, sample_state):
    """5xx 错误会重试。"""
    mock_response_fail = Mock()
    mock_response_fail.status_code = 500
    mock_response_fail.text = "Internal Server Error"
    mock_response_fail.headers = {}

    mock_response_success = Mock()
    mock_response_success.status_code = 200
    mock_response_success.json.return_value = {
        "id": "gen-test-456",
        "answers": {"evidence_sufficient": {"type": "noul", "noul": 0.88}},
        "usage": {}
    }

    with patch('requests.post', side_effect=[mock_response_fail, mock_response_success]), \
         patch('time.sleep'):
        scores, meta = verify_insight_risk(
                model="typesafe/jev-1.14",
                insight_state=sample_state,
                questions=sample_questions,
                retries=2
            )

    assert scores == {"evidence_sufficient": 0.88}


def test_verify_insight_risk_timeout(mock_env, sample_questions, sample_state):
    """超时会重试并最终失败。"""
    with patch('requests.post', side_effect=requests.Timeout("Connection timeout")), \
         patch('time.sleep'), \
         pytest.raises(JevVerificationUnavailable, match="failed after 2 attempts"):
        verify_insight_risk(
                    model="typesafe/jev-1.14",
                    insight_state=sample_state,
                    questions=sample_questions,
                    retries=2
                )


def test_verify_insight_risk_missing_answer(mock_env, sample_questions, sample_state):
    """缺少答案抛出错误。"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "gen-test-789",
        "answers": {}  # 空答案
    }

    with patch('requests.post', return_value=mock_response), \
         pytest.raises(JevVerificationError, match="Missing answers"):
        verify_insight_risk(
                model="typesafe/jev-1.14",
                insight_state=sample_state,
                questions=sample_questions
            )


def test_verify_insight_risk_refusal(mock_env, sample_questions, sample_state):
    """provider 拒答抛出错误。"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "gen-test-refused",
        "answers": {
            "evidence_sufficient": {"type": "refusal"}
        }
    }

    with patch('requests.post', return_value=mock_response), \
         pytest.raises(JevVerificationError, match="refused to answer"):
        verify_insight_risk(
                model="typesafe/jev-1.14",
                insight_state=sample_state,
                questions=sample_questions
            )


def test_verify_insight_risk_invalid_probability(mock_env, sample_questions, sample_state):
    """概率超出 [0, 1] 抛出错误。"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "gen-test-invalid",
        "answers": {
            "evidence_sufficient": {"type": "noul", "noul": 1.5}  # 无效概率
        }
    }

    with patch('requests.post', return_value=mock_response), \
         pytest.raises(JevVerificationError, match="Invalid probability.*1.5"):
        verify_insight_risk(
                model="typesafe/jev-1.14",
                insight_state=sample_state,
                questions=sample_questions
            )


def test_verify_insight_risk_multiple_questions(mock_env, sample_state):
    """多个问题一次返回。"""
    questions = {
        "evidence_sufficient": {"type": "noul", "instructions": "证据充分？"},
        "reasoning_sound": {"type": "noul", "instructions": "推理严密？"}
    }

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "gen-test-multi",
        "answers": {
            "evidence_sufficient": {"type": "noul", "noul": 0.92},
            "reasoning_sound": {"type": "noul", "noul": 0.85}
        },
        "usage": {}
    }

    with patch('requests.post', return_value=mock_response):
        scores, meta = verify_insight_risk(
            model="typesafe/jev-1.14",
            insight_state=sample_state,
            questions=questions
        )

    assert scores == {"evidence_sufficient": 0.92, "reasoning_sound": 0.85}

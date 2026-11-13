"""Integration tests for Jev verification stage.

需要真实 OPENROUTER_API_KEY 环境变量。
"""
import os

import pytest

from tradingagents.llm_clients.decisions_client import verify_insight_risk


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="Requires OPENROUTER_API_KEY"
)
def test_jev_verification_single_insight_real_api():
    """使用真实 API 验证单条 insight。"""
    insight_state = {
        "insight": {
            "claim": "公司营收连续三年增长超过20%",
            "reasoning": "根据财报数据，2021-2023年营收分别为100亿、125亿、156亿，同比增长25%、24.8%",
            "evidence_refs": ["E1", "E2"]
        },
        "cited_evidence": [
            {
                "ref": "E1",
                "text": "2021年年报显示营业收入100.2亿元",
                "limitations": []
            },
            {
                "ref": "E2",
                "text": "2022年年报显示营业收入125.1亿元，同比增长24.9%",
                "limitations": []
            }
        ],
        "global_catalog_summary": [
            {"ref": "E3", "text": "2023年年报显示营业收入156.2亿元"}
        ]
    }

    questions = {
        "evidence_sufficient": {
            "type": "noul",
            "instructions": "引用的证据卡片是否充分支持该观点的程度与范围？",
            "criteria": {
                "true": "证据直接覆盖观点主张，数量与质量足够",
                "false": "证据不足、证据与观点主张存在程度差距、或推理需要额外假设"
            }
        },
        "reasoning_sound": {
            "type": "noul",
            "instructions": "从证据到观点的推理链是否严密？",
            "criteria": {
                "true": "每步推理都有明确依据，无因果跳跃",
                "false": "存在未说明的因果假设、或将相关性当作因果、或忽略其他可能解释"
            }
        }
    }

    # 调用真实 API
    scores, meta = verify_insight_risk(
        model="typesafe/jev-1.14",
        insight_state=insight_state,
        questions=questions,
        timeout=30,
        retries=3
    )

    # 验证返回格式
    assert isinstance(scores, dict)
    assert "evidence_sufficient" in scores
    assert "reasoning_sound" in scores
    assert 0.0 <= scores["evidence_sufficient"] <= 1.0
    assert 0.0 <= scores["reasoning_sound"] <= 1.0

    # 验证 meta
    assert "id" in meta
    assert "model" in meta
    assert "usage" in meta
    assert meta["usage"]["input_tokens"] > 0

    print(f"\nJev verification scores: {scores}")
    print(f"Model: {meta['model']}, Cost: ${meta['usage'].get('cost', 0):.6f}")


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="Requires OPENROUTER_API_KEY"
)
def test_jev_risk_level_classification():
    """测试风险分级逻辑。"""
    # 高分 insight（应该是 jev_clear）
    high_scores = {
        "evidence_sufficient": 0.92,
        "reasoning_sound": 0.89,
        "catalog_consistent": 0.95
    }

    # 低分 insight（应该是 jev_high_risk）
    low_scores = {
        "evidence_sufficient": 0.12,
        "reasoning_sound": 0.85,
        "catalog_consistent": 0.90
    }

    # 中等分 insight（应该是 jev_uncertain）
    medium_scores = {
        "evidence_sufficient": 0.75,
        "reasoning_sound": 0.65,
        "catalog_consistent": 0.80
    }

    # 分级逻辑
    def classify_risk(scores):
        if (scores.get('evidence_sufficient', 0) >= 0.85 and
            scores.get('reasoning_sound', 0) >= 0.85 and
            scores.get('catalog_consistent', 0) >= 0.85):
            return 'jev_clear'
        elif any(scores.get(k, 1.0) <= 0.15 for k in scores):
            return 'jev_high_risk'
        else:
            return 'jev_uncertain'

    assert classify_risk(high_scores) == 'jev_clear'
    assert classify_risk(low_scores) == 'jev_high_risk'
    assert classify_risk(medium_scores) == 'jev_uncertain'


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="Requires OPENROUTER_API_KEY"
)
def test_jev_free_model_alternative():
    """测试免费模型 pplx-decider-flash-v1.3。"""
    insight_state = {
        "insight": {
            "claim": "测试观点",
            "reasoning": "测试推理"
        },
        "cited_evidence": [],
        "global_catalog_summary": []
    }

    questions = {
        "evidence_sufficient": {
            "type": "noul",
            "instructions": "证据是否充分？"
        }
    }

    scores, meta = verify_insight_risk(
        model="perplexity/pplx-decider-flash-v1.3:free",
        insight_state=insight_state,
        questions=questions
    )

    assert isinstance(scores, dict)
    assert "evidence_sufficient" in scores
    assert meta["provider"] == "Perplexity"
    print(f"\nFree model result: {scores}, Cost: ${meta['usage'].get('cost', 0):.6f}")

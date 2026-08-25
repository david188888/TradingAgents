from tradingagents.portfolio import ConvictionSignal, aggregate_risk_convictions


def test_abstained_risk_role_does_not_dilute_conviction():
    aggregate = aggregate_risk_convictions(
        [
            ConvictionSignal("aggressive", 0.7, 0.8),
            ConvictionSignal("conservative", None, 1.0),
            ConvictionSignal("neutral", 0.3, 0.2),
        ]
    )

    assert aggregate.conviction == 0.62
    assert aggregate.abstained_roles == ("conservative",)
    assert aggregate.disagreement == "tight"

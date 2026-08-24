from __future__ import annotations

import pytest

from tradingagents.research.public_hash import (
    PublicHashError,
    canonical_json_bytes,
    package_sha256,
)

pytestmark = pytest.mark.unit


def test_package_hash_is_deterministic_and_private_fields_are_rejected():
    package = {
        "schema_version": "research-package-v1",
        "run_id": "run_20260815T082000000000Z_ab12cd34",
        "claims": [{"claim_id": "claim_1", "text": "公开事实"}],
    }

    assert package_sha256(package) == package_sha256(dict(reversed(list(package.items()))))
    assert package_sha256(package) == package_sha256(
        {"claims": [{"text": "公开事实", "claim_id": "claim_1"}], **package}
    )
    with pytest.raises(PublicHashError, match="private field"):
        package_sha256({"privateReasoning": "do not export"})


def test_canonical_json_bytes_is_stable_and_utf8():
    payload = {"b": "中文", "a": 1}
    assert canonical_json_bytes(payload) == canonical_json_bytes({"a": 1, "b": "中文"})
    assert canonical_json_bytes(payload).decode("utf-8").startswith('{"a":1,"b":"中文"}')

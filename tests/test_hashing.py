"""Tests for payload content hashing."""

from endurance_coach.collector.hashing import payload_content_hash


def test_payload_content_hash_is_stable() -> None:
    payload = {"b": 2, "a": 1}
    assert payload_content_hash(payload) == payload_content_hash({"a": 1, "b": 2})


def test_payload_content_hash_differs_for_different_data() -> None:
    assert payload_content_hash({"a": 1}) != payload_content_hash({"a": 2})

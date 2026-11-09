# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

import json

import pytest

from custom_components.junie_remote.durable_store import read_store_envelope

KEY = "junie_remote_test_store"


class StoreError(Exception):
    pass


def _write(path, payload):
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))


def test_missing_store_reads_as_none(tmp_path):
    assert read_store_envelope(str(tmp_path / "absent"), KEY, 1, StoreError) is None


def test_valid_version_one_store_returns_data(tmp_path):
    path = tmp_path / "store"
    _write(path, {"version": 1, "minor_version": 1, "key": KEY, "data": {"a": 1}})
    assert read_store_envelope(str(path), KEY, 1, StoreError) == {"a": 1}


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "{truncated",
        {"version": 2, "minor_version": 1, "key": KEY, "data": {"a": 1}},
        {"version": 1, "minor_version": 2, "key": KEY, "data": {"a": 1}},
        {"version": 1, "minor_version": 1, "key": "other", "data": {"a": 1}},
        {"version": 1, "minor_version": 1, "key": KEY, "data": None},
        {"version": 1, "minor_version": 1, "key": KEY},
        ["not", "a", "dict"],
    ],
)
def test_corrupt_or_unknown_store_raises_without_touching_file(tmp_path, payload):
    path = tmp_path / "store"
    _write(path, payload)
    before = path.read_bytes()
    with pytest.raises(StoreError):
        read_store_envelope(str(path), KEY, 1, StoreError)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["store"]

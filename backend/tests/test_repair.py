from dzmm.parsing.repair import parse_loose_json


def test_parses_valid_json():
    assert parse_loose_json('{"hp": -5}') == {"hp": -5}


def test_parses_single_quoted():
    assert parse_loose_json("{'hp': -5}") == {"hp": -5}


def test_extracts_inner_braces():
    assert parse_loose_json('garbage {"hp": -5} trailing') == {"hp": -5}


def test_returns_empty_on_unrecoverable():
    assert parse_loose_json("not json at all") == {}


def test_handles_nested_braces():
    src = '{"a": {"b": 1}}'
    assert parse_loose_json(src) == {"a": {"b": 1}}


def test_handles_trailing_commas():
    result = parse_loose_json('{"hp": -5,}')
    assert isinstance(result, dict)

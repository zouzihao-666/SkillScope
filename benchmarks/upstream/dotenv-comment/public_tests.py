from candidate import parse_text


def test_empty_value_followed_by_comment():
    assert parse_text("KEY= # comment\nNEXT=ok\n") == {"KEY": "", "NEXT": "ok"}


def test_hash_without_whitespace_is_literal():
    assert parse_text("KEY=#literal\n") == {"KEY": "#literal"}

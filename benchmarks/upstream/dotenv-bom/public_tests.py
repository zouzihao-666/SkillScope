from candidate import parse_text


def test_first_key_has_no_bom():
    assert parse_text("\ufeffNAME=value\nNEXT=ok") == {"NAME": "value", "NEXT": "ok"}


def test_plain_stream():
    assert parse_text("NAME=value") == {"NAME": "value"}

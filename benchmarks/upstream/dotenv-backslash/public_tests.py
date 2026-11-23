from candidate import round_trip


def test_windows_path():
    assert round_trip(r"C:\Users") == {"value": r"C:\Users", "next": "sentinel", "keep": "original"}


def test_trailing_backslash():
    assert round_trip("back\\") == {"value": "back\\", "next": "sentinel", "keep": "original"}

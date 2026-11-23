import io
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import dotenv_values, get_key, set_key


def parse_text(text):
    return dict(dotenv_values(stream=io.StringIO(text), interpolate=False))


def round_trip(value, quote_mode="always"):
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sample.env"
        path.write_text("KEEP=original\n", encoding="utf-8")
        set_key(path, "VALUE", value, quote_mode=quote_mode)
        set_key(path, "NEXT", "sentinel")
        return {
            "value": get_key(path, "VALUE"),
            "next": get_key(path, "NEXT"),
            "keep": get_key(path, "KEEP"),
        }

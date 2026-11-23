import io

from dotenv import dotenv_values


def parse_text(text):
    return dict(dotenv_values(stream=io.StringIO(text), interpolate=False))

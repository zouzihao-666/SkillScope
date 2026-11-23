def parse_duration(text):
    import re

    match = re.fullmatch(r"\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s\s*)?", text)
    if match is None or all(value is None for value in match.groups()):
        raise ValueError("invalid duration")
    hours, minutes, seconds = (int(value or 0) for value in match.groups())
    return 3600 * hours + 60 * minutes + seconds

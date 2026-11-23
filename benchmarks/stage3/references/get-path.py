def get_path(data, path, default):
    parts, segment = [], []
    index = 0
    while index < len(path):
        char = path[index]
        if char == chr(92):
            index += 1
            if index == len(path) or path[index] not in (".", chr(92)):
                raise ValueError("invalid escape")
            segment.append(path[index])
        elif char == ".":
            if not segment:
                raise ValueError("empty segment")
            parts.append("".join(segment))
            segment = []
        else:
            segment.append(char)
        index += 1
    if not segment:
        raise ValueError("empty segment")
    parts.append("".join(segment))
    for key in parts:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data

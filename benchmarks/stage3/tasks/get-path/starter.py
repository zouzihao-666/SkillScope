def get_path(data, path, default):
    for key in path.split("."):
        data = data[key]
    return data

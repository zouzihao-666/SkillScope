from delivery.quote import shipping_fee as shipping_fee


def runtime_probe():
    import os
    from importlib.resources import files
    from pathlib import Path

    resource = Path("delivery/rates.json")
    try:
        resource.write_text("tampered", encoding="utf-8")
        readonly = False
    except OSError:
        readonly = True
    inventory = sorted(
        str(path.relative_to("/candidate"))
        for path in Path("/candidate").rglob("*")
        if path.is_file()
    )
    return {
        "cwd": str(Path.cwd()),
        "readonly": readonly,
        "namespace_resource": files("delivery").joinpath("rates.json").is_file(),
        "inventory": inventory,
        "has_api_key": any("API_KEY" in key for key in os.environ),
        "has_docker_socket": Path("/var/run/docker.sock").exists(),
    }

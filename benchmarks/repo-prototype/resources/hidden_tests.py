import pytest
from candidate import runtime_probe, shipping_fee


@pytest.mark.parametrize("zone, weight, expected", [("local", 2, 410), ("remote", 2.01, 1150)])
def test_resource_driven_fees(zone, weight, expected):
    assert shipping_fee(zone, weight) == expected


@pytest.mark.parametrize("weight", [-1, True, "2", None])
def test_invalid_weights(weight):
    with pytest.raises(ValueError):
        shipping_fee("local", weight)


def test_unknown_zone():
    with pytest.raises(ValueError):
        shipping_fee("unknown", 1)


def test_runtime_boundary():
    probe = runtime_probe()
    assert probe == {
        "cwd": "/candidate",
        "readonly": True,
        "namespace_resource": True,
        "inventory": ["README.md", "candidate.py", "delivery/quote.py", "delivery/rates.json"],
        "has_api_key": False,
        "has_docker_socket": False,
    }

import json
import math
from pathlib import Path


def shipping_fee(zone, weight):
    rates = json.loads(Path(__file__).with_name("rates.json").read_text(encoding="utf-8"))
    if not isinstance(zone, str) or zone not in rates:
        raise ValueError("Unknown zone")
    if type(weight) not in (int, float) or not math.isfinite(weight) or weight < 0:
        raise ValueError("Invalid weight")
    rate = rates[zone]
    return rate["base"] + rate["per_started_kg"] * math.ceil(weight)

Repair delivery/quote.py so shipping_fee(zone, weight) uses the adjacent rates.json.
The package intentionally has no __init__.py (a Python namespace package).
For each zone, charge base plus per_started_kg * ceil(weight).
Weight must be an actual int or float (not bool), finite and nonnegative.
Unknown zones and invalid weights must raise ValueError. Zero weight pays base.
Only delivery/quote.py may change. This is a manually authored runtime fixture,
not an upstream issue or a difficulty-calibration sample.

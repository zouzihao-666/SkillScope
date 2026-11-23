import copy

import pytest
from candidate import checkout


@pytest.mark.parametrize(
    "lines,discount,expected",
    [
        ([], 0, 0),
        ([{"price": "2.675", "quantity": 1}], 0, 268),
        ([{"price": "0.05", "quantity": 1}, {"price": "0.05", "quantity": 1}], 1000, 10),
        ([{"price": "3.335", "quantity": 2}], 2500, 500),
        ([{"price": "0.10", "quantity": 3}], 3333, 20),
        ([{"price": "10.00", "quantity": 1}], 10000, 0),
    ],
)
def test_prices_and_input_integrity(lines, discount, expected):
    before = copy.deepcopy(lines)
    assert checkout(lines, discount) == expected
    assert lines == before


@pytest.mark.parametrize("discount", [-1, 10001, True, 1.5])
def test_validate_even_empty_cart(discount):
    with pytest.raises(ValueError):
        checkout([], discount)


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-0.01", "invalid", None])
def test_invalid_prices(price):
    with pytest.raises(ValueError):
        checkout([{"price": price, "quantity": 1}], 0)


@pytest.mark.parametrize("quantity", [-1, True, 1.5])
def test_invalid_quantities(quantity):
    with pytest.raises(ValueError):
        checkout([{"price": "1.00", "quantity": quantity}], 0)


def test_missing_field():
    with pytest.raises(ValueError):
        checkout([{"quantity": 1}], 0)

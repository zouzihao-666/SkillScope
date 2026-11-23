from candidate import checkout


def test_simple_order():
    assert checkout([{"price": "2.00", "quantity": 3}], 0) == 600


def test_exact_half_cent():
    assert checkout([{"price": "1.005", "quantity": 1}], 0) == 101

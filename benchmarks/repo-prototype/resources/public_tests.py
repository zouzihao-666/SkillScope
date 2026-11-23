from candidate import shipping_fee


def test_local_fractional_weight():
    assert shipping_fee("local", 1.1) == 410


def test_remote_zero_weight():
    assert shipping_fee("remote", 0) == 700

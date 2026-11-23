from decimal import Decimal, InvalidOperation


def amount(text):
    if not isinstance(text, str):
        raise ValueError("price must be a string")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError("invalid decimal") from None
    if not value.is_finite() or value < 0:
        raise ValueError("price must be finite and nonnegative")
    return value

from decimal import ROUND_HALF_UP, Decimal

from shop.money import amount


def checkout(lines, discount_bps):
    if type(discount_bps) is not int or not 0 <= discount_bps <= 10000:
        raise ValueError("invalid discount")
    factor = Decimal(10000 - discount_bps) / Decimal(10000)
    total = 0
    for line in lines:
        if "price" not in line or "quantity" not in line:
            raise ValueError("missing field")
        quantity = line["quantity"]
        if type(quantity) is not int or quantity < 0:
            raise ValueError("invalid quantity")
        value = amount(line["price"]) * quantity * factor
        rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += int(rounded * 100)
    return total

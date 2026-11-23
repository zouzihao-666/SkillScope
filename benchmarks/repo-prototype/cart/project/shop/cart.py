from shop.money import amount


def checkout(lines, discount_bps):
    total = sum(amount(line["price"]) * line["quantity"] for line in lines)
    return round(total * 100 * (1 - discount_bps / 10000))

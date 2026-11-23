Repair shop.cart.checkout(lines, discount_bps), preserving the public function signatures.

Return the integer number of cents after applying the same discount to every line.
Each line is a dictionary with a price string and an integer quantity.
Use exact decimal arithmetic from the original price string. For each line, multiply price by quantity,
apply (10000 - discount_bps) / 10000, round that discounted line to 2 decimal places with ROUND_HALF_UP,
then sum the rounded line amounts. Do not round prices before multiplying.

Discount basis points must be an actual integer in [0, 10000], including for an empty cart.
Quantities must be actual nonnegative integers; booleans are invalid.
Prices must be finite nonnegative decimal strings. Invalid price strings, invalid field values,
or missing required line fields must raise ValueError.
An empty cart with a valid discount returns 0. Do not mutate the input list or line dictionaries.
Use only the Python standard library.

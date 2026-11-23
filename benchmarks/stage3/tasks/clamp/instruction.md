Fix `clamp(value, lower, upper)` for numeric inputs.

- Return the value if it is inside the inclusive interval [lower, upper].
- Return lower if the value is below the interval, or upper if above it.
- If lower is greater than upper, raise ValueError rather than silently swapping them.
- Preserve the function name and signature. Use the Python standard library only.

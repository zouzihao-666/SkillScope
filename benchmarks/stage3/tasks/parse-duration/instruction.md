Repair parse_duration(text). Parse one or more nonnegative integer counts immediately followed by lowercase h, m, s.
Units may be omitted but must occur at most once in h-then-m-then-s order. Allow whitespace around and between tokens.
Counts may exceed 59; for example '90m' is 5400 seconds. Return integer total seconds.
Reject empty/whitespace-only input, negative/decimal values, repeated/out-of-order units, uppercase units and junk with ValueError.
Preserve the function signature. Use only the standard library.

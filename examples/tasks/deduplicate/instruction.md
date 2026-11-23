Fix `deduplicate(items)`.

- Return a new list with duplicates removed, preserving first-occurrence order.
- Inputs may contain unhashable values such as lists and dictionaries.
- Do not mutate the input list or its elements.
- Use normal Python equality to decide whether two values are duplicates.
- Preserve the function name and signature. Use the Python standard library only.

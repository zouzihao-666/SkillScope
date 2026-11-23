Repair toposort(graph). graph maps each string node to a list of its prerequisite node names.
Include nodes mentioned only as prerequisites. Repeated prerequisites count only once.
Return a topological ordering, choosing the lexicographically smallest CURRENTLY AVAILABLE node at every step.
For example {'a': ['z'], 'b': []} returns ['b', 'z', 'a'].
Raise ValueError for any cycle including self-loops. Empty input returns []. Do not mutate input dictionaries or lists.
Keys and prerequisite names are strings, values are lists. Preserve the signature and use only the standard library.

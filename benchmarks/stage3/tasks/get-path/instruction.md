Repair get_path(data, path, default). Traverse nested dictionaries using a dotted string path.
A backslash escapes only a dot or another backslash: a\.b.c addresses key 'a.b' then key 'c'.
The empty path, empty segments, trailing backslash, and other escapes are invalid and must raise ValueError.
Validate the COMPLETE path before traversal, even if an earlier key is missing.
Return default for a missing key or a non-dictionary encountered before the end. Return stored None as None.
Do not mutate inputs. Arguments are ordinary JSON values; path is a string. Preserve the signature.
Use only the Python standard library.

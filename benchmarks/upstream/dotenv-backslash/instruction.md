Fix a python-dotenv value round-trip bug. Values containing backslashes, such as
Windows paths or regular expressions, must survive set_key followed by get_key
with quote_mode="always" or "auto". A quoted value ending in a backslash must not
consume subsequent bindings. Handle both single- and double-quoted input parsing.
Preserve ordinary quoting, multiline values, interpolation and unquoted behavior.
Only dotenv/main.py and dotenv/parser.py may change. Inspect the current code and
public tests; this is a library task, with no CLI dependencies or network access.

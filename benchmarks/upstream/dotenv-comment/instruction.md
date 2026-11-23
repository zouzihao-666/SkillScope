Fix parsing of empty unquoted values with inline comments in python-dotenv.
For KEY= # comment or KEY=\t# comment, KEY must have the empty string value.
Without whitespace after the equals sign, KEY=#literal must keep #literal.
Keep quoted hashes, hashes within nonempty unquoted values, multiline values,
blank values, export syntax, and subsequent bindings working normally.
Only dotenv/parser.py may change. This is a library task with no CLI dependencies.

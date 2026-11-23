Fix a python-dotenv parser bug where an initial UTF-8 BOM becomes part of the
first variable name. Ignore exactly one BOM at the beginning of the stream.
Preserve BOM characters inside values or later variable names and keep streams
without a BOM working normally. Only dotenv/parser.py may change.

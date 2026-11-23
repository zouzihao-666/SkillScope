"""One JSON function invocation. This file runs only inside the container."""

import contextlib
import importlib.util
import io
import json
import sys

request = json.loads(sys.stdin.buffer.read(65537))
try:
    # Candidate prints are not part of the RPC response.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec = importlib.util.spec_from_file_location("candidate", "/candidate/candidate.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["candidate"] = module
        spec.loader.exec_module(module)
        arguments = request["args"]
        result = getattr(module, request["function"])(*arguments)
        aliases = [index for index, value in enumerate(arguments) if result is value]
        response = {"result": result, "args_after": arguments, "result_aliases": aliases}
except BaseException as error:
    response = {"exception": type(error).__name__}
sys.stdout.write(json.dumps(response, allow_nan=False))

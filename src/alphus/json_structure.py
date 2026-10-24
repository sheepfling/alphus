"""Compatibility imports for the json-structure source gate."""

from alphus.gates.languages.javascript.json_decoding import (
    DECODERS as JS_DECODERS,
)
from alphus.gates.languages.javascript.json_decoding import (
    json_findings as js_json_findings,
)
from alphus.gates.languages.python.json_decoding import (
    DECODER_MODULES,
)
from alphus.gates.languages.python.json_decoding import (
    json_findings as python_json_findings,
)
from alphus.gates.source.json_structure import (
    check_json_structure,
)

__all__ = [
    "DECODER_MODULES",
    "JS_DECODERS",
    "check_json_structure",
    "js_json_findings",
    "python_json_findings",
]

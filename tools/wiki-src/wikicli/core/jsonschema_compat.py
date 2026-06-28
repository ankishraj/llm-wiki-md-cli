"""Compatibility shim for JSON Schema validation.

Prefer the real `jsonschema` package when it is importable (development and
CI); otherwise fall back to the bundled pure-Python Draft-07 subset validator
(used inside the reproducible wiki.pyz zipapp). Both expose Draft7Validator
with `.iter_errors()` and `.check_schema()`, plus ValidationError and
SchemaError, which is the entire surface the CLI uses.
"""

from __future__ import annotations

try:  # pragma: no cover - depends on environment
    import jsonschema as _js
    Draft7Validator = _js.Draft7Validator
    ValidationError = _js.ValidationError
    SchemaError = _js.SchemaError
    BACKEND = "jsonschema"
except Exception:  # pragma: no cover
    from . import _minijsonschema as _mini
    Draft7Validator = _mini.Draft7Validator
    ValidationError = _mini.ValidationError
    SchemaError = _mini.SchemaError
    BACKEND = "bundled"

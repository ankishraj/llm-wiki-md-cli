"""A small, self-contained JSON Schema (Draft-07 subset) validator.

The CLI needs JSON Schema validation but must ship as a reproducible, pure-
Python zipapp. The reference `jsonschema` package pulls in compiled
dependencies (rpds / pyrsistent) that cannot be vendored portably. This module
implements exactly the Draft-07 features the wiki schema relies on:

  type, enum, const, required, properties, additionalProperties,
  items, uniqueItems, minLength, maxLength, minimum, maximum,
  minProperties, pattern, $ref (local #/definitions/...), contains, anyOf.

It exposes a `jsonschema`-compatible surface (Draft7Validator with
iter_errors, ValidationError, SchemaError, check_schema) so the rest of the
CLI imports it through wikicli.core.jsonschema_compat without caring whether
the real library or this fallback is in use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class SchemaError(Exception):
    pass


@dataclass
class ValidationError:
    message: str
    path: list = field(default_factory=list)


_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class Draft7Validator:
    def __init__(self, schema: dict):
        self.schema = schema

    # -- public surface -----------------------------------------------------

    @staticmethod
    def check_schema(schema: dict):
        if not isinstance(schema, dict):
            raise SchemaError("schema must be an object")
        # Light structural sanity; full meta-validation is delegated elsewhere.
        t = schema.get("type")
        if t is not None and t not in _TYPE_CHECKS and not isinstance(t, list):
            raise SchemaError(f"unknown type {t!r}")

    def iter_errors(self, instance):
        yield from self._validate(instance, self.schema, [])

    def is_valid(self, instance) -> bool:
        for _ in self.iter_errors(instance):
            return False
        return True

    # -- core ---------------------------------------------------------------

    def _resolve_ref(self, ref: str) -> dict:
        if not ref.startswith("#/"):
            raise SchemaError(f"only local refs supported, got {ref!r}")
        node = self.schema
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            node = node[part]
        return node

    def _validate(self, instance, schema, path):
        if not isinstance(schema, dict):
            return
        if "$ref" in schema:
            yield from self._validate(instance, self._resolve_ref(schema["$ref"]), path)
            return

        # type
        if "type" in schema:
            types = schema["type"]
            types = types if isinstance(types, list) else [types]
            if not any(_TYPE_CHECKS.get(t, lambda v: True)(instance) for t in types):
                yield ValidationError(f"{instance!r} is not of type {schema['type']!r}", path)
                return

        # const / enum
        if "const" in schema and instance != schema["const"]:
            yield ValidationError(f"{instance!r} != const {schema['const']!r}", path)
        if "enum" in schema and instance not in schema["enum"]:
            yield ValidationError(f"{instance!r} is not one of {schema['enum']!r}", path)

        # anyOf
        if "anyOf" in schema:
            if not any(self._ok(instance, sub) for sub in schema["anyOf"]):
                yield ValidationError(f"{instance!r} does not match anyOf", path)

        if isinstance(instance, str):
            yield from self._validate_string(instance, schema, path)
        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            yield from self._validate_number(instance, schema, path)
        if isinstance(instance, list):
            yield from self._validate_array(instance, schema, path)
        if isinstance(instance, dict):
            yield from self._validate_object(instance, schema, path)

    def _ok(self, instance, schema) -> bool:
        for _ in self._validate(instance, schema, []):
            return False
        return True

    def _validate_string(self, instance, schema, path):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            yield ValidationError(f"string shorter than {schema['minLength']}", path)
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            yield ValidationError(f"string longer than {schema['maxLength']}", path)
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            yield ValidationError(f"{instance!r} does not match pattern {schema['pattern']!r}", path)

    def _validate_number(self, instance, schema, path):
        if "minimum" in schema and instance < schema["minimum"]:
            yield ValidationError(f"{instance} < minimum {schema['minimum']}", path)
        if "maximum" in schema and instance > schema["maximum"]:
            yield ValidationError(f"{instance} > maximum {schema['maximum']}", path)

    def _validate_array(self, instance, schema, path):
        if schema.get("uniqueItems"):
            seen = []
            for item in instance:
                if item in seen:
                    yield ValidationError("array items not unique", path)
                    break
                seen.append(item)
        if "items" in schema:
            for i, item in enumerate(instance):
                yield from self._validate(item, schema["items"], path + [i])
        if "contains" in schema:
            if not any(self._ok(item, schema["contains"]) for item in instance):
                yield ValidationError("array does not contain a required item", path)

    def _validate_object(self, instance, schema, path):
        for key in schema.get("required", []):
            if key not in instance:
                yield ValidationError(f"{key!r} is a required property", path + [key])
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            yield ValidationError(f"object has fewer than {schema['minProperties']} properties", path)
        props = schema.get("properties", {})
        for key, value in instance.items():
            if key in props:
                yield from self._validate(value, props[key], path + [key])
            else:
                ap = schema.get("additionalProperties", True)
                if ap is False:
                    yield ValidationError(f"additional property {key!r} is not allowed", path + [key])
                elif isinstance(ap, dict):
                    yield from self._validate(value, ap, path + [key])

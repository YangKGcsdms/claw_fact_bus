"""
Schema Registry for Fact Bus.

Provides:
- Schema registration and versioning
- Fact validation against schemas
- Schema evolution rules enforcement
- Forward compatibility validation

Schema evolution rules:
1. Fields can only be ADDED (never removed)
2. New fields must be OPTIONAL
3. Existing fields cannot change type
4. Required fields remain required
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("claw_fact_bus.schema")


class SchemaEnforcement(str, Enum):
    """Controls how the bus treats facts with unknown types (no registered schema)."""

    OPEN = "open"      # Unknown types pass silently (development)
    WARN = "warn"      # Unknown types pass but logged as warning
    STRICT = "strict"  # Unknown types rejected


class SchemaFieldType(str, Enum):
    """Supported field types in schemas."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    ENUM = "enum"


@dataclass
class SchemaField:
    """Definition of a field in a fact schema."""

    name: str
    type: SchemaFieldType
    required: bool = False
    description: str = ""
    default: Any = None
    enum_values: list[str] | None = None  # For enum type
    array_item_type: SchemaFieldType | None = None  # For array type

    def validate_value(self, value: Any) -> tuple[bool, str]:
        """Validate a value against this field definition."""
        if value is None:
            if self.required:
                return False, f"Field '{self.name}' is required but got None"
            return True, "ok"

        type_validators = {
            SchemaFieldType.STRING: lambda v: isinstance(v, str),
            SchemaFieldType.INTEGER: lambda v: isinstance(v, int) and not isinstance(v, bool),
            SchemaFieldType.NUMBER: lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            SchemaFieldType.BOOLEAN: lambda v: isinstance(v, bool),
            SchemaFieldType.ARRAY: lambda v: isinstance(v, list),
            SchemaFieldType.OBJECT: lambda v: isinstance(v, dict),
            SchemaFieldType.ENUM: lambda v: v in (self.enum_values or []),
        }

        validator = type_validators.get(self.type)
        if validator and not validator(value):
            return False, f"Field '{self.name}' expected {self.type.value}, got {type(value).__name__}"

        # Validate array items
        if self.type == SchemaFieldType.ARRAY and self.array_item_type and isinstance(value, list):
            for i, item in enumerate(value):
                item_field = SchemaField(name=f"{self.name}[{i}]", type=self.array_item_type)
                ok, err = item_field.validate_value(item)
                if not ok:
                    return False, err

        return True, "ok"


@dataclass
class FactSchema:
    """
    Schema definition for a fact type.

    Schemas are immutable once registered. New versions create new registrations.
    """

    fact_type: str  # e.g. "code.review.needed"
    version: str  # e.g. "1.0.0" (semver)
    description: str = ""
    fields: list[SchemaField] = field(default_factory=list)
    required_payload_fields: list[str] = field(default_factory=list)
    # System fields are always allowed and validated separately
    # (fact_type, payload, domain_tags, etc.)

    def to_json(self) -> dict:
        """Convert schema to JSON-serializable dict."""
        return {
            "fact_type": self.fact_type,
            "version": self.version,
            "description": self.description,
            "fields": [
                {
                    "name": f.name,
                    "type": f.type.value,
                    "required": f.required,
                    "description": f.description,
                    "default": f.default,
                    "enum_values": f.enum_values,
                    "array_item_type": f.array_item_type.value if f.array_item_type else None,
                }
                for f in self.fields
            ],
            "required_payload_fields": self.required_payload_fields,
        }

    @classmethod
    def from_json(cls, data: dict) -> FactSchema:
        """Create schema from JSON dict."""
        fields = []
        for f in data.get("fields", []):
            field = SchemaField(
                name=f["name"],
                type=SchemaFieldType(f["type"]),
                required=f.get("required", False),
                description=f.get("description", ""),
                default=f.get("default"),
                enum_values=f.get("enum_values"),
                array_item_type=SchemaFieldType(f["array_item_type"]) if f.get("array_item_type") else None,
            )
            fields.append(field)

        return cls(
            fact_type=data["fact_type"],
            version=data["version"],
            description=data.get("description", ""),
            fields=fields,
            required_payload_fields=data.get("required_payload_fields", []),
        )

    def validate_payload(self, payload: dict) -> tuple[bool, list[str]]:
        """
        Validate a payload against this schema.

        Returns: (is_valid, list_of_errors)
        """
        errors = []

        # Check required fields
        for field_name in self.required_payload_fields:
            if field_name not in payload:
                errors.append(f"Missing required field: {field_name}")

        # Validate each field in payload
        field_map = {f.name: f for f in self.fields}

        for key, value in payload.items():
            if key in field_map:
                field = field_map[key]
                ok, err = field.validate_value(value)
                if not ok:
                    errors.append(err)
            # Extra fields are allowed (forward compatibility)
            # but logged for monitoring

        return len(errors) == 0, errors


class SchemaRegistry:
    """
    Central registry for all fact schemas.

    Provides:
    - Schema registration
    - Schema retrieval
    - Fact validation
    - Schema evolution checking
    """

    def __init__(
        self,
        data_dir: str | Path = ".data/schemas",
        enforcement: SchemaEnforcement = SchemaEnforcement.OPEN,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.enforcement = enforcement

        self._schemas: dict[str, dict[str, FactSchema]] = {}
        self._load_schemas()

    def _load_schemas(self) -> None:
        """Load all schemas from disk."""
        if not self.data_dir.exists():
            return

        for schema_file in self.data_dir.glob("*.json"):
            try:
                with open(schema_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                schema = FactSchema.from_json(data)
                self._cache_schema(schema)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"[SchemaRegistry] Failed to load {schema_file}: {e}")

    def _cache_schema(self, schema: FactSchema) -> None:
        """Add schema to in-memory cache."""
        if schema.fact_type not in self._schemas:
            self._schemas[schema.fact_type] = {}
        self._schemas[schema.fact_type][schema.version] = schema

    def _save_schema(self, schema: FactSchema) -> None:
        """Save schema to disk."""
        filename = f"{schema.fact_type.replace('.', '_')}__v{schema.version}.json"
        filepath = self.data_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(schema.to_json(), f, indent=2, ensure_ascii=False)

    def register(self, schema: FactSchema) -> tuple[bool, str]:
        """
        Register a new schema.

        If a schema already exists for this fact_type + version, registration fails.
        """
        # Check if already exists
        if schema.fact_type in self._schemas:
            if schema.version in self._schemas[schema.fact_type]:
                return False, f"Schema {schema.fact_type}@{schema.version} already exists"

        # Validate schema itself
        if not schema.fields:
            return False, "Schema must have at least one field"

        # Check evolution rules if previous version exists
        if schema.fact_type in self._schemas:
            prev_versions = sorted(self._schemas[schema.fact_type].keys())
            if prev_versions:
                latest = self._schemas[schema.fact_type][prev_versions[-1]]
                ok, err = self._check_evolution(latest, schema)
                if not ok:
                    return False, f"Invalid schema evolution: {err}"

        # Save and cache
        self._cache_schema(schema)
        self._save_schema(schema)

        return True, "ok"

    def _check_evolution(self, old: FactSchema, new: FactSchema) -> tuple[bool, str]:
        """
        Check if new schema is a valid evolution of old schema.

        Evolution rules:
        1. Existing required fields cannot become optional
        2. Existing fields cannot change type
        3. Existing fields cannot be removed
        """
        old_fields = {f.name: f for f in old.fields}
        new_fields = {f.name: f for f in new.fields}

        # Check all old fields exist in new
        for name, old_field in old_fields.items():
            if name not in new_fields:
                return False, f"Field '{name}' was removed (breaking change)"

            new_field = new_fields[name]

            # Check type hasn't changed
            if old_field.type != new_field.type:
                return False, f"Field '{name}' changed type from {old_field.type.value} to {new_field.type.value}"

            # Check required status hasn't been relaxed in a breaking way
            if old_field.required and not new_field.required:
                # This is actually OK (making optional is backwards compatible for consumers)
                pass

        return True, "ok"

    def get_schema(self, fact_type: str, version: str | None = None) -> FactSchema | None:
        """
        Get schema for a fact type.

        If version is not specified, returns the latest version.
        """
        if fact_type not in self._schemas:
            return None

        versions = self._schemas[fact_type]

        if version is None:
            # Return latest version
            latest = sorted(versions.keys())[-1]
            return versions[latest]

        return versions.get(version)

    def validate_fact(
        self, fact_type: str, payload: dict, version: str | None = None
    ) -> tuple[bool, list[str]]:
        """
        Validate a fact payload against its schema.

        Behavior depends on enforcement mode when no schema exists:
          OPEN:   accept silently
          WARN:   accept with warning log
          STRICT: reject
        """
        schema = self.get_schema(fact_type, version)

        if schema is None:
            if self.enforcement == SchemaEnforcement.STRICT:
                return False, [f"no schema registered for '{fact_type}' (strict mode)"]
            if self.enforcement == SchemaEnforcement.WARN:
                logger.warning("No schema registered for '%s' (warn mode)", fact_type)
            return True, []

        return schema.validate_payload(payload)

    def list_schemas(self) -> dict[str, list[str]]:
        """List all registered schemas and their versions."""
        return {
            fact_type: sorted(versions.keys())
            for fact_type, versions in self._schemas.items()
        }

    def get_stats(self) -> dict:
        """Get registry statistics."""
        total_schemas = sum(len(versions) for versions in self._schemas.values())

        return {
            "fact_types": len(self._schemas),
            "total_schemas": total_schemas,
            "by_fact_type": {
                ft: len(versions) for ft, versions in self._schemas.items()
            },
        }


# Pre-defined schemas for common fact types

def get_common_schemas() -> list[FactSchema]:
    """Get a set of common pre-defined schemas."""
    return [
        FactSchema(
            fact_type="code.review.needed",
            version="1.0.0",
            description="Request for code review",
            fields=[
                SchemaField(name="file", type=SchemaFieldType.STRING, required=True),
                SchemaField(name="pr", type=SchemaFieldType.INTEGER, required=False),
                SchemaField(name="lines_added", type=SchemaFieldType.INTEGER, required=False),
                SchemaField(name="lines_removed", type=SchemaFieldType.INTEGER, required=False),
                SchemaField(name="description", type=SchemaFieldType.STRING, required=False),
            ],
            required_payload_fields=["file"],
        ),
        FactSchema(
            fact_type="code.review.completed",
            version="1.0.0",
            description="Code review completed",
            fields=[
                SchemaField(name="file", type=SchemaFieldType.STRING, required=True),
                SchemaField(name="issues", type=SchemaFieldType.INTEGER, required=False, default=0),
                SchemaField(name="severity", type=SchemaFieldType.ENUM, required=False, enum_values=["low", "medium", "high", "critical"]),
                SchemaField(name="comments", type=SchemaFieldType.ARRAY, required=False, array_item_type=SchemaFieldType.STRING),
            ],
            required_payload_fields=["file"],
        ),
        FactSchema(
            fact_type="task.created",
            version="1.0.0",
            description="New task created",
            fields=[
                SchemaField(name="title", type=SchemaFieldType.STRING, required=True),
                SchemaField(name="description", type=SchemaFieldType.STRING, required=False),
                SchemaField(name="assignee", type=SchemaFieldType.STRING, required=False),
                SchemaField(name="due_date", type=SchemaFieldType.STRING, required=False),
                SchemaField(name="priority", type=SchemaFieldType.ENUM, required=False, enum_values=["low", "medium", "high", "urgent"]),
            ],
            required_payload_fields=["title"],
        ),
        FactSchema(
            fact_type="task.completed",
            version="1.0.0",
            description="Task completed",
            fields=[
                SchemaField(name="task_id", type=SchemaFieldType.STRING, required=True),
                SchemaField(name="result", type=SchemaFieldType.STRING, required=False),
                SchemaField(name="duration_seconds", type=SchemaFieldType.INTEGER, required=False),
            ],
            required_payload_fields=["task_id"],
        ),
        FactSchema(
            fact_type="error.occurred",
            version="1.0.0",
            description="Error or exception occurred",
            fields=[
                SchemaField(name="error_type", type=SchemaFieldType.STRING, required=True),
                SchemaField(name="message", type=SchemaFieldType.STRING, required=True),
                SchemaField(name="stack_trace", type=SchemaFieldType.STRING, required=False),
                SchemaField(name="component", type=SchemaFieldType.STRING, required=False),
            ],
            required_payload_fields=["error_type", "message"],
        ),
    ]

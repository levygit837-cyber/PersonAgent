# Project Map: pydantic

## Overview

**pydantic** is a mature, production-grade data validation library for Python that uses Python type hints to define and validate data structures. It is one of the most widely-used Python libraries in the ecosystem, with over 500M monthly downloads.

- **Purpose**: Define data models using standard Python type annotations and automatically validate, serialize, and generate JSON schemas from them.
- **Tech Stack**:
  - **Python 3.10+** (primary language)
  - **Rust** (performance-critical validation/serialization core via PyO3)
  - **Build tools**: `hatchling` (Python package), `maturin` (Rust extension), `uv` for dependency management
- **Architecture**: Split into two packages:
  - `pydantic` (Python): User-facing API, schema generation, JSON schema generation, generics, decorators, type adapters
  - `pydantic-core` (Rust + Python stubs): High-performance validation/serialization engine, core schema definitions, error handling
- **Key External Dependencies**:
  - `typing-extensions>=4.15.0`, `typing-inspection>=0.4.2` (type system introspection)
  - `annotated-types>=0.6.0` (PEP 593 constraint metadata)
  - `pydantic-core==2.47.0` (tightly coupled Rust core)
  - Optional: `email-validator`, `tzdata`

---

## Directory Structure

```
pydantic/                          # Main Python package (~11.5K LOC)
├── __init__.py                    # Dynamic imports, public API exports
├── main.py                        # BaseModel, create_model (~1,866 LOC)
├── type_adapter.py                # TypeAdapter for non-BaseModel types (~799 LOC)
├── json_schema.py                 # JSON Schema generation (~2,908 LOC)
├── functional_validators.py       # @field_validator, @model_validator, AfterValidator, etc. (~893 LOC)
├── functional_serializers.py      # @field_serializer, @model_serializer, PlainSerializer, etc. (~470 LOC)
├── fields.py                      # FieldInfo, computed_field, PrivateAttr definitions
├── config.py                      # ConfigDict, model configuration
├── types.py                       # Constrained types (conint, SecretStr, Json, etc.)
├── networks.py                    # URL and email types
├── generics.py                    # Generic model support
├── dataclasses.py                 # Pydantic dataclass support
├── root_model.py                  # RootModel for wrapping single types
├── plugin/                        # Plugin system for schema validators
│   ├── __init__.py
│   ├── _loader.py
│   └── _schema_validator.py
├── _internal/                     # Private implementation (~5,500+ LOC total)
│   ├── _model_construction.py     # ModelMetaclass, model building lifecycle (~874 LOC)
│   ├── _generate_schema.py        # CoreSchema generation from Python types (~2,932 LOC)
│   ├── _discriminated_union.py    # Discriminator application on union schemas (~494 LOC)
│   ├── _generics.py               # Generic model parametrization, caching (~540 LOC)
│   ├── _decorators.py             # Decorator inspection and metadata (~864 LOC)
│   ├── _validators.py             # Built-in validator functions
│   ├── _serializers.py            # Built-in serializer functions
│   ├── _core_utils.py             # Core schema utilities
│   ├── _typing_extra.py           # Type annotation introspection helpers (~559 LOC)
│   ├── _mock_val_ser.py           # Mock validators/serializers for deferred/circular builds (~232 LOC)
│   ├── _forward_ref.py            # Forward reference handling
│   ├── _schema_gather.py          # Schema reference inlining and cleaning (~211 LOC)
│   ├── _known_annotated_metadata.py  # Constraint metadata for Annotated types (~403 LOC)
│   └── ...
├── deprecated/                    # V1 compatibility shims
├── v1/                            # Bundled pydantic v1 source code
└── experimental/                  # Experimental features (pipeline, arguments_schema)

pydantic-core/                     # Rust extension package
├── src/                           # Rust source (~8,500+ LOC)
│   ├── lib.rs                     # PyO3 module exports, entry point
│   ├── validators/                # Rust validators (~40 validator types)
│   │   ├── mod.rs                 # SchemaValidator, CombinedValidator enum dispatch
│   │   ├── function.rs            # Python callback validators (before/after/wrap/plain)
│   │   ├── model.rs               # Model validation
│   │   ├── model_fields.rs        # Model field validation
│   │   ├── union.rs               # Union validation
│   │   ├── definitions.rs         # Schema definition references
│   │   └── ... (int, str, bytes, dict, list, datetime, url, uuid, etc.)
│   ├── serializers/               # Rust serializers (~30 serializer types)
│   │   ├── mod.rs
│   │   ├── type_serializers/      # Per-type serializers
│   │   └── ...
│   ├── input/                     # Input abstraction (JSON vs Python objects)
│   ├── errors/                    # Error types, location tracking, validation exceptions
│   ├── build_tools.rs             # Schema building utilities
│   └── ...
├── python/pydantic_core/          # Python stubs and type definitions
├── tests/                         # pydantic-core specific tests
└── Cargo.toml                     # Rust dependencies (pyo3, jiter, speedate, uuid, etc.)

tests/                             # pydantic test suite (~20,000+ LOC)
├── test_main.py                   # BaseModel tests
├── test_generics.py               # Generic model tests (~3,199 LOC)
├── test_json_schema.py            # JSON Schema tests (~7,267 LOC)
├── test_discriminated_union.py    # Discriminated union tests (~2,497 LOC)
├── test_edge_cases.py             # Edge case regression tests (~3,163 LOC)
├── test_forward_ref.py            # Forward reference tests (~1,656 LOC)
├── test_type_adapter.py           # TypeAdapter tests (~676 LOC)
├── test_annotated.py              # Annotated metadata tests (~640 LOC)
└── ...
```

---

## Key Architectural Components

### 1. Model Construction Layer (`pydantic/_internal/_model_construction.py`)
- **`ModelMetaclass`**: Metaclass for `BaseModel`. Orchestrates the entire model lifecycle:
  1. Collects annotations and base class data
  2. Builds `ConfigWrapper` from model config
  3. Collects fields and private attributes
  4. Builds decorators (`@field_validator`, `@model_serializer`, etc.)
  5. Calls `complete_model_class()` to generate schema and validator
  6. Handles generic metadata and `__class_getitem__`
- **`complete_model_class()`**: Finalizes the model by generating core schema, building `SchemaValidator`/`SchemaSerializer`, and attaching them to the class.

### 2. Schema Generation Engine (`pydantic/_internal/_generate_schema.py`)
- **`GenerateSchema`**: The central class that converts Python types into `pydantic-core` `CoreSchema` dictionaries.
- Dispatches by type: handles `BaseModel`, `TypedDict`, `dataclass`, `Union`, `Annotated`, `GenericAlias`, `ForwardRef`, etc.
- Integrates with `__get_pydantic_core_schema__` protocol (PEP 593 metadata classes like `AfterValidator`, `FieldInfo`, `Discriminator` implement this).
- Manages recursive schema references via `PydanticRecursiveRef` and definition references.
- Applies validators/serializers from decorators and `Annotated` metadata.

### 3. Rust Core (`pydantic-core`)
- **`SchemaValidator`**: Rust struct (PyO3) that holds an `Arc<CombinedValidator>` and validates Python input against the core schema.
- **`CombinedValidator`**: Enum-dispatched validator tree. Each variant handles one schema type (`IntValidator`, `ModelValidator`, `UnionValidator`, `FunctionBeforeValidator`, etc.).
- **`SchemaSerializer`**: Similar enum-dispatched serializer tree for dumping to dict/JSON.
- **`Input` trait**: Abstracts over Python objects and JSON-parsed data (via `jiter`).
- **Error system**: `ValidationError` is built in Rust with Python-level error types and locations.

### 4. Type Adapter (`pydantic/type_adapter.py`)
- Provides `BaseModel`-like validation/serialization for arbitrary types (e.g., `TypeAdapter(list[int])`).
- Uses the same `GenerateSchema` engine but without metaclass machinery.
- Handles namespace resolution from parent stack frames for forward references.

### 5. JSON Schema Generation (`pydantic/json_schema.py`)
- **`GenerateJsonSchema`**: Traverses `CoreSchema` to produce JSON Schema draft 2020-12.
- Two modes: `validation` (input schemas) and `serialization` (output schemas).
- Handles `$defs`, references, computed fields, discriminator mapping, and schema overrides from `WithJsonSchema`.

### 6. Generics System (`pydantic/_internal/_generics.py`)
- Caches parametrized generic model subclasses (`WeakValueDictionary`).
- Handles type variable substitution, recursive generic models, and `RootModel` generics.
- Uses `create_generic_submodel()` to dynamically create concrete generic classes.

### 7. Discriminated Unions (`pydantic/_internal/_discriminated_union.py`)
- **`apply_discriminator()`**: Transforms a `union` schema into a `tagged-union` schema.
- Introspects model fields to find `Literal` discriminator values and map them to choices.
- Handles nested unions, definitions, nullable wrappers, and alias resolution.

### 8. Plugin System (`pydantic/plugin/`)
- **`PluggableSchemaValidator`**: Wraps `SchemaValidator` to allow plugins to intercept `validate_python`, `validate_json`, `validate_strings` events.
- Plugins discovered via entry points (`_loader.py`).

---

## Dependency Map

### Internal Package Dependencies

```
pydantic-core (Rust/PyO3 extension)
    ^
    |  (pydantic-core exports: SchemaValidator, SchemaSerializer, CoreSchema types,
    |   ValidationError, core_schema builder functions, to_json, to_jsonable_python)
    |
pydantic (Python package)
    ├── _internal/_generate_schema.py  ──> pydantic-core (core_schema types)
    ├── _internal/_model_construction.py ──> pydantic-core (SchemaValidator, SchemaSerializer)
    ├── type_adapter.py ──> pydantic-core (SchemaValidator, SchemaSerializer)
    ├── json_schema.py ──> pydantic-core (CoreSchema, to_jsonable_python)
    ├── functional_validators.py ──> pydantic-core (core_schema)
    ├── functional_serializers.py ──> pydantic-core (core_schema)
    └── plugin/_schema_validator.py ──> pydantic-core (SchemaValidator)
```

### Key External Dependencies
- `typing-extensions`: Backports of typing features (`Annotated`, `TypeAliasType`, `get_args`, `get_origin`, etc.)
- `typing-inspection`: Type introspection utilities (`is_union_origin`, `typing_objects`, etc.)
- `annotated-types`: Standard constraint metadata (`Gt`, `Le`, `MinLen`, etc.) used by `Field()`
- `jiter` (Rust, transitive via pydantic-core): Fast JSON parser
- `speedate` (Rust, transitive): Fast datetime parser

### Data Flow (Simplified)

```
User defines model:
  class User(BaseModel):
      name: str
      age: Annotated[int, Field(gt=0), AfterValidator(check_age)]

ModelMetaclass.__new__():
  -> collects fields, decorators, config
  -> GenerateSchema.generate_schema():
       -> resolves 'str' -> core_schema.str_schema()
       -> resolves 'Annotated[int, ...]' -> wraps int_schema with:
            -> Field constraints (gt=0)
            -> AfterValidator -> core_schema.no_info_after_validator_function()
       -> returns CoreSchema dict
  -> complete_model_class():
       -> SchemaValidator(core_schema)  [Rust: builds CombinedValidator tree]
       -> SchemaSerializer(core_schema) [Rust: builds serializer tree]

Runtime validation:
  User(name="x", age=-1)
  -> BaseModel.__init__() -> SchemaValidator.validate_python() [Rust]
  -> Rust traverses CombinedValidator tree:
       -> ModelValidator -> validates fields
       -> StrValidator for 'name'
       -> IntValidator for 'age' (checks gt=0 -> fails)
       -> ValidationError raised from Rust with Python error details
```

---

## Informational Goals (Benchmark Candidates)

### Goal 1: Tracing a Custom Validator Through the Rust/Python Boundary
- **Question**: When a user defines `AfterValidator(my_func)` on an `Annotated` field, trace the complete path from the Python decorator/metadata definition through schema generation to the actual function invocation inside `pydantic-core`'s Rust validator. Identify where the Python callback is stored, how it's called from Rust, and what arguments it receives.
- **Why it's hard**: Requires crossing the PyO3 boundary. The agent must follow `AfterValidator.__get_pydantic_core_schema__` -> `_generate_schema.py` -> `core_schema.no_info_after_validator_function` -> Rust `FunctionAfterValidator` -> `function.rs` -> the actual `PyObject::call1` invocation.
- **Expected findings**:
  - `AfterValidator` lives in `pydantic/functional_validators.py`
  - It generates a `function-after` core schema node
  - Rust `FunctionAfterValidator` in `pydantic-core/src/validators/function.rs` stores the Python function as a `Py<PyAny>`
  - The validator calls Python via `self.func.call1(py, (value, info))` with `ValidationInfo` constructed in Rust
  - Error conversion happens via `convert_err()` in `function.rs`
- **Complexity**: very complex
- **Key files involved**: `pydantic/functional_validators.py`, `pydantic/_internal/_generate_schema.py`, `pydantic-core/src/validators/function.rs`, `pydantic-core/src/validators/mod.rs`

### Goal 2: How Discriminated Unions Transform Core Schemas
- **Question**: When `Discriminator` is used on a union of BaseModels, explain the exact transformation applied to the `CoreSchema` tree. Where does the discriminator inference happen, how are `Literal` field values extracted from model schemas, and what does the final `tagged-union` schema look like?
- **Why it's hard**: The transformation is recursive and stateful. The agent must understand that `apply_discriminator()` in `_discriminated_union.py` walks the schema tree, validates compatibility, extracts literal values from nested model schemas, and replaces `union` with `tagged-union`. It also handles definitions, nullable wrappers, and alias resolution.
- **Expected findings**:
  - `pydantic/_internal/_discriminated_union.py` contains `_ApplyInferredDiscriminator`
  - It walks schemas recursively using `iter_union_choices()` from pydantic-core
  - It extracts discriminator values by looking at `model`/`typed-dict` schemas and finding the field's `literal` schema
  - It calls `core_schema.tagged_union_schema()` with the choices mapping
  - `json_schema.py` has special handling to emit `discriminator` keyword in JSON Schema
- **Complexity**: complex
- **Key files involved**: `pydantic/_internal/_discriminated_union.py`, `pydantic/_internal/_generate_schema.py`, `pydantic/json_schema.py`, `pydantic-core/src/validators/union.rs`

### Goal 3: Forward Reference Resolution During Model Definition
- **Question**: If a model field uses a string forward reference (`'MyModel'`) or a `ForwardRef` object, describe the complete resolution mechanism. When is the forward reference evaluated? What namespaces are searched? How does the system handle circular references between two models?
- **Why it's hard**: Forward refs are resolved at class creation time (not import time) and involve multiple namespace sources (module globals, parent namespace, localns). The agent must also understand how circular references are handled via `PydanticRecursiveRef` and mock validators.
- **Expected findings**:
  - `pydantic/_internal/_forward_ref.py` defines `PydanticRecursiveRef`
  - `eval_type()` in `_typing_extra.py` resolves forward refs using `typing._eval_type` or `annotationlib` (3.14+)
  - `NsResolver` in `_namespace_utils.py` manages namespace precedence
  - Circular references use mock validators (`MockValSer`, `MockCoreSchema` in `_mock_val_ser.py`) that rebuild on first access
  - `complete_model_class()` uses `raise_errors=False` initially and rebuilds later for recursive models
- **Complexity**: complex
- **Key files involved**: `pydantic/_internal/_forward_ref.py`, `pydantic/_internal/_typing_extra.py`, `pydantic/_internal/_namespace_utils.py`, `pydantic/_internal/_mock_val_ser.py`, `pydantic/_internal/_model_construction.py`

### Goal 4: Generic Model Subclass Creation and Schema Rebuilding
- **Question**: When `MyModel[int]` is called on a generic BaseModel, what concrete subclass is created? How is the generic type parameter `int` substituted into the model's fields, and how does the resulting class get its own `SchemaValidator` and `SchemaSerializer`?
- **Why it's hard**: Generics use a custom `__class_getitem__`, dynamic subclass creation, type variable substitution, and a `WeakValueDictionary` cache. The schema must be rebuilt with substituted types.
- **Expected findings**:
  - `pydantic/_internal/_generics.py` defines `create_generic_submodel()` and `_GENERIC_TYPES_CACHE`
  - `BaseModel.__class_getitem__` (or `__pydantic_init_subclass__` chain) triggers parametrization
  - `replace_types()` substitutes type variables in field annotations
  - The parametrized class gets a new `ModelMetaclass.__new__` call, triggering full schema generation with concrete types
  - `get_type_ref()` in `_core_utils.py` generates unique refs including generic args
- **Complexity**: complex
- **Key files involved**: `pydantic/_internal/_generics.py`, `pydantic/_internal/_model_construction.py`, `pydantic/_internal/_core_utils.py`, `pydantic/main.py`, `pydantic/_internal/_generate_schema.py`

### Goal 5: JSON Schema Mode Differences (Validation vs Serialization)
- **Question**: For a model with `computed_field` and a `PlainSerializer` on a field, explain how the JSON Schema output differs between `mode='validation'` and `mode='serialization'`. Where in the codebase are these differences implemented, and how does the schema walker handle `SerSchema` vs `CoreSchema` nodes?
- **Why it's hard**: JSON Schema generation is a massive 2,900 LOC file with many per-schema-type handlers. The agent must find that `GenerateJsonSchema` takes a `mode` parameter, that computed fields are excluded in validation mode, and that serializer schemas can override validation schemas.
- **Expected findings**:
  - `pydantic/json_schema.py` defines `JsonSchemaMode = Literal['validation', 'serialization']`
  - `GenerateJsonSchema.__init__` accepts `mode`
  - `model_json_schema()` passes mode through
  - Computed fields only appear in serialization mode (checked in `generate_inner()` or field iteration)
  - Serializer schemas (`plain_serializer_function_ser_schema`, etc.) can provide alternative JSON schemas via `return_schema`
  - `json_schema.py` handles both `CoreSchema` and `SerSchema` types
- **Complexity**: complex
- **Key files involved**: `pydantic/json_schema.py`, `pydantic/main.py`, `pydantic/type_adapter.py`, `pydantic/functional_serializers.py`

### Goal 6: Plugin Interception of Validation Events
- **Question**: If a third-party plugin is installed (e.g., Logfire), how does it intercept `BaseModel` validation? Describe the exact mechanism from plugin discovery through `PluggableSchemaValidator` to the wrapped `validate_python` call.
- **Why it's hard**: The plugin system is small but involves entry-point discovery, protocol classes, and method wrapper building. The agent must find the entry point loading, the `PydanticPluginProtocol`, and how `build_wrapper()` chains event handlers.
- **Expected findings**:
  - `pydantic/plugin/_loader.py` discovers plugins via `importlib.metadata.entry_points`
  - `pydantic/plugin/_schema_validator.py` defines `create_schema_validator()`
  - If plugins exist, it returns `PluggableSchemaValidator` instead of bare `SchemaValidator`
  - `PluggableSchemaValidator.__init__` calls `plugin.new_schema_validator()` to get event handlers
  - `build_wrapper()` wraps each validate method with a chain of `on_validate_python` handlers
  - The wrapper calls handlers before/after the actual Rust validation
- **Complexity**: medium
- **Key files involved**: `pydantic/plugin/_schema_validator.py`, `pydantic/plugin/_loader.py`, `pydantic/plugin/__init__.py`, `pydantic/_internal/_model_construction.py`

### Goal 7: Constraint Metadata Merging for `Annotated` Types
- **Question**: When a field is declared as `Annotated[int, Field(gt=0, lt=100), Strict()]`, how are the multiple metadata items merged into a single `CoreSchema` with both constraints? Trace the path from `Field()` through `Annotated` metadata processing to the final `int_schema` with constraints.
- **Why it's hard**: Multiple metadata sources (`FieldInfo`, `AfterValidator`, `Strict`, `annotated-types` constraints) must be merged. The agent must understand `__get_pydantic_core_schema__` protocol precedence, constraint accumulation in `_known_annotated_metadata.py`, and how `FieldInfo` constraints are applied.
- **Expected findings**:
  - `Field()` returns a `FieldInfo` object in `pydantic/fields.py`
  - `GenerateSchema` handles `Annotated` by iterating over metadata items in `_generate_schema.py`
  - Each metadata item with `__get_pydantic_core_schema__` can wrap or modify the schema
  - `FieldInfo` constraints are extracted and applied via `_known_annotated_metadata.py`
  - `CONSTRAINTS_TO_ALLOWED_SCHEMAS` validates that constraints are applied to compatible schema types
  - `Strict` is handled via `core_schema.lax_or_strict_schema()` or by setting `strict=True` on the schema
  - The final schema is a single `int_schema` with `gt=0`, `lt=100`, `strict=True`
- **Complexity**: complex
- **Key files involved**: `pydantic/_internal/_generate_schema.py`, `pydantic/_internal/_known_annotated_metadata.py`, `pydantic/fields.py`, `pydantic/types.py`, `pydantic/functional_validators.py`

---

## Complexity Assessment

**Overall Rating: very complex**

### Reasoning

pydantic is a deeply layered system with significant complexity across multiple dimensions:

1. **Dual-language architecture**: The Python/Rust boundary (PyO3) means understanding any validation or serialization path requires reading both Python and Rust code. Core schemas are defined as Python dicts but executed as Rust enum trees.

2. **Metaclass-driven model construction**: `ModelMetaclass.__new__()` is a complex 874-line orchestration of annotation collection, field parsing, decorator extraction, generic metadata handling, namespace resolution, schema generation, and validator building. It handles edge cases like forward references, circular models, private attributes, and deferred builds.

3. **Massive schema generation engine**: `_generate_schema.py` (2,932 LOC) is the heart of the system. It must handle every Python type construct (unions, generics, typed dicts, dataclasses, enums, callables, forward refs, annotated types, type alias types, etc.) and produce correct core schemas. It also manages recursive references and definition inlining.

4. **Recursive and deferred builds**: Circular references between models require mock validators/serializers that lazily rebuild on first access. This creates a non-obvious execution path that is hard to trace.

5. **Generics with caching**: The generic model system uses `WeakValueDictionary` caches, dynamic subclass creation, and type variable substitution that must interact correctly with the schema generation engine.

6. **Rich plugin and decorator ecosystem**: Field validators, model validators, serializers, computed fields, and plugins all hook into the model lifecycle at different points with different precedence rules.

7. **JSON Schema parity**: The JSON Schema generator (2,908 LOC) must mirror the validation/serialization behavior of the Rust core, handling two modes, references, discriminators, and computed fields.

### Most Complex Areas

| Rank | Area | Files | Why |
|------|------|-------|-----|
| 1 | Schema Generation | `_generate_schema.py` | 2,932 LOC handling every Python type construct, recursive refs, Annotated metadata, decorators |
| 2 | JSON Schema Generation | `json_schema.py` | 2,908 LOC mapping core schemas to JSON Schema with validation/serialization duality |
| 3 | Model Metaclass | `_model_construction.py` | Orchestrates the entire model lifecycle with many edge cases |
| 4 | Rust Validation Core | `pydantic-core/src/validators/` | ~40 validator types in Rust with enum dispatch and Python callback integration |
| 5 | Discriminated Unions | `_discriminated_union.py` | Complex recursive schema transformation with literal extraction |
| 6 | Generics | `_generics.py`, `main.py` | Dynamic subclassing, caching, type substitution |

---

*Map generated by exploring pydantic v2.47+ codebase. Total Python LOC in pydantic package: ~11,500. Total Rust LOC in pydantic-core: ~8,500. Total test LOC: ~20,000+.*

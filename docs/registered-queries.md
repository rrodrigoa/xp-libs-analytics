# Parameterized registered queries

The host supplies `registered_queries` to `create_server`. Each entry accepts fixed
YAML text, an `AnalyticsQuery`, a `ParameterizedYamlQuery`, or a `PolarsQuery`. The
adapter resolves the key within the server and selects the engine through the
trusted context. Dataset bindings remain local to that engine.

Use `analytics_describe_query(key)` to obtain the parameter JSON Schema. Call
`analytics_query_by_key(key, parameters)` with a JSON object. Omitting the object
applies the model defaults and still enforces required fields. Fixed queries accept
an omitted or empty object. With `generated_tools=True`, the tool
`analytics_registered_<key>` accepts the same values as named arguments. Both
surfaces validate requests against the same model.

Parameter models use strict JSON validation. Integer and boolean values require
their JSON types. Enums use their declared JSON values and datetimes use RFC 3339
strings. The engine forbids undeclared fields and applies byte, depth, node,
collection, and string limits before model validation. Effective values,
including defaults, are also subject to the resource limits. Host models can
enable Pydantic's `validate_default` setting to validate defaults against field
constraints. Model validators and serializers execute as trusted host code.

## Fixed YAML

Create `ParameterizedYamlQuery(yaml, parameters=Model)` and invoke it directly with
`engine.query_parameterized(definition, values)` or register it with the MCP
adapter. Place `{$param: minimum}` where the query expects a whole literal value.
Supported positions include predicate values, membership lists, range bounds,
matching pattern values and thresholds, and time range bounds. Placeholder names
refer to Python model fields. A bound string is a literal even if it contains YAML
syntax. The dataset name, field paths, operators, aggregate aliases, and other
structural parts come from the fixed template. The resulting query goes through
the normal typed planner.

## Native Polars

Create `PolarsQuery(dataset, fields, transform, parameters, output_schema)`
and invoke it with `engine.query_polars(definition, values)` or register it with the
MCP adapter. The host supplies the dataset name, JSON Pointer paths, and a callable
that takes a Polars DataFrame and the validated Pydantic model, then returns a
Polars DataFrame. The input contains every row from the leased snapshot, a
`row_index`, one column per authorized scalar path, and one Boolean
`present:<path>` column per path. Missing values have a false presence flag and a
null cell. Explicit nulls have a true presence flag and a null cell. Container and
mixed-type projections are rejected.

The output must match the declared column names, order, and types. Supported
output types are `integer` (Int64), `float` (Float64), `boolean`, `string`,
`datetime` (timezone-aware), and `null`. Values can be nullable. Oversized outputs
return a structured error. `max_output_rows` limits returned rows after the
transformation, and the engine enforces its result byte limit.

For isolated execution, construct the engine with `isolated=True` and an explicit
`native_transforms={"count": count_values}` registry. The transformation and the
parameter model must be top-level definitions in importable host modules. The
worker resolves the host-selected references after setting its resource limits.
MCP arguments supply parameter values only. Native transformations have the
privileges of the host or worker process and must come from trusted application
code. Use operating-system or container controls to restrict process access as
needed. The OS worker limits apply to execution, and the host bounds projection
and parameter processing.

Run `python -m examples.registered_queries` from the source checkout with the MCP
extra installed. The example uses one parameter model with both query types.

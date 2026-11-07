"""Restricted YAML boundary; no global PyYAML resolver mutation."""

import math
import re
from typing import Any

import yaml
from yaml import events, nodes

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.policy import Limits


def fault(code: str, mark: Any) -> AnalyticsError:
    return AnalyticsError(code, line=mark.line + 1, column=mark.column + 1)


class RestrictedLoader(yaml.SafeLoader):
    yaml_implicit_resolvers: dict[str, list[tuple[str, re.Pattern[str]]]] = {}


for tag, pattern, initial in [
    ("bool", r"^(?:true|false)$", "tf"),
    ("null", r"^null$", "n"),
    ("int", r"^-?(?:0|[1-9][0-9]*)$", "-0123456789"),
    (
        "float",
        r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)$",
        "-0123456789",
    ),
]:
    RestrictedLoader.add_implicit_resolver("tag:yaml.org,2002:" + tag, re.compile(pattern), initial)


DEFAULT_LIMITS = Limits()


def parse_yaml(
    text: str,
    limits: Limits = DEFAULT_LIMITS,
    *,
    source_marks: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    if not isinstance(text, str):
        raise AnalyticsError("QUERY_MALFORMED")
    try:
        encoded = text.encode("utf-8", "strict")
    except UnicodeError:
        raise AnalyticsError("QUERY_YAML_SCALAR_INVALID") from None
    if len(encoded) > limits.max_query_bytes:
        raise AnalyticsError("QUERY_YAML_COMPLEXITY_LIMIT")
    depth = docs = count = 0
    widths: list[int] = []
    try:
        for event in yaml.parse(text, Loader=RestrictedLoader):
            count += 1
            if count > limits.max_yaml_nodes:
                raise fault("QUERY_YAML_COMPLEXITY_LIMIT", event.start_mark)
            if isinstance(event, events.DocumentStartEvent):
                docs += 1
                if docs > 1:
                    raise fault("QUERY_YAML_MULTI_DOCUMENT", event.start_mark)
                if event.tags or event.version:
                    raise fault("QUERY_YAML_TAG_FORBIDDEN", event.start_mark)
            if isinstance(event, events.AliasEvent):
                raise fault("QUERY_YAML_ALIAS_FORBIDDEN", event.start_mark)
            if getattr(event, "anchor", None):
                raise fault("QUERY_YAML_ANCHOR_FORBIDDEN", event.start_mark)
            if getattr(event, "tag", None):
                raise fault("QUERY_YAML_TAG_FORBIDDEN", event.start_mark)
            if isinstance(event, (events.ScalarEvent, events.CollectionStartEvent)) and widths:
                widths[-1] += 1
                if widths[-1] > limits.max_collection_items:
                    raise fault("QUERY_YAML_COMPLEXITY_LIMIT", event.start_mark)
            if isinstance(event, events.CollectionStartEvent):
                depth += 1
                widths.append(0)
                if depth > limits.max_yaml_depth:
                    raise fault("QUERY_YAML_COMPLEXITY_LIMIT", event.start_mark)
            elif isinstance(event, events.CollectionEndEvent):
                depth -= 1
                widths.pop()
            elif isinstance(event, events.ScalarEvent):
                if len(event.value) > limits.max_scalar_chars:
                    raise fault("QUERY_YAML_COMPLEXITY_LIMIT", event.start_mark)
                if any(
                    ord(c) < 32 and c not in "\n\r\t" or 0xD800 <= ord(c) <= 0xDFFF
                    for c in event.value
                ):
                    raise fault("QUERY_YAML_SCALAR_INVALID", event.start_mark)
        loader = RestrictedLoader(text)
        marks: dict[str, tuple[int, int]] = {}
        try:
            root = loader.get_single_node()

            def convert(node: Any, path: str) -> Any:
                if node is not None:
                    marks[path] = (node.start_mark.line + 1, node.start_mark.column + 1)
                if isinstance(node, nodes.MappingNode):
                    result = {}
                    for key, value in node.value:
                        k = convert(key, path)
                        if not isinstance(k, str):
                            raise fault("QUERY_YAML_ROOT_INVALID", key.start_mark)
                        if k == "<<":
                            raise fault("QUERY_YAML_ALIAS_FORBIDDEN", key.start_mark)
                        if k in result:
                            raise fault("QUERY_YAML_DUPLICATE_KEY", key.start_mark)
                        result[k] = convert(value, path + "." + k)
                    return result
                if isinstance(node, nodes.SequenceNode):
                    return [convert(v, path + f"[{i}]") for i, v in enumerate(node.value)]
                if isinstance(node, nodes.ScalarNode):
                    value = loader.construct_object(node)
                    if isinstance(value, float) and not math.isfinite(value):
                        raise fault("QUERY_YAML_SCALAR_INVALID", node.start_mark)
                    if (
                        isinstance(value, int)
                        and not isinstance(value, bool)
                        and not -(2**63) <= value < 2**63
                    ):
                        raise fault("QUERY_YAML_SCALAR_INVALID", node.start_mark)
                    if node.style is None and re.match(
                        r"^(?:[+-]?\.(?:nan|inf)|[+-]?0[xob][0-9a-f]+|0[0-9]+)$", node.value, re.I
                    ):
                        raise fault("QUERY_YAML_SCALAR_INVALID", node.start_mark)
                    return value
                raise AnalyticsError("QUERY_YAML_ROOT_INVALID")

            result = convert(root, "$")
        finally:
            loader.dispose()
        if not isinstance(result, dict) or not result:
            raise AnalyticsError("QUERY_YAML_ROOT_INVALID")
        if source_marks is not None:
            source_marks.update(marks)
        return result
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        if mark:
            raise fault("QUERY_YAML_INVALID", mark) from None
        raise AnalyticsError("QUERY_YAML_INVALID") from None

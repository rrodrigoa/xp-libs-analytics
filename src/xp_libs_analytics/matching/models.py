"""Strict matching rules shared by scalar and multi-field source predicates."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Normalization(MatchModel):
    case_sensitive: bool = True
    unicode: Literal["none", "nfc", "nfkc"] = "none"
    trim: bool = False


class LiteralRule(MatchModel):
    op: Literal[
        "eq",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "word",
        "like",
        "ilike",
        "regex",
    ]
    value: str = Field(min_length=1, max_length=1024)


class FuzzyRule(MatchModel):
    op: Literal["fuzzy"]
    value: str = Field(min_length=1, max_length=1024)
    algorithm: Literal["ratio", "wratio", "token_sort"]
    min_score: float = Field(ge=0, le=100)


StringRule = Annotated[LiteralRule | FuzzyRule, Field(discriminator="op")]


class MatchFields(MatchModel):
    fields: list[str] = Field(min_length=1, max_length=10)
    patterns: list[StringRule] = Field(min_length=1, max_length=10)
    normalization: Normalization = Field(default_factory=Normalization)
    mode: Literal["any"] = "any"


class MatchFieldsPredicate(MatchModel):
    match: MatchFields

    @property
    def op(self) -> Literal["match"]:
        return "match"


class StringPredicate(MatchModel):
    op: Literal["not_contains", "word", "like", "ilike", "regex"]
    field: str
    value: str = Field(min_length=1, max_length=1024)
    normalization: Normalization | None = None


class FuzzyPredicate(FuzzyRule):
    field: str
    normalization: Normalization | None = None


class MatchingDetails(MatchModel):
    include: bool = False
    top_values: int = Field(default=10, ge=1, le=20)
    include_raw_values: bool = False


TEXT_OPS = {
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "word",
    "like",
    "ilike",
    "regex",
    "fuzzy",
}


def is_matching(node: Any, types: dict[str, str] | None = None) -> bool:
    if node.op == "match" or node.op in TEXT_OPS:
        return True
    if node.op in {"eq", "ne"}:
        if node.normalization is not None:
            return True
        return isinstance(node.value, str) and (
            types is None or types.get(node.field) in {None, "string", "null"}
        )
    return False

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageSpec:
    grammar: str
    function_types: frozenset[str]
    class_types: frozenset[str] = frozenset()
    standalone_types: frozenset[str] = frozenset()
    wrapper_fields: dict[str, str] = field(default_factory=dict)
    variable_types: frozenset[str] = frozenset()
    function_value_types: frozenset[str] = frozenset()
    comment_types: frozenset[str] = frozenset({"comment"})
    receiver_field: str | None = None


PYTHON = LanguageSpec(
    grammar="python",
    function_types=frozenset({"function_definition"}),
    class_types=frozenset({"class_definition"}),
    wrapper_fields={"decorated_definition": "definition"},
)

JAVASCRIPT_FUNCTIONS = frozenset({"function_declaration", "generator_function_declaration", "method_definition"})
JAVASCRIPT_VALUES = frozenset({"arrow_function", "function_expression", "function", "generator_function"})


def javascript_like(grammar: str, standalone: frozenset[str] = frozenset()) -> LanguageSpec:
    return LanguageSpec(
        grammar=grammar,
        function_types=JAVASCRIPT_FUNCTIONS,
        class_types=frozenset({"class_declaration", "abstract_class_declaration", "class"}),
        standalone_types=standalone,
        wrapper_fields={"export_statement": "declaration"},
        variable_types=frozenset({"lexical_declaration", "variable_declaration"}),
        function_value_types=JAVASCRIPT_VALUES,
    )


TYPESCRIPT_STANDALONE = frozenset({"interface_declaration", "type_alias_declaration", "enum_declaration"})

GO = LanguageSpec(
    grammar="go",
    function_types=frozenset({"function_declaration", "method_declaration"}),
    standalone_types=frozenset({"type_declaration"}),
    receiver_field="receiver",
)

JAVA = LanguageSpec(
    grammar="java",
    function_types=frozenset({"method_declaration", "constructor_declaration"}),
    class_types=frozenset(
        {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
    ),
    comment_types=frozenset({"line_comment", "block_comment"}),
)

LANGUAGE_SPECS: dict[str, LanguageSpec] = {
    "python": PYTHON,
    "javascript": javascript_like("javascript"),
    "typescript": javascript_like("typescript", TYPESCRIPT_STANDALONE),
    "tsx": javascript_like("tsx", TYPESCRIPT_STANDALONE),
    "go": GO,
    "java": JAVA,
}

SUPPORTED_GRAMMARS: tuple[str, ...] = tuple(sorted({spec.grammar for spec in LANGUAGE_SPECS.values()}))

import re
from dataclasses import dataclass
from typing import Literal

from tree_sitter import Node

from codebase_qa.chunking.treesitter.languages import LanguageSpec

DefinitionKind = Literal["function", "class", "standalone"]
MAX_SIGNATURE_CHARS = 200


@dataclass(frozen=True)
class Definition:
    kind: DefinitionKind
    outer: Node
    inner: Node
    start_line: int
    end_line: int


def start_line(node: Node) -> int:
    return node.start_point.row + 1


def end_line(node: Node) -> int:
    row, column = node.end_point.row, node.end_point.column
    return row + 1 if column > 0 else max(row, node.start_point.row + 1)


def node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def unwrap(node: Node, spec: LanguageSpec) -> Node:
    field_name = spec.wrapper_fields.get(node.type)
    if field_name is None:
        return node
    inner = node.child_by_field_name(field_name)
    return unwrap(inner, spec) if inner is not None else node


def function_value(node: Node, spec: LanguageSpec) -> Node | None:
    if node.type not in spec.variable_types:
        return None
    declarators = [child for child in node.named_children if child.type == "variable_declarator"]
    if len(declarators) != 1:
        return None
    value = declarators[0].child_by_field_name("value")
    return value if value is not None and value.type in spec.function_value_types else None


def classify(node: Node, spec: LanguageSpec) -> DefinitionKind | None:
    inner = unwrap(node, spec)
    if inner.type in spec.function_types or function_value(inner, spec) is not None:
        return "function"
    if inner.type in spec.class_types:
        return "class"
    if inner.type in spec.standalone_types:
        return "standalone"
    return None


def body_of(node: Node, spec: LanguageSpec) -> Node | None:
    value = function_value(node, spec)
    target = value if value is not None else node
    return target.child_by_field_name("body")


def signature(node: Node, source: bytes, spec: LanguageSpec) -> str:
    body = body_of(node, spec)
    end = body.start_byte if body is not None else node.end_byte
    text = source[node.start_byte : end].decode("utf-8", errors="replace")
    collapsed = re.sub(r"\s*(\{|=>|=)\s*$", "", re.sub(r"\s+", " ", text).strip())
    return collapsed[:MAX_SIGNATURE_CHARS]


def name_of(node: Node, source: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        declarator = next((c for c in node.named_children if c.type == "variable_declarator"), None)
        name = declarator.child_by_field_name("name") if declarator is not None else None
    return node_text(name, source) if name is not None else "<anonymous>"


def receiver_type(node: Node, source: bytes, spec: LanguageSpec) -> str | None:
    if spec.receiver_field is None:
        return None
    receiver = node.child_by_field_name(spec.receiver_field)
    if receiver is None:
        return None
    identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node_text(receiver, source))
    return identifiers[-1] if identifiers else None


def definitions_in(container: Node, spec: LanguageSpec) -> list[Definition]:
    found: list[Definition] = []
    children = member_nodes(container)
    for index, child in enumerate(children):
        kind = classify(child, spec)
        if kind is None:
            continue
        first = child
        cursor = index - 1
        while cursor >= 0 and children[cursor].type in spec.comment_types:
            if end_line(children[cursor]) + 1 < start_line(first):
                break
            first = children[cursor]
            cursor -= 1
        found.append(Definition(kind, child, unwrap(child, spec), start_line(first), end_line(child)))
    return found


def class_body(class_node: Node) -> Node | None:
    return class_node.child_by_field_name("body")


def member_nodes(container: Node) -> list[Node]:
    members: list[Node] = []
    for child in container.named_children:
        if child.type.endswith("body_declarations"):
            members.extend(child.named_children)
        else:
            members.append(child)
    return members

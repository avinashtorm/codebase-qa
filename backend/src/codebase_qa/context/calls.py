import re

from codebase_qa.context.catalog import ChunkCatalog, defined_name
from codebase_qa.models import Chunk

CALL = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*(?:<[^<>()]*>)?\(")
IGNORED = frozenset(
    {
        "if", "for", "while", "switch", "return", "catch", "function", "def", "class", "print", "len", "str", "int",
        "float", "bool", "dict", "list", "set", "tuple", "super", "isinstance", "range", "enumerate", "zip", "map",
        "filter", "sorted", "open", "type", "await", "async", "new", "typeof", "require", "import", "get", "set_",
        "update", "delete", "create", "add", "run", "main", "init", "__init__", "then", "useState", "useEffect",
    }
)


def called_names(chunk: Chunk) -> list[str]:
    names = [name for name in CALL.findall(chunk.content) if len(name) >= 3 and name not in IGNORED]
    return list(dict.fromkeys(names))


def callee_chunks(
    chunks: list[Chunk],
    catalog: ChunkCatalog,
    max_functions: int,
    max_lines: int,
    max_definitions: int = 2,
) -> list[Chunk]:
    present = {(chunk.path, chunk.start_line, chunk.end_line) for chunk in chunks}
    own = {defined_name(chunk) for chunk in chunks}
    selected: list[Chunk] = []
    used_lines = 0
    for chunk in chunks:
        for name in called_names(chunk):
            if len(selected) >= max_functions:
                return selected
            definitions = catalog.definitions.get(name, [])
            if name in own or not definitions or len({c.path for c in definitions}) > max_definitions:
                continue
            definition = definitions[0]
            key = (definition.path, definition.start_line, definition.end_line)
            size = definition.end_line - definition.start_line + 1
            if key in present or used_lines + size > max_lines:
                continue
            present.add(key)
            selected.append(definition)
            used_lines += size
    return selected

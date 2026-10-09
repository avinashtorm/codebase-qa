import textwrap

import pytest

from codebase_qa.chunking.fixed import FixedSizeChunker
from codebase_qa.chunking.treesitter.chunker import TreeSitterChunker
from codebase_qa.ingestion.walker import content_hash
from codebase_qa.models import Chunk, SourceFile


def source(path: str, language: str, code: str) -> SourceFile:
    content = textwrap.dedent(code).lstrip("\n")
    return SourceFile("repo", path, language, content, content_hash(content))


def chunk(file: SourceFile, max_lines: int = 60) -> list[Chunk]:
    chunks = TreeSitterChunker(max_lines=max_lines).chunk(file)
    lines = file.content.split("\n")
    for item in chunks:
        assert item.content == "\n".join(lines[item.start_line - 1 : item.end_line])
        assert item.header.startswith(f"# File: {file.path}")
    return chunks


def spans(chunks: list[Chunk]) -> list[tuple[int, int]]:
    return [(c.start_line, c.end_line) for c in chunks]


def find(chunks: list[Chunk], text: str) -> Chunk:
    return next(c for c in chunks if text in c.header)


PYTHON = """
import os

TIMEOUT = 5


class AuthService:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def login(self, user: str) -> str:
        return f"{user}:{self.secret}"


@decorator
def helper(value: int) -> int:
    return value * 2


print(helper(TIMEOUT))
"""


def test_python_methods_functions_and_top_level() -> None:
    chunks = chunk(source("app/auth.py", "python", PYTHON))
    assert spans(chunks) == [(1, 3), (7, 8), (10, 11), (14, 16), (19, 19)]
    login = find(chunks, "def login")
    assert "# Class: AuthService" in login.header
    assert "# Method: def login(self, user: str) -> str:" in login.header
    helper = find(chunks, "def helper")
    assert helper.content.startswith("@decorator")
    assert "# Function:" in helper.header
    assert find(chunks, "Top-level").content.startswith("import os")


def test_python_class_with_fields_keeps_docstring_and_fields() -> None:
    code = '''
    class Settings:
        """Application settings."""

        name: str = "app"
        debug: bool = False

        def url(self) -> str:
            return self.name
    '''
    chunks = chunk(source("s.py", "python", code))
    class_chunk = find(chunks, "# Class: class Settings:")
    assert (class_chunk.start_line, class_chunk.end_line) == (1, 5)
    assert find(chunks, "# Method:").start_line == 7


def test_python_oversized_function_splits_at_statement_boundaries() -> None:
    body = "\n".join(f"    value_{n} = compute({n})" for n in range(1, 31))
    code = f"def big(x: int) -> int:\n{body}\n    return x\n"
    file = SourceFile("repo", "big.py", "python", code, content_hash(code))
    chunks = chunk(file, max_lines=12)
    assert len(chunks) > 1
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 32
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_line == previous.end_line + 1
    for item in chunks:
        assert item.end_line - item.start_line + 1 <= 12
        assert "# Function: def big(x: int) -> int:" in item.header


JAVASCRIPT = """
import { api } from "./api"

export function fetchUser(id) {
  return api.get(`/users/${id}`)
}

class Cart {
  constructor() {
    this.items = []
  }

  add(item) {
    this.items.push(item)
  }
}

const total = (items) => {
  return items.length
}
"""


def test_javascript_functions_classes_and_arrow_functions() -> None:
    chunks = chunk(source("src/cart.js", "javascript", JAVASCRIPT))
    assert spans(chunks) == [(1, 1), (3, 5), (8, 10), (12, 14), (17, 19)]
    assert "# Function: function fetchUser(id)" in chunks[1].header
    add = find(chunks, "add(item)")
    assert "# Class: Cart" in add.header
    assert "# Function: const total = (items)" in chunks[-1].header


TYPESCRIPT = """
export interface User {
  id: string
  name: string
}

export class UserStore {
  private users: User[] = []

  find(id: string): User | undefined {
    return this.users.find((u) => u.id === id)
  }
}

export const greet = (user: User): string => `hi ${user.name}`
"""


def test_typescript_interfaces_classes_and_exports() -> None:
    chunks = chunk(source("src/store.ts", "typescript", TYPESCRIPT))
    assert spans(chunks) == [(1, 4), (6, 7), (9, 11), (14, 14)]
    assert "# Definition: interface User" in chunks[0].header
    assert "# Class: class UserStore" in chunks[1].header
    find_chunk = find(chunks, "find(id: string)")
    assert "# Class: UserStore" in find_chunk.header
    assert "# Function: const greet = (user: User): string" in chunks[-1].header


def test_tsx_component_is_one_chunk() -> None:
    code = """
    import React from "react"

    export const Button = ({ label }: { label: string }) => {
      const onClick = () => console.log(label)
      return <button onClick={onClick}>{label}</button>
    }
    """
    chunks = chunk(source("src/Button.tsx", "tsx", code))
    assert spans(chunks) == [(1, 1), (3, 6)]
    assert "# Function: const Button = ({ label }: { label: string })" in chunks[1].header


GO = """
package store

import "fmt"

// Store keeps items.
type Store struct {
	items []string
}

func New() *Store {
	return &Store{}
}

func (s *Store) Add(item string) {
	s.items = append(s.items, item)
	fmt.Println(item)
}
"""


def test_go_types_functions_and_methods() -> None:
    chunks = chunk(source("store/store.go", "go", GO))
    assert spans(chunks) == [(1, 3), (5, 8), (10, 12), (14, 17)]
    assert chunks[1].content.startswith("// Store keeps items.")
    assert "# Function: func New() *Store" in chunks[2].header
    assert "# Class: Store" in chunks[3].header
    assert "# Method: func (s *Store) Add(item string)" in chunks[3].header


JAVA = """
package app;

public class OrderService {
    private final Repo repo;

    public OrderService(Repo repo) {
        this.repo = repo;
    }

    public Order place(Order order) {
        return repo.save(order);
    }

    static class Repo {
        Order save(Order order) {
            return order;
        }
    }
}
"""


def test_java_classes_constructors_methods_and_nested_classes() -> None:
    chunks = chunk(source("src/OrderService.java", "java", JAVA))
    assert (6, 8) in spans(chunks)
    place = find(chunks, "place(Order order)")
    assert (place.start_line, place.end_line) == (10, 12)
    assert "# Class: OrderService" in place.header
    save = find(chunks, "save(Order order)")
    assert "# Class: OrderService.Repo" in save.header
    class_chunk = find(chunks, "# Class: public class OrderService")
    assert class_chunk.start_line == 3


@pytest.mark.parametrize(("path", "language"), [("README.md", "markdown"), ("config.yml", "yaml")])
def test_unsupported_languages_fall_back_to_fixed_chunks(path: str, language: str) -> None:
    file = source(path, language, "\n".join(f"line {n}" for n in range(1, 90)) + "\n")
    assert TreeSitterChunker().chunk(file) == FixedSizeChunker().chunk(file)

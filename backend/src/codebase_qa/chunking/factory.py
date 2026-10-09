from codebase_qa.chunking.fixed import FixedSizeChunker
from codebase_qa.chunking.treesitter.chunker import TreeSitterChunker
from codebase_qa.interfaces import Chunker


def build_chunker(name: str) -> Chunker:
    if name == "fixed":
        return FixedSizeChunker()
    if name == "treesitter":
        return TreeSitterChunker()
    raise ValueError(f"unknown chunker: {name}")

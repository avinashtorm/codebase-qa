from dataclasses import dataclass, field


@dataclass
class Folder:
    folders: dict[str, "Folder"] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)

    def file_count(self) -> int:
        return len(self.files) + sum(child.file_count() for child in self.folders.values())


def build_folders(paths: list[str]) -> Folder:
    root = Folder()
    for path in sorted(paths):
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.folders.setdefault(part, Folder())
        node.files.append(parts[-1])
    return root


def render(node: Folder, depth: int, max_depth: int, max_files: int) -> list[str]:
    indent = "  " * depth
    lines: list[str] = []
    for name, child in sorted(node.folders.items()):
        lines.append(f"{indent}{name}/ ({child.file_count()} files)")
        if depth + 1 < max_depth:
            lines.extend(render(child, depth + 1, max_depth, max_files))
    shown = node.files[:max_files]
    lines.extend(f"{indent}{name}" for name in shown)
    if len(node.files) > len(shown):
        lines.append(f"{indent}... {len(node.files) - len(shown)} more files")
    return lines


def folder_tree(paths: list[str], max_depth: int = 4, max_files: int = 12, max_lines: int = 240) -> str:
    lines = render(build_folders(paths), 0, max_depth, max_files)
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], f"... {len(lines) - max_lines} more lines"]
    return "\n".join(lines)


def parent_folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else "."


def ancestors(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[:end]) for end in range(len(parts), 0, -1)]

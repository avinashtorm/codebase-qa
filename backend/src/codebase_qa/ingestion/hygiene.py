from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

DEFAULT_SKIP: tuple[str, ...] = (
    "*.lock",
    "*.map",
    "*.snap",
    "*/__snapshots__/*",
    "*/fixtures/*.json",
    "*/__fixtures__/*",
    "*/testdata/*",
    "*/test-data/*",
    "*/data/*.json",
    "*/datasets/*",
    "*/seed*/*.json",
    "*/assets/*.json",
    "*/public/*.json",
    "*/locales/*.json",
    "*/i18n/*.json",
)
DEFAULT_DOWNWEIGHT: tuple[str, ...] = (
    "*.gen.*",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.pb.go",
    "*.d.ts",
    "*/generated/*",
    "*/__generated__/*",
    "*/fixtures/*",
    "*/__mocks__/*",
    "*/migrations/*",
    "*/alembic/versions/*",
)
TEST_PATTERNS: tuple[str, ...] = (
    "*/tests/*",
    "*/test/*",
    "*/__tests__/*",
    "*/e2e/*",
    "*/test_*.py",
    "*_test.py",
    "*_test.go",
    "*.test.*",
    "*.spec.*",
    "*/conftest.py",
)
MANIFEST_JSON = frozenset(
    {
        "package.json",
        "composer.json",
        "tsconfig.json",
        "jsconfig.json",
        "app.json",
        "manifest.json",
        "openapi.json",
        "swagger.json",
        "vercel.json",
        "nest-cli.json",
        "angular.json",
        "deno.json",
    }
)


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    candidate = "/" + path
    return any(fnmatchcase(candidate, pattern) or fnmatchcase(candidate, "*/" + pattern) for pattern in patterns)


@dataclass(frozen=True)
class HygieneRules:
    skip: tuple[str, ...] = DEFAULT_SKIP
    downweight: tuple[str, ...] = DEFAULT_DOWNWEIGHT
    factor: float = 0.9
    max_json_kb: int = 50
    downweight_tests: bool = False
    enabled: bool = True

    def skips(self, path: str, size_bytes: int) -> bool:
        if not self.enabled:
            return False
        name = PurePosixPath(path).name.lower()
        if name.endswith(".json") and name not in MANIFEST_JSON and not name.startswith("tsconfig"):
            if size_bytes > self.max_json_kb * 1024:
                return True
        return matches_any(path, self.skip)

    def weight(self, path: str) -> float:
        if not self.enabled:
            return 1.0
        if matches_any(path, self.downweight):
            return self.factor
        if self.downweight_tests and matches_any(path, TEST_PATTERNS):
            return self.factor
        return 1.0


NO_HYGIENE = HygieneRules(enabled=False)

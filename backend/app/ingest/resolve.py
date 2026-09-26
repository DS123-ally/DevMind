"""Resolve a human reference such as `app/pricing.py` or `calculate_tax` onto graph ids."""

from __future__ import annotations


def resolve_targets(
    refs: list[str],
    files_by_path: dict[str, str],
    symbols_by_name: dict[str, list[tuple[str, str]]],
) -> list[str]:
    """symbols_by_name maps a simple name to (symbol id, file path) pairs."""
    ids: list[str] = []
    paths = [ref.replace("\\", "/").strip("`") for ref in refs if "/" in ref or ref.endswith(_CODE_SUFFIXES)]
    path_set = set(paths)
    for ref in refs:
        cleaned = ref.replace("\\", "/").strip().strip("`")
        if not cleaned:
            continue
        file_id = _match_file(cleaned, files_by_path)
        if file_id:
            ids.append(file_id)
            continue
        name = cleaned.split(":")[-1].split(".")[-1]
        candidates = symbols_by_name.get(name, [])
        in_affected = [item for item in candidates if item[1] in path_set or any(item[1].endswith(path) for path in path_set)]
        chosen = in_affected or (candidates if len(candidates) == 1 else [])
        if len(chosen) == 1:
            ids.append(chosen[0][0])
    seen: set[str] = set()
    ordered: list[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".md", ".json")


def _match_file(ref: str, files_by_path: dict[str, str]) -> str | None:
    if ref in files_by_path:
        return files_by_path[ref]
    matches = [file_id for path, file_id in files_by_path.items() if path.endswith("/" + ref) or path == ref]
    if len(matches) == 1:
        return matches[0]
    return None

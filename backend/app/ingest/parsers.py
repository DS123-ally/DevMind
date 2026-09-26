"""Source parsers for symbols, imports, and architecture decision records."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".md": "markdown",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".css": "css",
    ".html": "html",
    ".sql": "sql",
}

SYMBOL_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx"}


@dataclass
class ParsedFunction:
    name: str
    signature: str
    docstring: str | None
    line: int
    class_name: str | None
    calls: list[str] = field(default_factory=list)


@dataclass
class ParsedClass:
    name: str
    docstring: str | None
    line: int
    bases: list[str] = field(default_factory=list)


@dataclass
class ParsedModule:
    docstring: str | None
    imports: list[str]
    classes: list[ParsedClass]
    functions: list[ParsedFunction]


@dataclass
class ParsedAdr:
    title: str
    status: str
    decision: str
    date: str | None = None
    deciders: list[str] = field(default_factory=list)
    supersedes: str | None = None
    context: str | None = None
    consequences: str | None = None
    affects: list[str] = field(default_factory=list)


def language_for(path: str) -> str:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return LANGUAGE_BY_SUFFIX.get(suffix, "text")


def parse_source(path: str, source: str) -> ParsedModule:
    from app.ingest.treesitter import parse_with_tree_sitter

    parsed = parse_with_tree_sitter(path, source)
    if parsed is not None and (parsed.functions or parsed.classes or parsed.imports):
        return parsed
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if suffix == ".py":
        return parse_python(source)
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return parse_javascript(source)
    return parsed or ParsedModule(docstring=None, imports=[], classes=[], functions=[])


def parse_python(source: str) -> ParsedModule:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ParsedModule(docstring=None, imports=[], classes=[], functions=[])

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.append(node.module)

    classes: list[ParsedClass] = []
    functions: list[ParsedFunction] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_function_from_ast(node, class_name=None))
        elif isinstance(node, ast.ClassDef):
            classes.append(
                ParsedClass(
                    name=node.name,
                    docstring=_clean(ast.get_docstring(node)),
                    line=node.lineno,
                    bases=_base_names(node),
                )
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(_function_from_ast(item, class_name=node.name))

    return ParsedModule(
        docstring=_clean(ast.get_docstring(tree)),
        imports=_unique(imports),
        classes=classes,
        functions=functions,
    )


def parse_javascript(source: str) -> ParsedModule:
    imports = _unique(re.findall(r"""from\s+['"]([^'"]+)['"]""", source))
    classes: list[ParsedClass] = []
    functions: list[ParsedFunction] = []
    class_spans = list(
        re.finditer(r"(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_]\w*)", source)
    )
    for match in class_spans:
        name = match.group(1)
        line = source[: match.start()].count("\n") + 1
        body = _brace_block(source, match.end())
        classes.append(ParsedClass(name=name, docstring=None, line=line, bases=_js_bases(source, match.end())))
        functions.extend(_js_methods(name, body, line))

    for match in re.finditer(
        r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(([^)]*)\)",
        source,
    ):
        name = match.group(1)
        if _inside_spans(match.start(), class_spans, source):
            continue
        functions.append(
            ParsedFunction(
                name=name,
                signature=f"{name}({_compact_params(match.group(2))})",
                docstring=None,
                line=source[: match.start()].count("\n") + 1,
                class_name=None,
                calls=_calls_in_block(_brace_block(source, match.end())),
            )
        )

    for match in re.finditer(
        r"(?:export\s+)?(?:const|let)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\(([^)]*)\)|([A-Za-z_]\w*))\s*=>",
        source,
    ):
        name = match.group(1)
        params = match.group(2) if match.group(2) is not None else (match.group(3) or "")
        functions.append(
            ParsedFunction(
                name=name,
                signature=f"{name}({_compact_params(params)})",
                docstring=None,
                line=source[: match.start()].count("\n") + 1,
                class_name=None,
                calls=[],
            )
        )

    return ParsedModule(docstring=None, imports=imports, classes=classes, functions=functions)


_FIELD = re.compile(
    r"^(Status|Date|Deciders|Supersedes|Superseded-by|Affects)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)


def is_adr_path(path: str) -> bool:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    return (
        "/adr/" in f"/{lowered}"
        or "/decisions/" in f"/{lowered}"
        or name.startswith("adr-")
        or bool(re.match(r"\d{3,}-.+\.md$", name))
    )


def parse_adr(path: str, text: str) -> ParsedAdr | None:
    if not is_adr_path(path) or not path.endswith(".md"):
        return None
    title_match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    if not title_match:
        return None
    fields = {match.group(1).lower(): match.group(2).strip() for match in _FIELD.finditer(text)}
    sections = _sections(text)
    decision = sections.get("decision") or sections.get("rationale") or sections.get("context") or ""
    affects = _split_list(fields.get("affects", ""))
    deciders = _split_list(fields.get("deciders", ""))
    supersedes = fields.get("supersedes")
    return ParsedAdr(
        title=title_match.group(1).strip(),
        status=(fields.get("status") or "accepted").strip().lower(),
        decision=decision.strip(),
        date=(fields.get("date") or None),
        deciders=deciders,
        supersedes=supersedes.strip() if supersedes else None,
        context=sections.get("context"),
        consequences=sections.get("consequences"),
        affects=affects,
    )


def readme_summary(text: str) -> str | None:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("```"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if stripped.startswith("![") or stripped.startswith("[![") or stripped.startswith("|"):
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    for paragraph in paragraphs:
        if len(paragraph) > 40:
            return paragraph[:600]
    return paragraphs[0][:600] if paragraphs else None


def _function_from_ast(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None) -> ParsedFunction:
    args: list[str] = []
    for arg in list(node.args.args) + list(node.args.kwonlyargs):
        if arg.arg in {"self", "cls"}:
            continue
        rendered = arg.arg
        if arg.annotation is not None:
            rendered += f": {ast.unparse(arg.annotation)}"
        args.append(rendered)
    signature = f"{node.name}({', '.join(args)})"
    if node.returns is not None:
        signature += f" -> {ast.unparse(node.returns)}"
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return ParsedFunction(
        name=node.name,
        signature=prefix + signature,
        docstring=_clean(ast.get_docstring(node)),
        line=node.lineno,
        class_name=class_name,
        calls=_calls_in_function(node),
    )


def _calls_in_function(node: ast.AST) -> list[str]:
    names: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, nested: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, nested: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, nested: ast.ClassDef) -> None:
            return

        def visit_Call(self, call: ast.Call) -> None:
            name = _call_name(call.func)
            if name:
                names.append(name)
            self.generic_visit(call)

    visitor = Visitor()
    for child in ast.iter_child_nodes(node):
        visitor.visit(child)
    return _unique(names)


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _base_names(node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _js_bases(source: str, start: int) -> list[str]:
    window = source[start : start + 180]
    match = re.search(r"\b(?:extends|implements)\s+([A-Za-z_][\w.]*)", window)
    if not match:
        return []
    return [match.group(1).split(".")[-1]]


def _js_methods(class_name: str, body: str, class_line: int) -> list[ParsedFunction]:
    found: list[ParsedFunction] = []
    pattern = re.compile(
        r"^\s*(?:public|private|protected|async|static|readonly|get|set|\s)*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{",
        re.MULTILINE,
    )
    reserved = {"if", "for", "while", "switch", "catch", "function", "return", "class"}
    for match in pattern.finditer(body):
        name = match.group(1)
        if name in reserved:
            continue
        found.append(
            ParsedFunction(
                name=name,
                signature=f"{name}({_compact_params(match.group(2))})",
                docstring=None,
                line=class_line + body[: match.start()].count("\n"),
                class_name=class_name,
                calls=_calls_in_block(_brace_block(body, match.end())),
            )
        )
    return found


def _calls_in_block(body: str) -> list[str]:
    return _unique(re.findall(r"\b([A-Za-z_]\w*)\s*\(", body))


def _brace_block(source: str, start: int) -> str:
    index = source.find("{", start)
    if index < 0:
        return ""
    depth = 0
    for pos in range(index, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[index + 1 : pos]
    return source[index + 1 :]


def _inside_spans(offset: int, spans: list[re.Match[str]], source: str) -> bool:
    for span in spans:
        block = _brace_block(source, span.end())
        begin = source.find("{", span.end())
        if begin >= 0 and begin <= offset <= begin + len(block):
            return True
    return False


def _compact_params(params: str) -> str:
    return ", ".join(part.strip() for part in params.split(",") if part.strip())


def _sections(text: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip().lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        body = "\n".join(line for line in body.splitlines() if not _FIELD.match(line)).strip()
        if body:
            sections[title] = body
    return sections


def _split_list(value: str) -> list[str]:
    parts = re.split(r",| and ", value)
    return [part.strip().strip("`") for part in parts if part.strip()]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    return compact or None

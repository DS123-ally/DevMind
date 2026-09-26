"""Tree-sitter extraction of classes, functions, imports, and calls."""

from __future__ import annotations

from functools import lru_cache

from app.ingest.parsers import ParsedClass, ParsedFunction, ParsedModule, _unique

_LANG_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}


def parse_with_tree_sitter(path: str, source: str) -> ParsedModule | None:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    language = _LANG_BY_SUFFIX.get(suffix)
    if not language:
        return None
    parser = _parser(language)
    if parser is None:
        return None
    tree = parser.parse(source.encode("utf-8"))
    if language == "python":
        return _python_module(tree.root_node, source)
    return _js_module(tree.root_node, source)


def available() -> bool:
    return _parser("python") is not None


@lru_cache(maxsize=8)
def _parser(language: str):
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return None
    blob = _language_blob(language)
    if blob is None:
        return None
    lang = Language(blob)
    try:
        return Parser(lang)
    except TypeError:
        parser = Parser()
        parser.language = lang
        return parser


def _language_blob(language: str):
    try:
        if language == "python":
            import tree_sitter_python as mod

            return mod.language()
        if language == "javascript":
            import tree_sitter_javascript as mod

            return mod.language()
        if language in {"typescript", "tsx"}:
            import tree_sitter_typescript as mod

            return mod.language_tsx() if language == "tsx" else mod.language_typescript()
    except Exception:
        return None
    return None


def _python_module(root, source: str) -> ParsedModule:
    imports: list[str] = []
    classes: list[ParsedClass] = []
    functions: list[ParsedFunction] = []

    def walk(node, class_name: str | None) -> None:
        if node.type == "import_statement":
            for child in _named(node, "dotted_name", "aliased_import"):
                imports.append(_text(child, source).split(" ")[0])
        elif node.type == "import_from_statement":
            module = node.child_by_field_name("module_name")
            if module is not None:
                imports.append(_text(module, source))
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else ""
            superclasses = node.child_by_field_name("superclasses")
            bases = _python_bases(superclasses, source) if superclasses else []
            classes.append(
                ParsedClass(
                    name=name,
                    docstring=_python_docstring(node, source),
                    line=node.start_point[0] + 1,
                    bases=bases,
                )
            )
            body = node.child_by_field_name("body")
            if body is not None:
                for child in body.children:
                    walk(child, name)
            return
        elif node.type in {"function_definition", "async_function_definition"}:
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else ""
            params = node.child_by_field_name("parameters")
            returns = node.child_by_field_name("return_type")
            signature = _python_signature(name, params, returns, source, node.type.startswith("async"))
            body = node.child_by_field_name("body")
            functions.append(
                ParsedFunction(
                    name=name,
                    signature=signature,
                    docstring=_python_docstring(node, source),
                    line=node.start_point[0] + 1,
                    class_name=class_name,
                    calls=_calls(body, source) if body else [],
                )
            )
            return
        for child in node.children:
            walk(child, class_name)

    walk(root, None)
    return ParsedModule(docstring=_python_docstring(root, source), imports=_unique(imports), classes=classes, functions=functions)


def _python_bases(node, source: str) -> list[str]:
    names: list[str] = []
    for child in node.children:
        if child.type == "identifier":
            names.append(_text(child, source))
        elif child.type == "attribute":
            attr = child.child_by_field_name("attribute")
            names.append(_text(attr or child, source))
    return names


def _python_docstring(node, source: str) -> str | None:
    body = node.child_by_field_name("body") if node.type != "module" else node
    if body is None:
        return None
    for child in body.children:
        if child.type == "expression_statement":
            expr = child.child(0)
            if expr is not None and expr.type == "string":
                raw = _text(expr, source).strip()
                if raw.startswith(('"""', "'''", '"', "'")):
                    return " ".join(raw.strip("\"'").split()) or None
            break
        if child.is_named:
            break
    return None


def _python_signature(name: str, params, returns, source: str, async_def: bool) -> str:
    args: list[str] = []
    if params is not None:
        for child in params.children:
            if child.type not in {"identifier", "typed_parameter", "default_parameter", "typed_default_parameter"}:
                continue
            ident = child if child.type == "identifier" else child.child_by_field_name("name") or child.child(0)
            arg = _text(ident, source) if ident else ""
            if arg in {"self", "cls", ""}:
                continue
            type_node = child.child_by_field_name("type")
            if type_node is not None:
                arg += f": {_text(type_node, source)}"
            args.append(arg)
    signature = f"{name}({', '.join(args)})"
    if returns is not None:
        signature += f" -> {_text(returns, source)}"
    return f"async {signature}" if async_def else signature


def _js_module(root, source: str) -> ParsedModule:
    imports: list[str] = []
    classes: list[ParsedClass] = []
    functions: list[ParsedFunction] = []

    def walk(node, class_name: str | None) -> None:
        if node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            if source_node is not None:
                imports.append(_text(source_node, source).strip("'\""))
        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else ""
            heritage = [child for child in node.children if child.type in {"class_heritage", "extends_clause"}]
            bases = []
            for clause in heritage:
                ident = _first_identifier(clause)
                if ident:
                    bases.append(ident)
            classes.append(ParsedClass(name=name, docstring=None, line=node.start_point[0] + 1, bases=bases))
            body = node.child_by_field_name("body")
            if body is not None:
                for child in body.children:
                    walk(child, name)
            return
        elif node.type in {"function_declaration", "function", "method_definition", "generator_function_declaration"}:
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else ""
            if not name:
                return
            params = node.child_by_field_name("parameters")
            body = node.child_by_field_name("body")
            param_text = _text(params, source).strip("()") if params else ""
            functions.append(
                ParsedFunction(
                    name=name,
                    signature=f"{name}({_compact(param_text)})",
                    docstring=None,
                    line=node.start_point[0] + 1,
                    class_name=class_name,
                    calls=_calls(body, source) if body else [],
                )
            )
            return
        elif node.type == "lexical_declaration" and class_name is None:
            for child in node.children:
                if child.type != "variable_declarator":
                    continue
                name_node = child.child_by_field_name("name")
                value = child.child_by_field_name("value")
                if name_node is None or value is None or value.type not in {"arrow_function", "function"}:
                    continue
                name = _text(name_node, source)
                params = value.child_by_field_name("parameters")
                param_text = _text(params, source).strip("()") if params else ""
                functions.append(
                    ParsedFunction(
                        name=name,
                        signature=f"{name}({_compact(param_text)})",
                        docstring=None,
                        line=node.start_point[0] + 1,
                        class_name=None,
                        calls=[],
                    )
                )
            return
        for child in node.children:
            walk(child, class_name)

    walk(root, None)
    return ParsedModule(docstring=None, imports=_unique(imports), classes=classes, functions=functions)


def _calls(body, source: str) -> list[str]:
    names: list[str] = []

    def walk(node) -> None:
        if node.type in {"function_definition", "async_function_definition", "function_declaration", "method_definition", "arrow_function", "function"}:
            if node is not body:
                return
        if node.type == "call" or node.type == "call_expression":
            func = node.child_by_field_name("function")
            name = _call_name(func, source) if func is not None else None
            if name:
                names.append(name)
        for child in node.children:
            if child.type in {"function_definition", "async_function_definition", "function_declaration", "method_definition"}:
                continue
            walk(child)

    walk(body)
    return _unique(names)


def _call_name(node, source: str) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return _text(node, source)
    if node.type in {"attribute", "member_expression"}:
        attr = node.child_by_field_name("attribute") or node.child_by_field_name("property")
        if attr is not None:
            return _text(attr, source)
    return None


def _named(node, *types: str):
    for child in node.children:
        if child.type in types:
            yield child
        elif child.type == "aliased_import":
            inner = child.child_by_field_name("name")
            if inner is not None:
                yield inner


def _first_identifier(node) -> str | None:
    if node.type == "identifier":
        return node.text.decode("utf-8") if isinstance(node.text, bytes) else None
    for child in node.children:
        found = _first_identifier(child)
        if found:
            return found
    return None


def _text(node, source: str) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte]


def _compact(params: str) -> str:
    return ", ".join(part.strip() for part in params.split(",") if part.strip())

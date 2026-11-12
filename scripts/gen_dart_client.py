#!/usr/bin/env python3
"""Generate the Dart client of the engine API from auto_edit/openapi.yaml.

    python scripts/gen_dart_client.py          # writes packages/auto_edit_client/lib/src/generated/
    python scripts/gen_dart_client.py --check  # fails if the generated files are stale

Writes two files: `models.dart` (one class per object schema, inline objects
included, and one extension type per string enum) and `api.dart` (one method
per operationId). The hand-written transport (HTTP, token, SSE with
reconnection) lives next to them in `lib/src/`.

A purpose-built generator instead of openapi-generator: the spec is OpenAPI
3.1 (`type: [string, "null"]`), which the Dart generators don't handle well,
and this keeps the CI free of Java. If `dart` is on the PATH the output goes
through `dart format`; the CI check runs with it.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "auto_edit" / "openapi.yaml"
PACKAGE = ROOT / "packages" / "auto_edit_client"
OUT = PACKAGE / "lib" / "src" / "generated"

HEADER = """\
// GENERATED from auto_edit/openapi.yaml by scripts/gen_dart_client.py.
// Do not edit: change the spec and run the script again.
// ignore_for_file: type=lint
"""

RESERVED = {
    "abstract", "as", "assert", "async", "await", "break", "case", "catch", "class", "const",
    "continue", "covariant", "default", "deferred", "do", "dynamic", "else", "enum", "export",
    "extends", "extension", "external", "factory", "false", "final", "finally", "for", "Function",
    "get", "hide", "if", "implements", "import", "in", "interface", "is", "late", "library",
    "mixin", "new", "null", "on", "operator", "part", "required", "rethrow", "return", "set",
    "show", "static", "super", "switch", "sync", "this", "throw", "true", "try", "typedef", "var",
    "void", "while", "with", "yield", "hashCode", "runtimeType", "toString", "noSuchMethod",
    "toJson", "fromJson",
}

# Schema names that would shadow dart:core.
RENAMES = {"Error": "ApiError"}

BINARY_PREFIXES = ("image/", "video/", "audio/", "text/plain", "application/octet-stream")


def class_name(name: str) -> str:
    cls = pascal(name)
    return RENAMES.get(cls, cls)


def pascal(name: str) -> str:
    parts = re.split(r"[^0-9A-Za-z]+", name)
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return out if out and not out[0].isdigit() else "N" + out


def camel(name: str) -> str:
    p = pascal(name)
    ident = p[:1].lower() + p[1:]
    return ident + "_" if ident in RESERVED else ident


def dart_string(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'").replace("$", "\\$") + "'"


def doc(text: str | None, indent: str = "") -> str:
    if not text:
        return ""
    lines = [ln.rstrip() for ln in str(text).strip().splitlines()]
    return "".join(f"{indent}/// {ln}".rstrip() + "\n" for ln in lines)


# --- types -------------------------------------------------------------------


@dataclass
class DType:
    """A Dart type plus how to read it from / write it to decoded JSON."""

    name: str  # without the `?`
    read: str  # template with {v}: an Object? that is not null
    write: str  # template with {v}: a value of this (non-null) type
    nullable: bool = False

    def decl(self) -> str:
        return self.name + ("?" if self.nullable else "")

    def from_json(self, expr: str) -> str:
        if self.name == "Object":
            return expr
        if self.nullable:
            return f"{expr} == null ? null : {self.read.format(v=expr)}"
        return self.read.format(v=expr)

    def to_json(self, expr: str) -> str:
        return self.write.format(v=expr)


OBJECT = DType("Object", "{v}", "{v}", nullable=True)
JSON_MAP = DType("Map<String, Object?>", "({v} as Map).cast<String, Object?>()", "{v}")


@dataclass
class ClassDef:
    name: str
    description: str | None
    props: dict  # name -> schema
    required: set[str]


@dataclass
class EnumDef:
    name: str
    description: str | None
    values: list[str]


@dataclass
class Gen:
    spec: dict
    classes: dict[str, ClassDef] = field(default_factory=dict)
    enums: dict[str, EnumDef] = field(default_factory=dict)
    seen_inline: dict[int, str] = field(default_factory=dict)

    # -- refs
    def deref(self, ref: str) -> tuple[str, dict]:
        parts = ref.removeprefix("#/").split("/")
        node = self.spec
        for p in parts:
            node = node[p]
        return parts[-1], node

    def flatten(self, schema: dict) -> dict:
        """allOf of objects → one object (properties and required merged)."""
        if "allOf" not in schema:
            return schema
        props, required, desc = {}, set(), schema.get("description")
        for part in schema["allOf"]:
            if "$ref" in part:
                _, part = self.deref(part["$ref"])
            part = self.flatten(part)
            props.update(part.get("properties", {}))
            required |= set(part.get("required", []))
            desc = desc or part.get("description")
        return {"type": "object", "properties": props, "required": sorted(required), "description": desc}

    def declare_class(self, name: str, schema: dict) -> str:
        if name in self.classes or name in self.enums:
            raise SystemExit(f"gen_dart_client: two schemas generate the Dart class {name}")
        schema = self.flatten(schema)
        self.classes[name] = ClassDef(
            name, schema.get("description"), schema.get("properties", {}), set(schema.get("required", []))
        )
        return name

    # -- schema → DType
    def type_of(self, schema: dict | None, hint: str) -> DType:
        if not schema:
            return OBJECT
        if "$ref" in schema:
            name, target = self.deref(schema["$ref"])
            if self.is_object(target) or self.is_enum(target):
                cls = class_name(name)
                if cls not in self.classes and cls not in self.enums:
                    self.declare_schema(name, target)
                if cls in self.enums:
                    return DType(cls, f"{cls}({{v}} as String)", "{v}.value")
                return DType(cls, f"{cls}.fromJson(({{v}} as Map).cast<String, Object?>())", "{v}.toJson()")
            return self.type_of(target, pascal(name))
        if "allOf" in schema:
            return self.type_of(self.flatten(schema), hint)
        if "oneOf" in schema or "anyOf" in schema:
            return OBJECT
        types = schema.get("type")
        types = types if isinstance(types, list) else [types] if types else []
        nullable = "null" in types
        types = [t for t in types if t != "null"]
        if len(types) != 1:
            return OBJECT
        t = types[0]
        if t == "string":
            base = DType("String", "{v} as String", "{v}")
        elif t == "integer":
            base = DType("int", "({v} as num).toInt()", "{v}")
        elif t == "number":
            base = DType("double", "({v} as num).toDouble()", "{v}")
        elif t == "boolean":
            base = DType("bool", "{v} as bool", "{v}")
        elif t == "array":
            item = self.type_of(schema.get("items"), hint + "Item")
            base = DType(
                f"List<{item.decl()}>",
                f"({{v}} as List).map((e) => {item.from_json('e')}).toList()",
                "{v}" if item.to_json("e") == "e" else f"{{v}}.map((e) => {item.to_json('e')}).toList()",
            )
        elif t == "object":
            if schema.get("properties"):
                key = id(schema)
                if key not in self.seen_inline:
                    self.seen_inline[key] = self.declare_class(hint, schema)
                cls = self.seen_inline[key]
                base = DType(cls, f"{cls}.fromJson(({{v}} as Map).cast<String, Object?>())", "{v}.toJson()")
            elif isinstance(schema.get("additionalProperties"), dict) and schema["additionalProperties"]:
                val = self.type_of(schema["additionalProperties"], hint + "Value")
                base = DType(
                    f"Map<String, {val.decl()}>",
                    f"({{v}} as Map).map((k, e) => MapEntry(k as String, {val.from_json('e')}))",
                    "{v}" if val.to_json("e") == "e" else f"{{v}}.map((k, e) => MapEntry(k, {val.to_json('e')}))",
                )
            else:
                base = JSON_MAP
        else:
            return OBJECT
        if nullable:
            return DType(base.name, base.read, base.write, nullable=True)
        return base

    @staticmethod
    def is_object(schema: dict) -> bool:
        t = schema.get("type")
        return "allOf" in schema or (t == "object" and bool(schema.get("properties")))

    @staticmethod
    def is_enum(schema: dict) -> bool:
        return schema.get("type") == "string" and bool(schema.get("enum"))

    def declare_schema(self, name: str, schema: dict) -> None:
        cls = class_name(name)
        if self.is_enum(schema):
            self.enums[cls] = EnumDef(cls, schema.get("description"), [str(v) for v in schema["enum"]])
        elif self.is_object(schema):
            self.declare_class(cls, schema)


# --- models.dart ---------------------------------------------------------------


def render_class(gen: Gen, c: ClassDef) -> str:
    fields = []
    for prop, schema in c.props.items():
        t = gen.type_of(schema, c.name + pascal(prop))
        required = prop in c.required
        if not required:
            t = DType(t.name, t.read, t.write, nullable=True)
        fields.append((prop, camel(prop), t, required, (schema or {}).get("description")))

    out = [doc(c.description) + f"class {c.name} {{"]
    if fields:
        params = ", ".join(
            ("required " if req and not t.nullable else "") + f"this.{ident}" for _, ident, t, req, _ in fields
        )
        out.append(f"  const {c.name}({{{params}}});\n")
    else:
        out.append(f"  const {c.name}();\n")
    for _, ident, t, _, desc in fields:
        out.append(doc(desc, "  ") + f"  final {t.decl()} {ident};")
    out.append("")
    out.append(f"  factory {c.name}.fromJson(Map<String, Object?> json) => {c.name}(")
    for prop, ident, t, _, _ in fields:
        out.append(f"        {ident}: {t.from_json(f'json[{dart_string(prop)}]')},")
    out.append("      );\n")
    out.append("  Map<String, Object?> toJson() => {")
    for prop, ident, t, req, _ in fields:
        key = dart_string(prop)
        if req:
            value = t.to_json(ident) if not t.nullable or t.to_json("x") == "x" else (
                f"{ident} == null ? null : {t.to_json(ident + '!')}"
            )
            out.append(f"        {key}: {value},")
        elif t.name == "Object":
            out.append(f"        if ({ident} != null) {key}: {ident},")
        else:
            out.append(f"        if ({ident} != null) {key}: {t.to_json(ident + '!')},")
    out.append("      };")
    out.append("}\n")
    return "\n".join(out)


def render_enum(e: EnumDef) -> str:
    out = [
        doc(e.description)
        + "/// Values the engine sends today; an unknown one still parses (a newer engine).\n"
        + f"extension type const {e.name}(String value) {{"
    ]
    for v in e.values:
        out.append(f"  static const {camel(v)} = {e.name}({dart_string(v)});")
    out.append(f"  static const values = [{', '.join(camel(v) for v in e.values)}];")
    out.append("}\n")
    return "\n".join(out)


# --- api.dart ------------------------------------------------------------------


@dataclass
class Param:
    name: str
    ident: str
    dtype: DType
    required: bool
    where: str  # path | query
    description: str | None


def resolve_response(gen: Gen, resp: dict) -> tuple[str, dict]:
    name = ""
    if "$ref" in resp:
        name, resp = gen.deref(resp["$ref"])
    return name, resp


def success(gen: Gen, op: dict) -> tuple[str, str, dict | None, str]:
    """(status, content type, schema, reusable response name) of the 2xx answer."""
    for status, resp in op["responses"].items():
        if not str(status).startswith("2"):
            continue
        name, resp = resolve_response(gen, resp)
        content = resp.get("content") or {}
        if not content:
            continue
        ctype, media = next(iter(content.items()))
        return str(status), ctype, media.get("schema"), name
    return "200", "", None, ""


def render_api(gen: Gen) -> str:
    methods, comps = [], gen.spec["components"]
    for path, item in gen.spec["paths"].items():
        shared = item.get("parameters", [])
        for verb, op in item.items():
            if verb == "parameters":
                continue
            methods.append(render_method(gen, path, verb, op, shared, comps))
    return (
        HEADER
        + "\nimport 'dart:typed_data';\n\n"
        + "import '../transport.dart';\nimport 'models.dart';\n\n"
        + f"/// Every operation of the engine API (contract {gen.spec['info']['version']}).\n"
        + "class AutoEditApi {\n  AutoEditApi(this.transport);\n\n  final Transport transport;\n\n"
        + "  /// The `info.version` this client was generated from.\n"
        + f"  static const contractVersion = {dart_string(str(gen.spec['info']['version']))};\n\n"
        + "\n".join(methods)
        + "}\n"
    )


def as_text(p: Param) -> str:
    """A path or query parameter as the String that goes in the URL."""
    if p.dtype.name == "String":
        return p.ident
    if p.dtype.write == "{v}.value":  # an enum
        return f"{p.ident}.value"
    return f"'${p.ident}'"


def render_method(gen: Gen, path: str, verb: str, op: dict, shared: list, comps: dict) -> str:
    op_id = op["operationId"]
    params: list[Param] = []
    for raw in shared + op.get("parameters", []):
        if "$ref" in raw:
            _, raw = gen.deref(raw["$ref"])
        dt = gen.type_of(raw.get("schema", {"type": "string"}), pascal(op_id) + pascal(raw["name"]))
        params.append(Param(raw["name"], camel(raw["name"]), dt, raw.get("required", False) or raw["in"] == "path",
                            raw["in"], raw.get("description")))
    path_params = sorted((p for p in params if p.where == "path"), key=lambda p: path.index("{" + p.name + "}"))
    query = [p for p in params if p.where == "query"]

    body = op.get("requestBody")
    body_type = None
    if body:
        if "$ref" in body:
            _, body = gen.deref(body["$ref"])
        schema = (body.get("content", {}).get("application/json") or {}).get("schema")
        body_type = gen.type_of(schema, pascal(op_id) + "Request")
    body_required = bool(body and body.get("required"))

    status, ctype, schema, resp_name = success(gen, op)
    if ctype == "text/event-stream":
        kind, ret = "events", gen.type_of(schema, "JobEvent")
        sig_ret = f"Stream<{ret.name}>"
    elif ctype.startswith(BINARY_PREFIXES):
        kind, ret, sig_ret = "bytes", None, "Future<Uint8List>"
    elif ctype == "application/json":
        kind = "json"
        hint = pascal(resp_name) if resp_name and not schema.get("$ref") else pascal(op_id) + "Response"
        if resp_name and pascal(resp_name) in gen.classes:
            hint = pascal(resp_name) + "Response"
        ret = gen.type_of(schema, hint)
        sig_ret = f"Future<{ret.decl()}>"
    else:
        kind, ret, sig_ret = "none", None, "Future<void>"

    positional = [f"{p.dtype.decl()} {p.ident}" for p in path_params]
    named = []
    if body_type is not None:
        if body_required:
            positional.append(f"{body_type.decl()} body")
        else:
            named.append(f"{body_type.name}? body")
    for p in query:
        named.append((f"required {p.dtype.decl()} " if p.required else f"{p.dtype.name}? ") + p.ident)
    args = ", ".join(positional)
    if named:
        args += (", " if args else "") + "{" + ", ".join(named) + "}"

    url = path
    for p in path_params:
        url = url.replace("{" + p.name + "}", f"${{Uri.encodeComponent({as_text(p)})}}")
    url_lit = "'" + url + "'"
    q = ""
    if query:
        entries = ", ".join(
            (f"if ({p.ident} != null) " if not p.required else "") + f"{dart_string(p.name)}: {as_text(p)}"
            for p in query
        )
        q = f", query: {{{entries}}}"
    b = ""
    if body_type is not None:
        if body_required:
            b = f", body: {body_type.to_json('body')}"
        else:
            b = ", body: body" if body_type.to_json("x") == "x" else ", body: body?.toJson()"

    doc_lines = doc(op.get("summary"), "  ") + doc(op.get("description"), "  ")
    doc_lines += f"  ///\n  /// `{verb.upper()} {path}`\n"
    v = dart_string(verb.upper())
    if kind == "events":
        body_code = f"  {sig_ret} {camel(op_id)}({args}) =>\n      transport.events({url_lit}).map((e) => {ret.from_json('e')});\n"
    elif kind == "bytes":
        body_code = f"  {sig_ret} {camel(op_id)}({args}) =>\n      transport.bytes({v}, {url_lit}{q}{b});\n"
        if verb == "get":
            body_code += (
                f"\n  /// The URL of `{camel(op_id)}` (to hand a player or an image widget"
                " together with [Transport.headers]).\n"
                f"  Uri {camel(op_id)}Uri({args}) => transport.uri({url_lit}{q});\n"
            )
    elif kind == "json":
        body_code = (
            f"  {sig_ret} {camel(op_id)}({args}) async =>\n"
            f"      {ret.from_json(f'await transport.json({v}, {url_lit}{q}{b})')};\n"
        )
    else:
        body_code = f"  {sig_ret} {camel(op_id)}({args}) =>\n      transport.json({v}, {url_lit}{q}{b});\n"
    return doc_lines + body_code


def render_models(gen: Gen) -> str:
    parts = [HEADER, ""]
    parts += [render_enum(e) for e in gen.enums.values()]
    # Rendering a class can declare nested ones: loop until it settles.
    done: set[str] = set()
    while len(done) < len(gen.classes):
        for name in list(gen.classes):
            if name not in done:
                parts.append(render_class(gen, gen.classes[name]))
                done.add(name)
    return "\n".join(parts)


def generate(spec: dict) -> dict[str, str]:
    gen = Gen(spec)
    # Every enum is a component schema, so all of them exist before rendering.
    for name, schema in spec["components"]["schemas"].items():
        gen.declare_schema(name, schema)
    api = render_api(gen)
    return {"api.dart": api, "models.dart": render_models(gen)}


def dart_format(files: dict[str, str]) -> dict[str, str]:
    dart = shutil.which("dart")
    if not dart:
        print("gen_dart_client: dart não está no PATH, saída sem `dart format`", file=sys.stderr)
        return files
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in files.items():
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        subprocess.run([dart, "format", "--language-version=3.8", "-o", "write", tmp],
                       check=True, capture_output=True)
        return {name: (Path(tmp) / name).read_text(encoding="utf-8") for name in files}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the generated files are stale")
    args = ap.parse_args()
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    files = dart_format(generate(spec))
    stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != text]
    if args.check:
        if stale:
            print(f"gen_dart_client: desatualizado ({', '.join(stale)}). Rode scripts/gen_dart_client.py",
                  file=sys.stderr)
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
    print(f"gen_dart_client: {len(files)} arquivos em {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The Dart client generator (scripts/gen_dart_client.py) covers the whole contract.

The generated code itself is compiled and tested by the `dart-client` CI job
(dart analyze + dart test, with a real `auto-edit serve`); this only checks,
without Dart, that every operation and schema of the spec gets generated.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
yaml_spec = yaml.safe_load((ROOT / "auto_edit" / "openapi.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_dart_client", ROOT / "scripts" / "gen_dart_client.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look the module up
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def files(gen):
    return gen.generate(yaml_spec)


def operations():
    for item in yaml_spec["paths"].values():
        for verb, op in item.items():
            if verb != "parameters":
                yield op["operationId"]


def test_one_method_per_operation(gen, files):
    methods = set(re.findall(r"^  (?:Future<.+?>|Stream<\w+>) (\w+)\(", files["api.dart"], re.M))
    assert methods == {gen.camel(op) for op in operations()}


def test_every_component_schema_is_generated(gen, files):
    declared = set(re.findall(r"^(?:class|extension type const) (\w+)", files["models.dart"], re.M))
    for name, schema in yaml_spec["components"]["schemas"].items():
        if gen.Gen.is_object(schema) or gen.Gen.is_enum(schema):
            assert gen.class_name(name) in declared, name


def test_no_class_shadows_dart_core(files):
    declared = set(re.findall(r"^class (\w+)", files["models.dart"], re.M))
    assert not declared & {"Error", "Exception", "Object", "Type", "Function", "Iterable", "Map", "List"}


def test_contract_version_is_embedded(files):
    assert f"contractVersion = '{yaml_spec['info']['version']}'" in files["api.dart"]


def test_names(gen):
    assert gen.camel("video_id") == "videoId"
    assert gen.camel("default") == "default_"
    assert gen.pascal("thumbnail_b") == "ThumbnailB"
    assert gen.class_name("Error") == "ApiError"

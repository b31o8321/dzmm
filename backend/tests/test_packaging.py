from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "packaging" / "build_backend.py"
SPEC = spec_from_file_location("dzmm_build_backend", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
build_backend = module_from_spec(SPEC)
SPEC.loader.exec_module(build_backend)


def test_stage_migrations_excludes_bytecode_and_retired_cache_files(tmp_path) -> None:
    source = tmp_path / "source"
    (source / "versions" / "__pycache__").mkdir(parents=True)
    (source / "env.py").write_text("# active\n")
    (source / "versions" / "0011_active.py").write_text("# active\n")
    (source / "versions" / "__pycache__" / "0006_mobile_pairing.pyc").write_bytes(b"old")

    destination = tmp_path / "staged"
    build_backend.stage_migrations(source, destination)

    assert (destination / "env.py").is_file()
    assert (destination / "versions" / "0011_active.py").is_file()
    assert not (destination / "versions" / "__pycache__").exists()


def test_verify_clean_migrations_rejects_retired_artifacts(tmp_path) -> None:
    migrations = tmp_path / "_internal" / "migrations" / "versions"
    migrations.mkdir(parents=True)
    (migrations / "0006_mobile_pairing.pyc").write_bytes(b"old")

    with pytest.raises(RuntimeError, match="retired migration artifacts"):
        build_backend.verify_clean_migrations(tmp_path)


def test_release_workflow_installs_the_pyinstaller_package_extra() -> None:
    workflow = Path(__file__).parents[2] / ".github" / "workflows" / "release.yml"
    source = workflow.read_text(encoding="utf-8")
    assert 'pip install -e ".[dev,package]"' in source

"""Git transport must preserve the bytes authenticated by platform contracts."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile

import pytest
from strategy_manager import CandidateEvidence, StrategyRegistry, ValidationError
from strategy_runtime import implementation_sha256, load_strategy_deployment

from test_current_contracts import (
    current_frozen as current_frozen,
    inspection as inspection,
    completed as completed,
    managed_evaluation as managed_evaluation,
)


ROOT = Path(__file__).resolve().parents[2]


def _git(root, autocrlf, *arguments):
    return subprocess.check_output(
        [
            "git", "-c", f"core.autocrlf={autocrlf}",
            "-c", "core.safecrlf=false", "-c", "commit.gpgsign=false",
            "-c", f"core.hooksPath={root / '.disabled-hooks'}",
            "-c", "user.name=Artifact Test", "-c", "user.email=artifact@example.invalid",
            *arguments,
        ],
        cwd=root, stderr=subprocess.PIPE,
    )


@pytest.mark.parametrize("autocrlf", ["true", "false", "input"])
def test_git_roundtrip_preserves_evidence_and_current_release(tmp_path, current_frozen, autocrlf):
    context, version = current_frozen
    source = tmp_path / "git-source"
    source.mkdir()
    shutil.copy2(ROOT / ".gitattributes", source / ".gitattributes")
    shutil.copytree(context.strategy_root, source / "strategies")
    # Fresh paths cover future modules/strategies, not just current directory exceptions.
    samples = {
        "src/new_module/source.py": "# 中文\r\nvalue = 1\r\n".encode(),
        "packages/new_package/src/source.py": b"value = 1\n",
        "experiments/S999/20990101_S999_EX01/artifacts/evidence.json": '{\r\n  "说明": "事实"\r\n}\r\n'.encode(),
        "experiments/S999/20990101_S999_EX01/objects/mixed.txt": b"one\r\ntwo\nthree\r",
        "experiments/S999/20990101_S999_EX01/deliveries/COMPONENTS/1/report.md": "# 交付\r\n".encode(),
        "research/S999/mandates/1/report.md": "# 任务\n".encode(),
        "strategies/research_objects/evidence.json": b'{"value": 1}\r\n',
        "data/raw/binary.dat": b"\x00\xff\r\n\x80\n",
    }
    for name, content in samples.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    files = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*") if path.is_file()
    }
    source_files = ("src/new_module/source.py", "packages/new_package/src/source.py")
    source_identity = implementation_sha256(source_files, source_root=source)
    _git(source, autocrlf, "init")
    _git(source, autocrlf, "add", ".")
    _git(source, autocrlf, "commit", "-m", "synthetic authenticated artifacts")
    checkout = tmp_path / "git-checkout"
    _git(source, autocrlf, "clone", "--no-hardlinks", str(source), str(checkout))
    archive = ZipFile(BytesIO(_git(source, autocrlf, "archive", "--format=zip", "HEAD")))
    with archive:
        for name, content in files.items():
            assert _git(source, autocrlf, "cat-file", "blob", f"HEAD:{name}") == content, name
            assert (checkout / name).read_bytes() == content, name
            assert archive.read(name) == content, name
            CandidateEvidence(name, sha256(content).hexdigest()).resolve(checkout)
    assert implementation_sha256(source_files, source_root=checkout) == source_identity
    assert StrategyRegistry(checkout / "strategies").get_version("S900", "v1") == version
    deployed = load_strategy_deployment(checkout / "strategies", version.release_id)
    assert deployed.release_hash == version.release_hash
    # Changed bytes still fail authentication; Git stability never relaxes the hash contract.
    name = "strategies/research_objects/evidence.json"
    (checkout / name).write_bytes(samples[name] + b" ")
    with pytest.raises(ValidationError, match="hash"):
        CandidateEvidence(name, sha256(samples[name]).hexdigest()).resolve(checkout)


def test_effective_repository_attributes_disable_eol_conversion():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    attributes = subprocess.check_output(
        ["git", "check-attr", "--stdin", "-z", "text", "eol"], cwd=ROOT, input=paths,
    ).decode("utf-8").split("\0")[:-1]
    for path, attribute, value in zip(attributes[::3], attributes[1::3], attributes[2::3]):
        assert value == "unset", (path, attribute, value)


def test_archive_manifest_is_emitted_as_utf8_lf(tmp_path):
    from czsc_trader.experiment_archive import build_experiment_manifest

    archive = tmp_path / "20990101_EOL"
    archive.mkdir()
    for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
        (archive / name).write_bytes("合成档案\n".encode())
    build_experiment_manifest(archive, {"experiment_id": archive.name, "status": "COMPLETE"})
    content = (archive / "experiment_manifest.json").read_bytes()
    assert b"\n" in content and b"\r" not in content
    assert content.decode("utf-8").endswith("\n")

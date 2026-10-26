"""Run the public browser API contract against a deterministic DOM adapter."""

from pathlib import Path
import shutil
import subprocess


def test_shared_chart_runtime_contract() -> None:
    node = shutil.which("node")
    assert node is not None, "shared chart runtime tests require Node.js"
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("chart.test.cjs"))],
        check=False, capture_output=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

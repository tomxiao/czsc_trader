"""Run the public browser API contract against a deterministic DOM adapter."""

from pathlib import Path
import shutil
import subprocess

from strategy_chart import chart_body


def test_shared_shell_has_direct_date_navigation_without_event_date_selector() -> None:
    body = chart_body()
    assert 'id="forward-event-date"' not in body
    assert "事件日期" not in body
    assert 'id="forward-svg" role="img" tabindex="0"' in body
    assert "非交易日事件" in body


def test_shared_chart_runtime_contract() -> None:
    node = shutil.which("node")
    assert node is not None, "shared chart runtime tests require Node.js"
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("chart.test.cjs"))],
        check=False, capture_output=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

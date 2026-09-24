from __future__ import annotations

from pathlib import Path


FAILED = Path(__file__).resolve().parent.parent / "20260925_S008_EX86"
source = (FAILED / "run_experiment.py").read_text(encoding="utf-8")
if source.count('f"EX86 already has immutable output: {name}"') != 1:
    raise ValueError("EX86 runner identity differs")
source = source.replace('f"EX86 already has immutable output: {name}"', 'f"EX87 already has immutable output: {name}"')
source = source.replace("# S008 EX86", "# S008 EX87")
source = source.replace('"20260925_S008_EX86"', '"20260925_S008_EX87"')
exec(compile(source, str(FAILED / "run_experiment.py"), "exec"), globals())

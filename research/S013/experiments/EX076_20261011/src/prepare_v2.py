"""One-time source-only exact date-axis correction; never run real inputs."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
jobs = {
    "input_authentication.py": ("input_authentication_v2.py", {
        "if not decision_axis.equals(sessions):": "if not decision_axis.equals(full_axis[:-1]):"}),
    "driver.py": ("driver_v2.py", {
        "execution_freeze.json": "execution_freeze_v2.json",
        "from input_authentication import": "from input_authentication_v2 import",
        "import input_authentication as adapter": "import input_authentication_v2 as adapter"}),
    "execution_checks.py": ("execution_checks_v2.py", {
        "import driver\n": "import driver_v2 as driver\n",
        "import input_authentication as adapter": "import input_authentication_v2 as adapter",
        '"signal_date": sessions.as_unit("s")': '"signal_date": full_axis[:-1].as_unit("s")',
        "decisions.confirmation_opportunity.iloc[:-1]": "decisions.confirmation_opportunity.iloc[1:]",
        'HERE/"driver.py"': 'HERE/"driver_v2.py"',
        '("input_authentication.py", "reading.py", "driver.py", "execution_checks.py")':
            '("input_authentication_v2.py", "reading.py", "driver_v2.py", "execution_checks_v2.py")',
        "execution_pureproof.json": "execution_pureproof_v2.json"})}
for original, (new_name, changes) in jobs.items():
    source = (HERE/original).read_text()
    for before, after in changes.items():
        if source.count(before) != 1:
            raise ValueError("exact single original correction site required: " + before)
        source = source.replace(before, after)
    with (HERE/new_name).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(source)

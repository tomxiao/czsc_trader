"""Trace approved independent risks without changing collection or execution."""


def pytest_configure(config):
    config.addinivalue_line("markers", "risk_cases(*case_ids): approved independent-risk case references")

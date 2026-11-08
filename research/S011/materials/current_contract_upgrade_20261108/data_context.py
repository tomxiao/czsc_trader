"""Reuse the same retained ETF source conversion for S011 and S015."""
import importlib.util
from pathlib import Path


def build_data_context(candidate):
    root = Path(__file__).resolve().parents[4]
    path = root / 'research/S015/materials/current_contract_upgrade_20261108/data_context.py'
    spec = importlib.util.spec_from_file_location('s011_s015_retained_data', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_data_context(candidate)

"""Check exact copied frozen reference functions before native diagnostic execution."""
import ast
from common import ROOT, SRC, write, file_hash


def functions(path):
    return {node.name: ast.dump(node, include_attributes=False)
            for node in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(node, ast.FunctionDef)}


def main():
    old = functions(ROOT / 'research/S013/experiments/EX039_20261011/src/direction_diagnosis.py')
    new = functions(SRC / 'native_reference.py')
    assert len(new) == 8
    for name, value in new.items():
        assert old[name] == value, name
    text = (SRC / 'native_diagnosis.py').read_text(encoding='utf-8')
    assert '.evaluation.prepare(' not in text and '.evaluation.evaluate' not in text
    write(ROOT / '.tmp/ex042-diagnosis/source_checks.json', {
        'status': 'PURE_PASS', 'new_account_evaluations': 0,
        'frozen_reference_functions_AST_identical': sorted(new),
        'native_diagnosis_sha256': file_hash(SRC / 'native_diagnosis.py'),
        'limits': 'Reference-source identity and zero-evaluation orchestration only; full native accounts are audited after declaration.'})
    print({'source_checks': 'PURE_PASS', 'exact_frozen_functions': 8}, flush=True)


if __name__ == '__main__':
    main()

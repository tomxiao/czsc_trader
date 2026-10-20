"""Prepare/review/apply the explicitly authorized six same-version upgrades."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from strategy_manager import freeze_contracts as f
from czsc_trader.application import (
    FrozenRuntimeUpgradeRequest, PreparedFrozenRuntimeUpgrade, RepositoryContext,
    apply_frozen_runtime_upgrade, prepare_frozen_runtime_upgrade,
)
from czsc_trader.application.research_evidence import read_decision


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUTPUT = EX / 'others/inplace_upgrade'
REFERENCES = ('S001-v1', 'S001-v2', 'S002-v1', 'S003-v1', 'S007-v1', 'S011-v1')


def read(path):
    return json.loads(path.read_bytes())


def write_once(path, document):
    data = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('immutable upgrade receipt differs')
    else:
        with path.open('xb') as stream:
            stream.write(data)


def report_path(reference):
    directory = EX / 'others/formal_migration_inspection/inplace'
    if reference == 'S011-v1':
        directory = directory / 'attempt2'
    return directory / f'{reference}.json'


def prepared_record(reference):
    return OUTPUT / 'prepared' / f'{reference}.json'


def load_prepared(reference):
    record = read(prepared_record(reference))
    path = ROOT / record['plan_path']
    if sha256(path.read_bytes()).hexdigest() != record['plan_sha256']:
        raise ValueError('prepared exact plan bytes changed')
    return PreparedFrozenRuntimeUpgrade(path, record['plan_sha256'],
        f.FrozenVersionReference.from_dict(record['original']),
        f.FrozenVersionReference.from_dict(record['migrated']))


def prepare(reference):
    if prepared_record(reference).exists():
        value = load_prepared(reference)
        print(json.dumps({'reference': reference, 'status': 'EXISTING_PREPARED',
                          'plan_sha256': value.plan_sha256}), flush=True)
        return
    receipt = read(report_path(reference))
    if receipt['status'] != 'PASS':
        raise ValueError('same-version technical inspection must pass')
    context = RepositoryContext.discover(ROOT)
    selection = read_decision(ROOT, f.DecisionReference.from_dict(receipt['selection']))
    subject = selection.subject
    if type(subject) is not f.FrozenMigrationSelectionSubject:
        raise ValueError('explicit frozen migration selection required')
    prepared = prepare_frozen_runtime_upgrade(context, FrozenRuntimeUpgradeRequest(
        subject.original, subject.candidate,
        f.ResearchEvidenceRef.from_dict(receipt['inspection_reference']),
        selection.confirmation_source, ROOT / '.tmp/inplace-upgrade' / reference))
    write_once(prepared_record(reference), {
        'reference': reference, 'status': 'PREPARED_SAME_VERSION_UPGRADE',
        'plan_path': prepared.plan_path.relative_to(ROOT).as_posix(),
        'plan_sha256': prepared.plan_sha256, 'original': prepared.original.to_dict(),
        'migrated': prepared.migrated.to_dict(),
        'technical_inspection': receipt['inspection_reference'],
        'same_version': prepared.original.version == prepared.migrated.version,
        'production_writes': 0, 'paper_qualification_change_authorized': False,
    })
    print(json.dumps({'reference': reference, 'status': 'PREPARED',
        'plan_sha256': prepared.plan_sha256, 'new_release_hash': prepared.migrated.release_hash}), flush=True)


def apply(reference):
    prepared = load_prepared(reference)
    receipt = apply_frozen_runtime_upgrade(RepositoryContext.discover(ROOT), prepared)
    if receipt.status != 'COMMITTED':
        raise RuntimeError(f'upgrade did not commit: {receipt.status}')
    write_once(OUTPUT / 'applied' / f'{reference}.json', {
        'reference': reference, 'status': receipt.status,
        'original': receipt.original.to_dict(), 'migrated': receipt.migrated.to_dict(),
        'archive_path': receipt.archive_path.relative_to(ROOT).as_posix(),
        'receipt_path': receipt.receipt_path.relative_to(ROOT).as_posix(),
        'plan_sha256': prepared.plan_sha256, 'version_unchanged': True,
        'production_writes': 0, 'pte_accounts_changed': 0,
    })
    print(json.dumps({'reference': reference, 'status': receipt.status,
        'version': receipt.migrated.version, 'release_hash': receipt.migrated.release_hash}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('prepare', 'apply'), required=True)
    parser.add_argument('--references', choices=REFERENCES, nargs='+', default=list(REFERENCES))
    args = parser.parse_args()
    if args.phase == 'apply':
        # Review/prepare the complete selected batch before changing its first release.
        for reference in args.references:
            load_prepared(reference)
    for reference in args.references:
        (prepare if args.phase == 'prepare' else apply)(reference)


if __name__ == '__main__':
    main()

"""Fixed EX077 local-cache extraction; never returns out-of-window price rows.

No download, account execution, or formal research-space write is performed.
The parent cache is read-only. Whole pickle materialization is only used for
fixed date clipping before any dataframe statistic, feature, or output.
"""
from __future__ import annotations

import copy
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import pickle
import sqlite3

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
DATABASE = ROOT / '.tmp/lite-full-readiness-20261028/data/assets.sqlite3'
FIRST, LAST = date(2025, 11, 1), date(2026, 9, 30)
ZONE = 'America/New_York'
SPACE = 'f01da8ad-27b2-4839-a866-3639dc0329c6'
PREPARATION = 'c3cb4452-9ab8-4227-9c52-93b100a51c37'
MANIFEST = '50d7af9bb5fc5a6e70c530c657b45efd6c45784ee02d50a72a8e73d1de0b0a64'
ASSETS = {
    'BARS': 'c342aa4d4a046872d5d2e8511ef2efb1cbde51df82d4b79a8c8d46b456f8ce1e',
    'SESSIONS': '2eaa429badae9670fad096286245c90d39f30bc99d07c004bb49883ca26d26b7',
    'ACTIONS': '518b93233cd28c45961204f0a71f2b99287b85745c4807ffd2dd0af72337aa3d',
    'CONSTRAINTS': '4c90d85b4f57c85e70138aa2be7f6294a761eb055d65066a78f808d9bf1ba757',
}


def load_authorized_slice():
    """Return (frames, metadata, provenance); frames are exact fixed-window data.

    CONSTRAINTS remains the original source product. The caller applies the
    established EX032 V4 explicit_rules transformation before DFLS prepare.
    """
    frames, metadata, lineage = {}, {}, {}
    with sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True) as connection:
        space = connection.execute('SELECT space_id FROM space_metadata WHERE id=1').fetchone()
        manifest = connection.execute(
            'SELECT manifest_sha256 FROM preparations WHERE preparation_id=?', (PREPARATION,)).fetchone()
        if space != (SPACE,) or manifest != (MANIFEST,):
            raise ValueError('Fixed source preparation not found')
        for name, asset_id in ASSETS.items():
            payload_sha, payload = connection.execute(
                'SELECT payload_sha256,payload FROM assets WHERE asset_id=?', (asset_id,)).fetchone()
            full_frame, identity, _warnings = pickle.loads(payload)
            # IMPORTANT: no statistics/printing/feature calls before this slice.
            if name == 'ACTIONS':
                frame = full_frame.copy()
            else:
                stamp = pd.to_datetime(full_frame['BarStart' if name == 'BARS' else 'Date'], utc=True)
                local_dates = stamp.dt.tz_convert(ZONE).dt.date
                frame = full_frame.loc[local_dates.between(FIRST, LAST)].copy().reset_index(drop=True)
            del full_frame, payload
            meta = copy.deepcopy(identity['metadata'])
            meta['coverage_start'], meta['coverage_end'] = FIRST.isoformat(), LAST.isoformat()
            meta['sessions'] = [s for s in meta['sessions']
                                if FIRST.isoformat() <= s['session_date'] <= LAST.isoformat()]
            if name == 'ACTIONS':
                # The inherited NONE marker is a declaration, not an economic event.
                if len(frame) != 1 or frame.Kind.iloc[0] != 'NONE' or not meta.get('no_actions_verified'):
                    raise ValueError('Cached no-action declaration differs from fixed assumptions')
                stamp = pd.Timestamp(meta['sessions'][0]['segments'][0]['start'])
                frame.loc[:, 'Date'], frame.loc[:, 'AvailableDate'] = stamp, stamp
                meta['none_marker_basis'] = 'Inherited cached NONE declaration; canonical first requested session; no new historical verification'
            for key in ('research_bar_policy', 'download_receipts', 'download_complete'):
                meta.pop(key, None)
            evidence = 'Exact fixed-window local Futu cache slice; parent=' + asset_id + '; inherited gap/no-event limitations retained; zero downloads'
            meta.update(observation_contract='EXPLICIT_SOURCE_OBSERVATIONS_V1',
                        coverage_evidence=evidence, coverage_evidence_sha256=sha256(evidence.encode()).hexdigest(),
                        parent_asset_id=asset_id, parent_content_sha256=identity['content_sha256'],
                        cached_subset_only=True)
            frames[name], metadata[name] = frame, meta
            lineage[name] = {'asset_id': asset_id, 'payload_sha256': payload_sha,
                             'content_sha256': identity['content_sha256']}
    return frames, metadata, {'space_id': SPACE, 'preparation_id': PREPARATION,
                              'manifest_sha256': MANIFEST, 'assets': lineage,
                              'first': FIRST.isoformat(), 'last': LAST.isoformat(), 'downloads': 0}


if __name__ == '__main__':
    frames, metadata, provenance = load_authorized_slice()
    # Only authorized-window structural/quality facts; no price statistics.
    summary = {'window': [FIRST.isoformat(), LAST.isoformat()], 'downloads': 0, 'products': {}}
    for name, frame in frames.items():
        dates = pd.to_datetime(frame['BarStart' if name == 'BARS' else 'Date'], utc=True).dt.tz_convert(ZONE)
        entry = {'rows': len(frame), 'first': dates.min().isoformat(), 'last': dates.max().isoformat(),
                 'columns': list(frame.columns), 'metadata_keys': sorted(metadata[name])}
        if name == 'BARS':
            entry['statuses'] = frame.BarStatus.value_counts().to_dict()
            entry['blocked'] = int(frame.ExecutionBlocked.sum())
        summary['products'][name] = entry
    print(json.dumps(summary, ensure_ascii=False, default=str))

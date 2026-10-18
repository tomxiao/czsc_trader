"""Supplement immutable EX030 calculation audit with public input/evidence bindings."""
from hashlib import sha256
import json
from pathlib import Path

import requests
from czsc_trader.research_tools import EvidenceRef

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    dest=EX/'others/input_binding_review.json'
    if dest.exists():
        raise RuntimeError('Preserve existing input binding review')
    attempts=[]
    def block(*args,**kwargs):
        attempts.append(1)
        raise RuntimeError('No upstream access during binding audit')
    requests.sessions.Session.request=block
    checks=0
    manifest={}
    def bind(path,expected=None):
        nonlocal checks
        value=sha256(path.read_bytes()).hexdigest()
        if expected is not None:
            assert value==expected,(path,value,expected)
        relative=path.relative_to(ROOT).as_posix()
        assert relative not in manifest or manifest[relative]==value
        manifest[relative]=value
        checks+=1
        return value

    design_path=EX/'protocols/published_design.json'
    design=read(design_path)
    assert design['status']=='LOCKED_BEFORE_NEW_LABELS'
    checks+=1
    resolved=[]
    for row in design['files']:
        source=ROOT/row['path']
        digest=bind(source,row['sha256'])
        evidence=EvidenceRef.from_dict(row['evidence'])
        target=evidence.resolve(ROOT)
        assert evidence.sha256==digest==sha256(target.read_bytes()).hexdigest()
        assert source.read_bytes()==target.read_bytes()
        assert evidence.experiment.strategy_id=='S014'
        checks+=3
        resolved.append(dict(source=row['path'],sha256=digest,evidence=row['evidence'],resolved_path=target.relative_to(ROOT).as_posix()))
    bind(design_path)
    analysis_path=EX/'others/analysis.json'
    analysis=read(analysis_path)
    assert analysis['status']=='COMPLETE'
    checks+=1
    for relative,digest in analysis['source_sha256'].items():
        bind(ROOT/relative,digest)
    for name,digest in analysis['output_sha256'].items():
        bind(EX/f'others/{name}.csv',digest)
    pinned={
        'space_id':'9b7260bb-f12c-4eab-bc37-884d0cc58c91',
        'preparation_id':'dfb12e42-f327-4e1b-bf25-d15201b4e69b',
        'manifest_sha256':'b68cf906d81e19a16b131fe63ca1f4f901f9baa202bae75110481b5f209d8f57',
    }
    old_path=EX.parent/'EX023_20261018/others/loss_state_diagnostics.json'
    old=read(old_path)
    assert analysis['prepared_reference']==old['prepared_reference']==pinned
    checks+=2
    originals=[r for r in old['episodes'] if r['window']=='ALL' and r['entry_below_previous_broken_floor'] is True]
    bridged=[r['original'] for r in analysis['counterexample_bridge']]
    assert len(originals)==len(bridged)==69
    assert len({r['entry_date'] for r in originals})==69
    checks+=2
    for source,preserved in zip(originals,bridged):
        assert source==preserved,(source['entry_date'],preserved['entry_date'])
        checks+=1
    precheck=read(EX/'others/precheck.json')
    assert precheck['status']=='PASS' and precheck['checks']==17 and precheck['new_accounts']==0
    checks+=1
    audit_path=EX/'others/independent_audit.json'
    audit=read(audit_path)
    assert audit['status']=='PASS' and audit['checks']==314177
    checks+=1
    for row in audit['manifest']:
        bind(ROOT/row['path'],row['sha256'])
    for path in (Path(__file__),analysis_path,audit_path,old_path):
        bind(path)
    assert not attempts
    output=dict(status='PASS',checks=checks,new_accounts=0,new_upstream_calls=0,
        locked_public_evidence=resolved,prepared_reference=pinned,
        exact_old_counterexample_rows=69,independent_calculation_audit_sha256=sha256(audit_path.read_bytes()).hexdigest(),
        manifest=[dict(path=path,sha256=digest) for path,digest in sorted(manifest.items())],
        scope='Public lock source bytes and EvidenceRef.resolve content; all calculation source/output hashes; exact69 original bridge rows; pinned input identity; immutable prior independent audit. No new calculations or account replay.')
    dest.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='PASS',checks=checks,manifest_files=len(manifest),sha256=sha256(dest.read_bytes()).hexdigest())))


if __name__=='__main__':
    main()

"""Technical check revision: nullable empty-prefix dtype is not economic state."""
from run import *

def check():
    sources, _ = authenticate()
    runtime = module(SOURCE / FILES[0], 'ex050_runtime_check')
    feature_ref = EvidenceRef.from_dict(sources['training_input:others/model_features.csv'])
    x = pd.read_csv(feature_ref.resolve(ROOT)).set_index('date')[list(runtime.COLUMNS)]
    x.index = pd.DatetimeIndex(x.index)
    x['feature_ready'] = True
    x = pd.concat([pd.DataFrame([{**{c:0. for c in runtime.COLUMNS}, 'feature_ready':False}],
                                index=pd.DatetimeIndex(['2024-12-31'])), x])
    outputs = {mode: runtime.intentions(x, params(mode)) for mode in MODES}
    old = module(OLD / 'src/strategy_runtime/strategies/price_information.py', 'ex050_old_runtime')
    historical = old.intentions(x, {'family':'A','mode':'path','hold':3,'exposure':1.,'schedule':params('fixed100')['schedule']})
    for mode, output in outputs.items():
        definition = runtime.CycleRiskAllocation(ParameterSet(params(mode))).definition
        assert definition.decision.output_kind == 'CYCLE_TARGET'
        assert dict(definition.execution.settings['capital']) == {'fee_rate':.001, 'mode':'signal_cash_fraction', 'target_scope':'entry_cycle'}
        if mode != 'risk_reject':
            pd.testing.assert_series_equal(output.target_position, historical.target_position)
        fraction = output.entry_allocation_fraction
        assert fraction[output.target_position.eq(0)].isna().all()
        assert fraction[output.target_position.eq(1)].isin([.5,.75,1.]).all()
        for stop in (1,35,100,200,435):
            pp = params(mode)
            pp['schedule'] = [r for r in pp['schedule'] if r['date'] <= x.index[stop-1].date().isoformat()]
            prefix = runtime.intentions(x.iloc[:stop], pp)
            prefix['entry_allocation_fraction'] = prefix.entry_allocation_fraction.astype(float)
            pd.testing.assert_frame_equal(prefix, output.iloc[:stop], check_dtype=False)
        output.to_csv(HERE / f'others/signals_{mode}.csv', index_label='signal_date')
    # Every held intention keeps the allocation selected at its own start.
    for mode, output in outputs.items():
        opening = output.intent_age.eq(1).cumsum()
        for _, group in output[output.target_position.eq(1)].groupby(opening):
            assert group.entry_allocation_fraction.nunique() == 1
            if mode == 'risk_half':
                assert group.entry_allocation_fraction.iloc[0] == (1. if group.risk_allowed.iloc[0] else .5)
    save(HERE / 'others/runtime_checks.json', {
        'status':'PASS','source_sha256':sha256((SOURCE/FILES[0]).read_bytes()).hexdigest(),
        'authenticated_sources':sources,'model_releases':len(params('fixed100')['schedule']),
        'new_model_fits':0,'feature_rows':434,'checks':['five_CYCLE_TARGET_signal_cash_fraction_contracts',
            'four_path_arms_identical_old_intent_clock','25_physically_truncated_model_and_feature_prefixes',
            'flat_fraction_null','positive_fraction_bounds','within_intention_fraction_locked'],
        'training_causality':'Authenticated prior audit + all model known dates strictly before releases; unchanged40 A-role models. No new fitted coefficients.',
        'limits':'Runtime feature fields are verified against actual bound inputs in the post-account audit; prefix equality does not establish predictive usefulness.'})
    print('P2_RUNTIME_CHECK_PASS', flush=True)


if __name__ == "__main__":
    check()

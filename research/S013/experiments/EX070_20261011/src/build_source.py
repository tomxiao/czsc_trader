"""Create finite source-only prototype. No public/account reads on import."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent
old=ROOT/'research/S013/experiments/EX058_20261011/src/strategy_runtime/strategies'
out=WORK/'strategy_runtime/strategies'
out.mkdir(parents=True,exist_ok=True)
for path in old.glob('*.py'):
    target=out/path.name
    if target.exists():
        assert target.read_bytes()==path.read_bytes()
    else:
        target.write_bytes(path.read_bytes())
source=(old/'boundary_bear_recovery_range.py').read_text(encoding='utf-8')
source=source.replace('Original BELOW bear BODY ACF recovery plus raw-bull boundary BODY entry guard.',
    'Fixed original C8880 with causal four-session alternative buy confirmation.')
source=source.replace('class BoundaryBearRecoveryRange(', 'class ShortAlternativeRange(')
source=source.replace('"RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"',
    '"RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY_SHORT_ALT"')
source=source.replace('        super().__init__(\n',
    '        lookback = p.get("short_confirmation_lookback4")\n'
    '        if type(lookback) is not int or not 1 <= lookback <= 20:\n'
    '            raise ValueError("short confirmation lookback integer1..20 required")\n'
    '        super().__init__(\n',1)
source=source.replace('if key != "mechanism"', 'if key not in ("mechanism", "short_confirmation_lookback4")',1)
source=source.replace('p["regime_window"] + 2)', 'p["regime_window"] + 2, 21, lookback + 1)',1)
source=source.replace('        direction = (signal_close > signal_open).to_numpy()',
    '        short_value, short_pass, short_reason = short_confirmation(close, p["short_confirmation_lookback4"])\n'
    '        short_value = short_value.reindex(sessions)\n'
    '        short_pass = short_pass.reindex(sessions)\n'
    '        short_reason = short_reason.reindex(sessions)\n'
    '        direction = (signal_close > signal_open).to_numpy()')
source=source.replace('        recovery_flags, eligibility_flags = [], []',
    '        recovery_flags, eligibility_flags = [], []\n'
    '        alternative_opportunities, alternative_entries, entry_origins = [], [], []')
source=source.replace('            contexts.append(last_exit_reason or "initial")',
    '            contexts.append(last_exit_reason or "initial")\n'
    '            alternative = bool(short_pass.iloc[i])\n'
    '            alt_only = opportunity and not passed and alternative\n'
    '            alternative_opportunities.append(alt_only)\n'
    '            entered_by_alt = False\n'
    '            entry_origin = "NONE"')
source=source.replace('                elif passed:', '                elif passed or alternative:')
source=source.replace('                    reason = "entry"',
    '                    reason = "entry"\n'
    '                    entered_by_alt = not passed\n'
    '                    entry_origin = "ORIGINAL_CONFIRMATION" if passed else "SHORT_ALTERNATIVE"')
source=source.replace('            reasons.append(reason)',
    '            reasons.append(reason)\n'
    '            alternative_entries.append(entered_by_alt)\n'
    '            entry_origins.append(entry_origin)')
source=source.replace('            entry_eligible=eligibility_flags,',
    '            entry_eligible=eligibility_flags,\n'
    '            original_pass=passes,\n'
    '            short_alt_pass=short_pass,\n'
    '            short_stretch4=short_value,\n'
    '            short_stretch_reason=short_reason,\n'
    '            alt_only_opportunity=alternative_opportunities,\n'
    '            alt_only_entry=alternative_entries,\n'
    '            entry_confirmation_origin=entry_origins,')
insert='''
def short_confirmation(close, lookback):
    """No epsilon: unavailable/zero volatility cannot offer an alternative."""
    if type(lookback) is not int or not 1 <= lookback <= 20:
        raise ValueError("short confirmation integer lookback1..20 required")
    volatility = close.pct_change(fill_method=None).rolling(20,min_periods=20).std(ddof=1)
    prior = close.shift(lookback)
    defined = prior.notna() & volatility.notna() & volatility.gt(0)
    value = pd.Series(np.nan,index=close.index,dtype=float)
    value.loc[defined] = (np.log(close.loc[defined])-np.log(prior.loc[defined])) / (volatility.loc[defined]*np.sqrt(lookback))
    passed = defined & value.le(0)
    reason = pd.Series("COMPLETE",index=close.index,dtype=object)
    reason.loc[volatility.eq(0)]="ZERO_VOLATILITY"
    reason.loc[prior.isna() | volatility.isna()]="INCOMPLETE_HISTORY"
    return value,passed.astype(bool),reason

'''
source=source.replace('\n\nclass ShortAlternativeRange', '\n\n'+insert+'class ShortAlternativeRange',1)
target=out/'short_alternative_range.py'
if target.exists():
    assert target.read_text(encoding='utf-8')==source
else:
    target.write_text(source,encoding='utf-8',newline='\n')
print({'source_only':'READY','files':len(list(out.glob('*.py'))),'accounts':0})

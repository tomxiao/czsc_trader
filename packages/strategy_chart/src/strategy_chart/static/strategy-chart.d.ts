type SignalAvailability = 'AVAILABLE' | 'INACTIVE' | 'UNAVAILABLE';
type NumericFormat = 'NUMBER' | 'PERCENT' | 'INTEGER';
interface SignalGuide { key: string; label: string; value: number }
interface SignalGroup {
  key: string; label: string; unit: string; basis: string;
  format: NumericFormat; precision: number; description: string;
}
interface SignalStateOption { key: string; label: string }
interface SignalPanel {
  groups: SignalGroup[];
  series: Array<{
    key: string; label: string; group: string; render: 'LINE' | 'STEP' | 'BAR';
    description: string; value: number | null; status: SignalAvailability;
    reason: string | null; segment_id: string | null; guides: SignalGuide[];
  }>;
  states: Array<{
    key: string; label: string; description: string; options: SignalStateOption[];
    value: string | null; status: SignalAvailability; reason: string | null;
  }>;
  /** Absent only on explicitly supported legacy observations. */
  explanation?: {
    state_key: string; case_key: string; judgment: string;
    basis: Array<{key: string; text: string}>;
    next_watch: string; explanation: string;
  };
}
interface ReadyObservationValues {
  status: 'READY';
  series: Array<{key: string; label: string; value: number; guides: SignalGuide[]}>;
  facts: Array<{key: string; label: string; value: number | boolean | string; format: NumericFormat | 'BOOLEAN' | 'TEXT'}>;
}
/** Legacy PTE values, complete SRT observations, and authenticated PTE panel projections. */
type ChartObservation = (
  ReadyObservationValues & (
    {signal_panel?: never; definition_sha256?: string; strategy?: {release_hash: string}}
    | ({signal_panel: SignalPanel; definition_sha256: string} & (
      {release_hash: string; strategy?: never}
      | {strategy: {release_hash: string}; release_hash?: never}
    ))
  )
) | {status: 'UNAVAILABLE'; message: string};
interface StrategyChartContext {
  mode: 'BACKTEST' | 'PAPER';
  strategy: {
    symbol: string; release_id?: string; reference_id?: string;
    name?: string; account_id?: string;
  };
  window: {start?: string; end?: string; selection_data_cutoff?: string; observation_start?: string};
  market_data: {
    as_of: string;
    bars: Array<{date: string; open: number; high: number; low: number; close: number}>;
  };
  observations: Array<{
    decision_id: string; signal_date: string; generated_at?: string;
    observation: ChartObservation;
  }>;
  execution: {
    decisions: Array<{
      decision_id: string; generated_at: string; signal_date: string; valid_session: string;
      action: string; target_quantity: number; status: string;
      state_reason?: string; state_changed_at?: string;
    }>;
    fills: Array<{
      fill_id: string; occurred_at: string; session?: string; time_precision?: 'SESSION' | 'TIMESTAMP';
      side: 'BUY' | 'SELL'; quantity: number; price: number; fee: number | null;
    }>;
    snapshots: Array<{session: string; quantity: number}>;
  };
}
declare function mountStrategyChart(container: HTMLElement, context: StrategyChartContext): {destroy(): void};

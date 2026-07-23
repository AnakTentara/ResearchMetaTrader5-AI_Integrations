"""
param_sweep.py

Coba beberapa kombinasi MeanReversionParams sekaligus di atas data yang
sudah di-cache, cetak tabel perbandingan. Alat eksplorasi cepat untuk
in-sample -- BUKAN pengganti disiplin out-of-sample di run_research.py.
Kalau ada kandidat yang terlihat jelas lebih baik di sini, itu baru
layak diuji lebih serius lewat run_research.py.
"""

from pathlib import Path

import pandas as pd

from backtest_engine import TransactionCost, run_backtest
from metrics import compute_metrics
from signals.mean_reversion import MeanReversionParams, compute_entry_signals, compute_zscore


def _load_data() -> pd.DataFrame:
    cache_file = Path(__file__).parent / "data" / "EURUSD_H1.csv"
    if not cache_file.exists():
        raise FileNotFoundError(f"{cache_file} belum ada. Jalankan fetch_historical.py dulu.")
    df = pd.read_csv(cache_file)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def _run_one(raw_df: pd.DataFrame, params: MeanReversionParams, cost: TransactionCost):
    df = compute_zscore(raw_df, lookback=params.lookback)
    df["entry"] = compute_entry_signals(df, params)
    trades = run_backtest(df, params, cost)
    return compute_metrics(trades) if len(trades) > 0 else None


if __name__ == "__main__":
    raw_df = _load_data()
    cost = TransactionCost(spread_pips=0.1, commission_per_round_trip=0.0, slippage_pips=0.2)

    # Baseline (hasil kemarin) + 5 varian: stop lebih ketat, lookback
    # lebih panjang (mean/std lebih stabil), entry lebih selektif.
    kandidat = [
        MeanReversionParams(lookback=20, entry_z=2.0, exit_z=0.5, stop_z=3.5, max_hold_bars=48),
        MeanReversionParams(lookback=20, entry_z=2.0, exit_z=0.5, stop_z=2.5, max_hold_bars=48),
        MeanReversionParams(lookback=20, entry_z=2.0, exit_z=0.5, stop_z=3.0, max_hold_bars=48),
        MeanReversionParams(lookback=50, entry_z=2.0, exit_z=0.5, stop_z=3.5, max_hold_bars=48),
        MeanReversionParams(lookback=50, entry_z=2.0, exit_z=0.5, stop_z=2.5, max_hold_bars=48),
        MeanReversionParams(lookback=20, entry_z=2.5, exit_z=0.5, stop_z=3.5, max_hold_bars=48),
    ]

    rows = []
    for p in kandidat:
        m = _run_one(raw_df, p, cost)
        rows.append(
            {
                "lookback": p.lookback,
                "entry_z": p.entry_z,
                "stop_z": p.stop_z,
                "trades": m.total_trades if m else 0,
                "win_rate": f"{m.win_rate:.1%}" if m else "-",
                "profit_factor": f"{m.profit_factor:.2f}" if m else "-",
                "max_dd_pips": f"{m.max_drawdown_pips:.0f}" if m else "-",
                "sharpe": f"{m.sharpe_ratio:.2f}" if m else "-",
            }
        )

    print(pd.DataFrame(rows).to_string(index=False))
    print(
        "\nCatatan: ini in-sample, seluruh data sekaligus -- bukan bukti "
        "final. Baru sinyal awal kombinasi mana yang layak diuji lebih "
        "jauh."
    )

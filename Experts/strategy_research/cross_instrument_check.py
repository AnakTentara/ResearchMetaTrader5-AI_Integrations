"""
cross_instrument_check.py

Validasi silang-instrumen: jalankan strategi yang SAMA PERSIS (parameter
beku dari run_research.py) di beberapa pasangan mata uang major lain,
pakai seluruh riwayat historisnya.

Ini BUKAN pengganti out-of-sample temporal yang sudah dilakukan
run_research.py -- ini jenis bukti independen yang berbeda: kalau
sinyal yang sama menunjukkan pola serupa di beberapa instrumen berbeda,
itu bukti kuat sinyalnya menangkap sesuatu yang riil, bukan kebetulan
yang cuma cocok dengan riwayat harga EURUSD secara spesifik. Kalau
cuma EURUSD yang terlihat bagus dan yang lain tidak, itu justru
petunjuk sebaliknya.

Parameter TIDAK diubah sama sekali dari run_research.py, dan TIDAK
disetel per-instrumen -- ini murni menguji generalisasi, bukan
kesempatan tuning ulang lewat pintu belakang.

Butuh terminal MT5 terbuka & login -- simbol-simbol ini belum ada di
cache.
"""

import pandas as pd

from backtest_engine import TransactionCost, run_backtest
from fetch_historical import fetch_historical
from metrics import compute_metrics
from signals.mean_reversion import MeanReversionParams, compute_entry_signals, compute_zscore
from signals.trend_filter import apply_trend_filter, compute_trend_direction

# Sama persis dengan run_research.py -- lihat docstring di atas soal
# kenapa ini tidak boleh disetel ulang.
PARAMS = MeanReversionParams(lookback=20, entry_z=2.0, exit_z=0.5, stop_z=3.0, max_hold_bars=48)
TREND_LONG_WINDOW = 200

# Pasangan JPY dikutip 2 desimal, bukan 4 -- pip_size beda, kalau tidak
# disesuaikan, biaya transaksi untuk USDJPY akan under-estimasi 100x.
PIP_SIZE_BY_SYMBOL = {"USDJPY": 0.01}
DEFAULT_PIP_SIZE = 0.0001

# Dipilih untuk sebaran korelasi -- GBPUSD relatif berkorelasi dengan
# EURUSD, USDJPY & AUDUSD relatif tidak.
SYMBOLS = ["GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]


def check_symbol(symbol: str):
    raw_df = fetch_historical(symbol=symbol, timeframe_name="H1", tahun_terakhir=2.0)

    df = compute_zscore(raw_df, lookback=PARAMS.lookback)
    raw_entry = compute_entry_signals(df, PARAMS)
    trend = compute_trend_direction(df, long_window=TREND_LONG_WINDOW)
    df["entry"] = apply_trend_filter(raw_entry, trend)

    cost = TransactionCost(
        spread_pips=0.1,
        commission_per_round_trip=0.0,
        slippage_pips=0.2,
        pip_size=PIP_SIZE_BY_SYMBOL.get(symbol, DEFAULT_PIP_SIZE),
    )
    trades = run_backtest(df, PARAMS, cost)
    return compute_metrics(trades) if len(trades) > 0 else None


if __name__ == "__main__":
    rows = []
    for symbol in SYMBOLS:
        try:
            m = check_symbol(symbol)
        except Exception as exc:
            print(f"{symbol}: gagal -- {exc}")
            rows.append({"symbol": symbol, "trades": "error", "win_rate": "-", "profit_factor": "-", "max_dd_pips": "-", "sharpe": "-"})
            continue

        if m is None:
            rows.append({"symbol": symbol, "trades": 0, "win_rate": "-", "profit_factor": "-", "max_dd_pips": "-", "sharpe": "-"})
            continue

        rows.append(
            {
                "symbol": symbol,
                "trades": m.total_trades,
                "win_rate": f"{m.win_rate:.1%}",
                "profit_factor": f"{m.profit_factor:.2f}",
                "max_dd_pips": f"{m.max_drawdown_pips:.0f}",
                "sharpe": f"{m.sharpe_ratio:.2f}",
            }
        )

    print(pd.DataFrame(rows).to_string(index=False))
    print(
        "\nReferensi EURUSD dengan parameter+cost yang sama: seluruh data "
        "(trend_filter.py) profit_factor=1.21, sharpe=0.87; in-sample "
        "(run_research.py) 1.29/1.18; out-of-sample 0.98/-0.07."
    )
    print(
        "Yang dicari: apakah profit_factor & sharpe di simbol lain "
        "konsisten positif dan sepadan dengan angka EURUSD di atas, atau "
        "EURUSD outlier sendirian."
    )

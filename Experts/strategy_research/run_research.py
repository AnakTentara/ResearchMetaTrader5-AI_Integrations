"""
run_research.py

Orkestrasi resmi Fase 2: split kronologis in-sample/out-of-sample,
kembangkan & evaluasi HANYA di in-sample, baru cek out-of-sample SATU
KALI di akhir dengan parameter yang sudah dibekukan sebelumnya.

ATURAN YANG TIDAK BOLEH DILANGGAR: begitu angka out-of-sample keluar
untuk simbol tertentu, JANGAN kembali mengubah parameter untuk simbol
itu lalu jalankan ulang. Itu sama saja diam-diam menjadikan data
out-of-sample sebagai bahan tuning juga.

Bisa dijalankan untuk simbol lain (python run_research.py AUDUSD
USDCAD) -- parameter TETAP beku persis sama untuk semua simbol, tidak
disetel ulang per simbol. Ini memperluas PERTANYAAN yang sama ("apakah
edge-nya stabil lintas waktu") ke instrumen lain, bukan kesempatan
mencari-cari simbol yang kebetulan cocok.

Parameter di bawah ini SUDAH DIBEKUKAN dari eksplorasi in-sample EURUSD
sebelumnya (param_sweep.py + trend_filter.py) -- lookback=20, stop_z=3.0,
ditambah filter tren long_window=200.

Catatan indikator: zscore dan arah tren dihitung di atas SELURUH data
historis secara kontinu (supaya rolling window di awal periode
out-of-sample tetap punya konteks yang benar dari akhir periode
in-sample) -- pemisahan in-sample/out-of-sample baru diterapkan setelah
itu, ke DAFTAR TRADE hasil backtest, berdasarkan waktu entry masing-
masing trade.
"""

from backtest_engine import TransactionCost, run_backtest
from fetch_historical import fetch_historical
from metrics import compute_metrics
from signals.mean_reversion import MeanReversionParams, compute_entry_signals, compute_zscore
from signals.trend_filter import apply_trend_filter, compute_trend_direction

IN_SAMPLE_RATIO = 0.75
TREND_LONG_WINDOW = 200

# Parameter beku -- sama untuk semua simbol, tidak disetel ulang.
PARAMS = MeanReversionParams(lookback=20, entry_z=2.0, exit_z=0.5, stop_z=3.0, max_hold_bars=48)
COST = TransactionCost(spread_pips=0.1, commission_per_round_trip=0.0, slippage_pips=0.2)


def run_research(symbol: str = "EURUSD"):
    raw_df = fetch_historical(symbol=symbol, timeframe_name="H1", tahun_terakhir=2.0)

    split_idx = int(len(raw_df) * IN_SAMPLE_RATIO)
    split_date = raw_df["time"].iloc[split_idx]

    df = compute_zscore(raw_df, lookback=PARAMS.lookback)
    raw_entry = compute_entry_signals(df, PARAMS)
    trend = compute_trend_direction(df, long_window=TREND_LONG_WINDOW)
    df["entry"] = apply_trend_filter(raw_entry, trend)

    trades = run_backtest(df, PARAMS, COST)

    print(f"=== {symbol} ===")
    if len(trades) == 0:
        print("Tidak ada trade sama sekali dengan parameter ini.")
        return

    in_sample = trades[trades["entry_time"] < split_date]
    out_of_sample = trades[trades["entry_time"] >= split_date]

    print(f"Titik pisah (kronologis, {IN_SAMPLE_RATIO:.0%} data): {split_date}")
    print(
        f"Total bar: {len(raw_df)}  |  In-sample: {split_idx} bar  |  "
        f"Out-of-sample: {len(raw_df) - split_idx} bar\n"
    )

    print("--- IN-SAMPLE ---")
    print(compute_metrics(in_sample) if len(in_sample) > 0 else "Tidak ada trade di periode in-sample.")

    print("\n--- OUT-OF-SAMPLE (cek SEKALI -- jangan diulang-ulang) ---")
    print(compute_metrics(out_of_sample) if len(out_of_sample) > 0 else "Tidak ada trade di periode out-of-sample.")


if __name__ == "__main__":
    import sys

    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["EURUSD"]
    for i, symbol in enumerate(symbols):
        if i > 0:
            print()
        run_research(symbol)

"""
signals/trend_filter.py

Filter arah tren jangka panjang -- BUKAN pengganti mean_reversion.py,
melainkan lapisan tambahan di atasnya. mean_reversion.py sengaja TIDAK
diubah sama sekali (sudah teruji); modul ini murni menyaring sinyal
yang sudah ada.

Hipotesis (dari pola drawdown di param_sweep.py): mean-reversion murni
babak belur justru saat melawan tren kuat yang sedang berjalan. Modul
ini menambah SATU informasi baru yang sebelumnya sama sekali tidak
dilihat sinyal manapun -- arah moving average jangka panjang -- dan
memblokir sinyal yang melawannya.

long_window=200 dipilih karena itu konvensi MA jangka panjang paling
umum di industri trading, BUKAN dicari lewat coba-coba di data ini --
beda dengan mencoba banyak angka lalu pilih yang paling cocok (itu
justru yang barusan kita hindari di param_sweep.py).

Sengaja dibuat sesederhana mungkin: cuma TANDA kemiringan (naik/turun),
bukan magnitude berambang -- supaya tidak menambah parameter baru yang
bisa jadi celah overfitting lagi.
"""

import pandas as pd


def compute_trend_direction(df: pd.DataFrame, long_window: int = 200) -> pd.Series:
    """
    +1 = MA jangka panjang sedang naik, -1 = sedang turun, NaN = masih
    masa warmup (belum cukup riwayat). Pakai shift(1), disiplin sama
    dengan compute_zscore -- bar sekarang tidak ikut menghitung MA-nya
    sendiri.
    """
    if "close" not in df.columns:
        raise ValueError("df harus punya kolom 'close'")
    if len(df) <= long_window:
        raise ValueError(
            f"Data cuma {len(df)} bar, kurang dari long_window={long_window}."
        )

    long_ma = df["close"].shift(1).rolling(window=long_window).mean()
    slope = long_ma.diff(1)

    direction = pd.Series(index=df.index, dtype="float64")
    direction[slope > 0] = 1
    direction[slope < 0] = -1
    direction[slope == 0] = 0  # jarang terjadi di harga riil, tetap ditangani
    # slope NaN (masa warmup) otomatis tetap NaN di sini -- disengaja,
    # lihat penanganannya di apply_trend_filter.

    return direction


def apply_trend_filter(entry_signal: pd.Series, trend_direction: pd.Series) -> pd.Series:
    """
    Blokir sinyal yang melawan arah tren: BUY diblokir saat downtrend,
    SELL diblokir saat uptrend. Fail-safe: kalau arah tren belum
    diketahui (NaN, masa warmup 200 bar pertama), blokir KEDUA arah --
    jangan diam-diam meloloskan sinyal mentah tanpa filter.
    """
    filtered = entry_signal.copy()
    filtered[(entry_signal == 1) & (trend_direction == -1)] = 0
    filtered[(entry_signal == -1) & (trend_direction == 1)] = 0
    filtered[trend_direction.isna()] = 0
    return filtered


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from backtest_engine import TransactionCost, run_backtest
    from metrics import compute_metrics
    from signals.mean_reversion import MeanReversionParams, compute_entry_signals, compute_zscore

    cache_file = Path(__file__).parent.parent / "data" / "EURUSD_H1.csv"
    if not cache_file.exists():
        raise FileNotFoundError(f"{cache_file} belum ada. Jalankan fetch_historical.py dulu.")

    raw_df = pd.read_csv(cache_file)
    raw_df["time"] = pd.to_datetime(raw_df["time"], utc=True)

    # Pakai kandidat terbaik dari param_sweep.py sebagai basis
    # perbandingan (stop_z=3.0), bukan baseline paling awal.
    params = MeanReversionParams(lookback=20, entry_z=2.0, exit_z=0.5, stop_z=3.0, max_hold_bars=48)
    cost = TransactionCost(spread_pips=0.1, commission_per_round_trip=0.0, slippage_pips=0.2)

    df = compute_zscore(raw_df, lookback=params.lookback)
    raw_entry = compute_entry_signals(df, params)
    trend = compute_trend_direction(df, long_window=200)
    filtered_entry = apply_trend_filter(raw_entry, trend)

    print("=== TANPA filter tren ===")
    df_a = df.copy()
    df_a["entry"] = raw_entry
    trades_a = run_backtest(df_a, params, cost)
    print(compute_metrics(trades_a) if len(trades_a) > 0 else "Tidak ada trade.")

    print("\n=== DENGAN filter tren (long_window=200) ===")
    df_b = df.copy()
    df_b["entry"] = filtered_entry
    trades_b = run_backtest(df_b, params, cost)
    print(compute_metrics(trades_b) if len(trades_b) > 0 else "Tidak ada trade.")

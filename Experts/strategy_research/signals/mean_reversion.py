"""
signals/mean_reversion.py

Sinyal mean-reversion berbasis Z-score dari moving average.

Modul ini CUMA menghitung sinyal per bar -- tidak mensimulasikan siklus
posisi (buka/tahan/tutup). Alasan pemisahan: logika "buka posisi, tahan,
cek exit/stop/time-exit" itu generik dan akan dipakai ulang oleh
backtest_engine.py untuk sinyal apa pun -- kalau ditaruh di sini, harus
ditulis ulang tiap kali ada sinyal baru (RSI, dst).

Formula: zscore = (close - rolling_mean) / rolling_std, dengan
rolling_mean/rolling_std dihitung dari `lookback` bar SEBELUM bar ini
(tidak termasuk bar ini sendiri) -- supaya tidak ada look-ahead bias:
di dunia nyata, saat bar sekarang masih berjalan, closing price-nya
belum diketahui.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class MeanReversionParams:
    lookback: int = 20        # jumlah bar riwayat untuk hitung mean/std
    entry_z: float = 2.0      # buka posisi kalau |zscore| >= ini
    exit_z: float = 0.5       # tutup posisi (reverted) kalau |zscore| <= ini
    stop_z: float = 3.5       # tutup posisi (stop loss) kalau |zscore| >= ini
    max_hold_bars: int = 48   # tutup posisi (time exit) kalau sudah sepanjang ini


def compute_zscore(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """
    Tambahkan kolom rolling_mean, rolling_std, zscore ke df.

    df harus punya kolom 'close', terurut kronologis (paling lama di atas,
    seperti hasil fetch_historical.py). Baris paling awal (kurang dari
    `lookback` bar riwayat) akan NaN -- normal, bukan bug, karena belum
    ada cukup riwayat untuk dihitung.
    """
    if "close" not in df.columns:
        raise ValueError("df harus punya kolom 'close'")
    if len(df) <= lookback:
        raise ValueError(
            f"Data cuma {len(df)} bar, kurang dari lookback={lookback}. "
            "Perbesar tahun_terakhir di fetch_historical kalau perlu."
        )

    out = df.copy()

    # shift(1) memastikan bar sekarang TIDAK ikut dihitung dalam mean/std
    # miliknya sendiri -- itu inti dari "tanpa look-ahead bias".
    prior_close = out["close"].shift(1)
    out["rolling_mean"] = prior_close.rolling(window=lookback).mean()
    out["rolling_std"] = prior_close.rolling(window=lookback).std()
    out["zscore"] = (out["close"] - out["rolling_mean"]) / out["rolling_std"]

    return out


def compute_entry_signals(df: pd.DataFrame, params: MeanReversionParams) -> pd.Series:
    """
    Sinyal entry mentah untuk SETIAP bar (vectorized, bukan row-by-row --
    supaya tetap cepat saat nanti dipanggil berulang kali sambil coba-coba
    parameter). +1 = sinyal BUY, -1 = sinyal SELL, 0 = tidak ada sinyal.

    Ini murni "apa kata sinyal di bar ini" -- belum tahu apakah sedang ada
    posisi terbuka atau tidak, itu urusan backtest_engine.py. Bar dengan
    zscore NaN (di awal data) otomatis dapat sinyal 0.
    """
    z = df["zscore"]
    signal = pd.Series(0, index=df.index, dtype="int8")
    signal[z <= -params.entry_z] = 1
    signal[z >= params.entry_z] = -1
    return signal


if __name__ == "__main__":
    from pathlib import Path

    cache_file = Path(__file__).parent.parent / "data" / "EURUSD_H1.csv"
    if not cache_file.exists():
        raise FileNotFoundError(
            f"{cache_file} belum ada. Jalankan dulu fetch_historical.py "
            "(dari folder strategy_research/) supaya ada cache data."
        )

    df = pd.read_csv(cache_file)
    df["time"] = pd.to_datetime(df["time"], utc=True)

    df = compute_zscore(df, lookback=20)
    params = MeanReversionParams()
    df["entry"] = compute_entry_signals(df, params)

    n_buy = int((df["entry"] == 1).sum())
    n_sell = int((df["entry"] == -1).sum())

    print(df[["time", "close", "rolling_mean", "rolling_std", "zscore", "entry"]].tail(10))
    print(f"\nTotal bar: {len(df)}")
    print(f"Sinyal BUY  (zscore <= -{params.entry_z}): {n_buy}")
    print(f"Sinyal SELL (zscore >= +{params.entry_z}): {n_sell}")

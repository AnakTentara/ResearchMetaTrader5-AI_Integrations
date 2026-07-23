"""
backtest_engine.py

Mensimulasikan siklus posisi (entry -> exit/stop/time-exit) dari sinyal
mentah yang dihasilkan signals/mean_reversion.py, dengan biaya transaksi
realistis. Hasilnya: DataFrame trade individual (bukan lagi sinyal
mentah per-bar) -- lihat ARCHITECTURE.md dan ROADMAP.md untuk kenapa
pemisahan sinyal vs backtest ini sengaja dibuat begini.

DISIPLIN "TANPA LOOK-AHEAD BIAS" (diterapkan konsisten, bukan cuma di
entry): keputusan APAPUN -- entry, reverted, stop_loss, time_exit --
ditentukan dari data yang tersedia di CLOSE bar ke-i, tapi eksekusinya
disimulasikan di OPEN bar ke-(i+1). Di dunia nyata, selama bar ke-i
masih berjalan, closing price-nya belum diketahui -- baik untuk membuka
posisi maupun menutupnya.

KETERBATASAN YANG SENGAJA (bukan bug, baca dulu sebelum bingung):
- Tidak ada pembalikan posisi. Sinyal berlawanan yang muncul saat masih
  ada posisi terbuka DIABAIKAN -- posisi cuma ditutup lewat
  reverted/stop_loss/time_exit. Simplifikasi sengaja untuk v1.
- max_hold_bars menghitung BAR, bukan jam kalender asli. Trade yang
  menyeberangi weekend (pasar forex tutup) bisa "48 bar" tapi lebih
  dari 48 jam sungguhan. Simplifikasi sengaja untuk v1 -- kandidat
  pertama diperbaiki kalau metrics.py nanti menunjukkan pola aneh
  khusus di trade yang menyeberangi weekend.
- Biaya transaksi dibebankan penuh di entry, exit dianggap bersih --
  ini SETARA secara matematis dengan membagi ke dua kaki untuk P&L
  akhir, bukan aproksimasi.
"""

from dataclasses import dataclass

import pandas as pd

from signals.mean_reversion import MeanReversionParams, compute_entry_signals, compute_zscore


@dataclass
class TransactionCost:
    spread_pips: float = 0.1
    # Komisi ECN/raw (kalau ada) dalam PIPS-EKUIVALEN per round-trip,
    # bukan dalam dolar -- supaya modul ini tetap konsisten kerja dalam
    # pips (position sizing & uang sungguhan baru masuk di Fase 3).
    # Cara isi kalau akun ternyata berkomisi: buka+tutup 1 trade kecil
    # di demo, jumlahkan kolom Commission di tab History (buka + tutup
    # kalau dikenakan di dua sisi), lalu bagi dengan pip value lot itu
    # (EURUSD standard lot pip value ~$10; proporsional untuk lot lain).
    commission_per_round_trip: float = 0.0
    slippage_pips: float = 0.2
    pip_size: float = 0.0001

    @property
    def total_cost_pips(self) -> float:
        return self.spread_pips + self.commission_per_round_trip + self.slippage_pips


REQUIRED_COLUMNS = {"time", "open", "close", "zscore", "entry"}


def _apply_entry_cost(open_price: float, direction: int, cost: TransactionCost) -> float:
    """direction: +1 = BUY, -1 = SELL."""
    adjustment = cost.total_cost_pips * cost.pip_size
    return open_price + adjustment if direction == 1 else open_price - adjustment


def _pnl_pips(direction: int, entry_price: float, exit_price: float, pip_size: float) -> float:
    diff = exit_price - entry_price
    return (diff if direction == 1 else -diff) / pip_size


def run_backtest(
    df: pd.DataFrame,
    params: MeanReversionParams,
    cost: TransactionCost,
) -> pd.DataFrame:
    """
    df: hasil compute_zscore() + compute_entry_signals(), kolom wajib
    ada di REQUIRED_COLUMNS, terurut kronologis (paling lama di atas).

    Kembalikan DataFrame trade individual dengan kolom: direction,
    entry_time, entry_price, exit_time, exit_price, exit_reason,
    bars_held, pnl_pips. Kosong (0 baris) kalau tidak ada trade sama
    sekali -- itu valid, bukan error.
    """
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"df kurang kolom: {missing}")
    if len(df) < 3:
        raise ValueError("df terlalu pendek untuk backtest (minimal 3 baris)")

    # open/close/zscore/entry diambil sebagai array numpy dulu, bukan
    # diakses lewat df.iloc[i] di dalam loop -- .iloc[] per-baris itu
    # lambat karena overhead pandas per akses. Untuk data puluhan ribu
    # bar yang dipanggil berulang kali saat coba-coba parameter, bedanya
    # cukup terasa. Kolom 'time' tetap Series biasa karena cuma diakses
    # saat mencatat 1 trade (jarang), bukan tiap bar.
    time_col = df["time"]
    open_arr = df["open"].to_numpy(dtype="float64")
    close_arr = df["close"].to_numpy(dtype="float64")
    zscore_arr = df["zscore"].to_numpy(dtype="float64")
    entry_arr = df["entry"].to_numpy(dtype="int8")

    n = len(df)
    trades: list[dict] = []

    direction = None
    entry_price = None
    entry_time = None
    entry_index = None

    for i in range(n - 1):  # butuh bar i+1 untuk eksekusi
        if direction is None:
            sig = entry_arr[i]
            if sig != 0:
                direction = int(sig)
                entry_price = _apply_entry_cost(open_arr[i + 1], direction, cost)
                entry_time = time_col.iloc[i + 1]
                entry_index = i + 1
            continue

        # Sedang ada posisi -- cek kondisi keluar dari zscore bar ini.
        z = zscore_arr[i]
        bars_held = i - entry_index + 1

        exit_reason = None
        if abs(z) <= params.exit_z:
            exit_reason = "reverted"
        elif abs(z) >= params.stop_z:
            exit_reason = "stop_loss"
        elif bars_held >= params.max_hold_bars:
            exit_reason = "time_exit"

        if exit_reason is not None:
            exit_price = open_arr[i + 1]
            pnl = _pnl_pips(direction, entry_price, exit_price, cost.pip_size)
            trades.append(
                {
                    "direction": "BUY" if direction == 1 else "SELL",
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "exit_time": time_col.iloc[i + 1],
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "bars_held": bars_held,
                    "pnl_pips": pnl,
                }
            )
            direction = None
            entry_price = None
            entry_time = None
            entry_index = None

    # Data habis sementara masih ada posisi terbuka -- tutup paksa di
    # close bar terakhir yang tersedia, tandai jelas supaya metrics.py
    # bisa memilih meng-exclude-nya dari kesimpulan statistik (ini
    # bukan exit "natural", cuma kehabisan data historis).
    if direction is not None:
        exit_price = close_arr[-1]
        pnl = _pnl_pips(direction, entry_price, exit_price, cost.pip_size)
        trades.append(
            {
                "direction": "BUY" if direction == 1 else "SELL",
                "entry_time": entry_time,
                "entry_price": entry_price,
                "exit_time": time_col.iloc[-1],
                "exit_price": exit_price,
                "exit_reason": "end_of_data",
                "bars_held": (n - 1) - entry_index + 1,
                "pnl_pips": pnl,
            }
        )

    return pd.DataFrame(trades)


if __name__ == "__main__":
    from pathlib import Path

    cache_file = Path(__file__).parent / "data" / "EURUSD_H1.csv"
    if not cache_file.exists():
        raise FileNotFoundError(
            f"{cache_file} belum ada. Jalankan dulu fetch_historical.py."
        )

    df = pd.read_csv(cache_file)
    df["time"] = pd.to_datetime(df["time"], utc=True)

    params = MeanReversionParams()
    df = compute_zscore(df, lookback=params.lookback)
    df["entry"] = compute_entry_signals(df, params)

    # spread dari observasi Market Watch (0-2 poin, rata-rata ~1 poin
    # = 0.1 pip untuk broker 5-digit). commission_per_round_trip masih
    # 0.0 -- isi kalau ternyata akunnya berkomisi, lihat catatan cara
    # cek di atas.
    cost = TransactionCost(spread_pips=0.1, commission_per_round_trip=0.0, slippage_pips=0.2)

    trades = run_backtest(df, params, cost)

    print(trades.head(10))
    print(f"\nTotal trade: {len(trades)}")
    if len(trades) > 0:
        print(f"Total pnl_pips (kasar, TANPA position sizing): {trades['pnl_pips'].sum():.1f}")
        print("\nBreakdown exit_reason:")
        print(trades["exit_reason"].value_counts())

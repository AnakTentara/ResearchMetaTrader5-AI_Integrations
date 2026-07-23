"""
metrics.py

Ubah DataFrame trade individual (hasil backtest_engine.run_backtest())
jadi angka-angka ringkas: win rate, profit factor, max drawdown, Sharpe
ratio -- plus penanda eksplisit kalau jumlah trade terlalu sedikit untuk
disimpulkan apa pun secara statistik.

Trade dengan exit_reason == "end_of_data" DIKELUARKAN dari semua
statistik di sini -- itu bukan hasil trading sungguhan, cuma posisi
yang terpaksa ditutup karena data historisnya habis. Tetap dihitung dan
dilaporkan terpisah supaya tidak hilang diam-diam.
"""

import math
from dataclasses import dataclass

import pandas as pd

MIN_TRADES_FOR_SIGNIFICANCE = 100
TRADING_DAYS_PER_YEAR = 252


@dataclass
class BacktestMetrics:
    total_trades: int
    excluded_end_of_data: int
    win_rate: float
    avg_win_pips: float
    avg_loss_pips: float
    profit_factor: float
    total_pnl_pips: float
    max_drawdown_pips: float
    sharpe_ratio: float
    is_statistically_thin: bool

    def __str__(self) -> str:
        thin_warning = (
            f"\n  !! HANYA {self.total_trades} TRADE -- di bawah ambang "
            f"{MIN_TRADES_FOR_SIGNIFICANCE}, JANGAN simpulkan apa pun dari "
            f"angka-angka ini. Perpanjang rentang data atau tunggu lebih "
            f"banyak sinyal sebelum mempercayai hasil ini."
            if self.is_statistically_thin
            else ""
        )
        return (
            f"Total trade         : {self.total_trades} "
            f"(+{self.excluded_end_of_data} end_of_data dikecualikan)\n"
            f"Win rate            : {self.win_rate:.1%}\n"
            f"Rata-rata win       : {self.avg_win_pips:+.1f} pips\n"
            f"Rata-rata loss      : {self.avg_loss_pips:+.1f} pips\n"
            f"Profit factor       : {self.profit_factor:.2f}\n"
            f"Total pnl           : {self.total_pnl_pips:+.1f} pips\n"
            f"Max drawdown        : {self.max_drawdown_pips:.1f} pips\n"
            f"Sharpe (tahunan)    : {self.sharpe_ratio:.2f}"
            f"{thin_warning}"
        )


def compute_metrics(trades: pd.DataFrame) -> BacktestMetrics:
    if len(trades) == 0:
        raise ValueError("Tidak ada trade sama sekali -- tidak ada yang bisa dihitung.")

    excluded = trades[trades["exit_reason"] == "end_of_data"]
    clean = (
        trades[trades["exit_reason"] != "end_of_data"]
        .sort_values("exit_time")
        .reset_index(drop=True)
    )

    if len(clean) == 0:
        raise ValueError(
            "Semua trade adalah end_of_data (belum ada yang keluar secara "
            "natural) -- data historisnya kemungkinan terlalu pendek."
        )

    wins = clean.loc[clean["pnl_pips"] > 0, "pnl_pips"]
    losses = clean.loc[clean["pnl_pips"] <= 0, "pnl_pips"]

    win_rate = len(wins) / len(clean)
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = losses.mean() if len(losses) > 0 else 0.0

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    total_pnl = clean["pnl_pips"].sum()

    equity = clean["pnl_pips"].cumsum()
    running_max = equity.cummax()
    max_drawdown = (equity - running_max).min()  # nilai <= 0

    sharpe = _annualized_sharpe(clean)

    return BacktestMetrics(
        total_trades=len(clean),
        excluded_end_of_data=len(excluded),
        win_rate=win_rate,
        avg_win_pips=avg_win,
        avg_loss_pips=avg_loss,
        profit_factor=profit_factor,
        total_pnl_pips=total_pnl,
        max_drawdown_pips=max_drawdown,
        sharpe_ratio=sharpe,
        is_statistically_thin=len(clean) < MIN_TRADES_FOR_SIGNIFICANCE,
    )


def _annualized_sharpe(clean_trades: pd.DataFrame) -> float:
    """
    Sharpe dihitung dari kurva ekuitas pip yang di-resample HARIAN --
    bukan per-trade langsung -- supaya perhitungannya sepadan dengan
    waktu (Sharpe pada dasarnya ukuran risiko per satuan WAKTU, bukan
    per satuan trade). Equity cuma berubah saat trade ditutup, jadi
    hari tanpa trade di-forward-fill dari nilai terakhir yang diketahui.

    Catatan: dihitung dalam PIPS (position sizing belum ada di sistem
    ini -- lihat ARCHITECTURE.md). Untuk ukuran lot yang tetap, ini
    sepadan dengan Sharpe berbasis uang; begitu Fase 3 menambahkan
    position sizing dinamis, angka ini perlu dihitung ulang dari kurva
    ekuitas uang sungguhan, bukan pip.
    """
    equity = clean_trades.set_index("exit_time")["pnl_pips"].cumsum()
    daily_equity = equity.resample("1D").last().ffill()
    daily_returns = daily_equity.diff().dropna()

    if len(daily_returns) < 2 or daily_returns.std() == 0:
        return float("nan")

    return (daily_returns.mean() / daily_returns.std()) * math.sqrt(TRADING_DAYS_PER_YEAR)


if __name__ == "__main__":
    from pathlib import Path

    from backtest_engine import TransactionCost, run_backtest
    from signals.mean_reversion import MeanReversionParams, compute_entry_signals, compute_zscore

    cache_file = Path(__file__).parent / "data" / "EURUSD_H1.csv"
    if not cache_file.exists():
        raise FileNotFoundError(f"{cache_file} belum ada. Jalankan dulu fetch_historical.py.")

    df = pd.read_csv(cache_file)
    df["time"] = pd.to_datetime(df["time"], utc=True)

    params = MeanReversionParams()
    df = compute_zscore(df, lookback=params.lookback)
    df["entry"] = compute_entry_signals(df, params)

    cost = TransactionCost(spread_pips=0.1, commission_per_round_trip=0.0, slippage_pips=0.2)
    trades = run_backtest(df, params, cost)

    if len(trades) == 0:
        print("Tidak ada trade sama sekali dengan parameter ini -- cek entry_z/lookback.")
    else:
        metrics = compute_metrics(trades)
        print(metrics)

"""
forward_observation/observer.py

Amati sinyal strategi (Z-score + filter tren, parameter BEKU dari
Fase 2 -- diimpor langsung dari strategy_research/, TIDAK disalin) di
harga LANGSUNG, catat keputusan yang AKAN diambil -- TANPA mengirim
order sungguhan sama sekali. Tujuan: kumpulkan data out-of-sample yang
genuinely baru, berjalan ke depan dari sekarang, bukan replay data
historis.

CARA JALAN: dipanggil BERKALA (mis. Task Scheduler Windows, tiap jam,
beberapa menit setelah bar H1 baru semestinya close), satu kali cek
lalu keluar -- bukan proses yang terus hidup. Kalau ada beberapa bar
baru sekaligus (skrip sempat tidak jalan beberapa jam), SEMUA diproses
urut kronologis, bukan cuma bar terakhir -- supaya tidak ada sinyal
yang hilang diam-diam.

STATE MACHINE per simbol (disimpan di state/state_{symbol}.json):
  NONE -> sinyal entry muncul -> PENDING_ENTRY
  PENDING_ENTRY -> bar berikutnya close -> buka posisi @ open bar ini
                   -> OPEN, LANGSUNG cek exit di bar yang sama
                   (bars_held=1, persis seperti backtest_engine.py)
  OPEN -> tiap bar: bars_held+=1, cek exit_z/stop_z/max_hold_bars
          -> terpicu -> PENDING_EXIT | tidak -> tetap OPEN
  PENDING_EXIT -> bar berikutnya close -> tutup @ open bar ini,
                  catat ke logs/trades_{symbol}.csv -> NONE

Kolom trades_{symbol}.csv sengaja SAMA dengan skema DataFrame trade di
backtest_engine.py -- supaya metrics.py bisa langsung dipakai ulang di
data forward ini nanti tanpa modifikasi.
"""

import json
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "strategy_research"))

import MetaTrader5 as mt5  # noqa: E402
from fetch_historical import fetch_recent_bars  # noqa: E402
from run_research import COST, PARAMS, TREND_LONG_WINDOW  # noqa: E402
from signals.mean_reversion import compute_entry_signals, compute_zscore  # noqa: E402
from signals.trend_filter import apply_trend_filter, compute_trend_direction  # noqa: E402

TIMEFRAME = mt5.TIMEFRAME_H1
TIMEFRAME_SECONDS = 3600

STATE_DIR = Path(__file__).parent / "state"
LOG_DIR = Path(__file__).parent / "logs"

logger = logging.getLogger(__name__)


def _state_path(symbol: str) -> Path:
    return STATE_DIR / f"state_{symbol}.json"


def _trades_path(symbol: str) -> Path:
    return LOG_DIR / f"trades_{symbol}.csv"


def _load_state(symbol: str) -> dict:
    path = _state_path(symbol)
    if not path.exists():
        return {"status": "NONE", "last_processed_bar_time": None}
    return json.loads(path.read_text())


def _save_state(symbol: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(symbol).write_text(json.dumps(state, indent=2, default=str))


def _append_trade(symbol: str, trade: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _trades_path(symbol)
    pd.DataFrame([trade]).to_csv(path, mode="a", header=not path.exists(), index=False)


def _entry_cost_adjustment(direction: int) -> float:
    # Mencerminkan _apply_entry_cost di backtest_engine.py -- disalin
    # kecil di sini karena fungsi aslinya private (underscore-prefixed),
    # tidak dimaksudkan diimpor lintas file.
    return COST.total_cost_pips * COST.pip_size * (1 if direction == 1 else -1)


def _pnl_pips(direction: int, entry_price: float, exit_price: float) -> float:
    diff = exit_price - entry_price
    return (diff if direction == 1 else -diff) / COST.pip_size


def _process_bar(symbol: str, state: dict, bar: pd.Series) -> dict:
    """Satu langkah state machine untuk satu bar. Return state baru."""
    status = state["status"]

    if status == "PENDING_ENTRY":
        direction = state["pending_direction"]
        entry_price = bar["open"] + _entry_cost_adjustment(direction)
        state = {
            "status": "OPEN",
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": str(bar["time"]),
            "bars_held": 0,
        }
        logger.info(
            "[%s] Posisi paper DIBUKA: %s @ %.5f (%s)",
            symbol, "BUY" if direction == 1 else "SELL", entry_price, bar["time"],
        )
        status = "OPEN"

    elif status == "PENDING_EXIT":
        exit_price = bar["open"]
        direction = state["direction"]
        pnl = _pnl_pips(direction, state["entry_price"], exit_price)
        _append_trade(symbol, {
            "direction": "BUY" if direction == 1 else "SELL",
            "entry_time": state["entry_time"],
            "entry_price": state["entry_price"],
            "exit_time": str(bar["time"]),
            "exit_price": exit_price,
            "exit_reason": state["exit_reason"],
            "bars_held": state["bars_held"],
            "pnl_pips": pnl,
        })
        logger.info(
            "[%s] Posisi paper DITUTUP: alasan=%s @ %.5f, pnl=%.1f pips",
            symbol, state["exit_reason"], exit_price, pnl,
        )
        state = {"status": "NONE"}
        status = "NONE"

    if status == "OPEN":
        state["bars_held"] += 1
        z = abs(bar["zscore"])
        exit_reason = None
        if z <= PARAMS.exit_z:
            exit_reason = "reverted"
        elif z >= PARAMS.stop_z:
            exit_reason = "stop_loss"
        elif state["bars_held"] >= PARAMS.max_hold_bars:
            exit_reason = "time_exit"

        if exit_reason is not None:
            state["status"] = "PENDING_EXIT"
            state["exit_reason"] = exit_reason
            logger.info(
                "[%s] Sinyal keluar (%s) @ bar %s, dieksekusi bar berikutnya",
                symbol, exit_reason, bar["time"],
            )

    elif status == "NONE":
        if bar["entry"] != 0:
            state = {"status": "PENDING_ENTRY", "pending_direction": int(bar["entry"])}
            logger.info(
                "[%s] Sinyal entry terdeteksi @ bar %s, dibuka bar berikutnya",
                symbol, bar["time"],
            )

    return state


def observe_once(symbol: str = "EURUSD") -> None:
    state = _load_state(symbol)

    bars = fetch_recent_bars(symbol, TIMEFRAME, TIMEFRAME_SECONDS, count=300)
    df = compute_zscore(bars, lookback=PARAMS.lookback)
    raw_entry = compute_entry_signals(df, PARAMS)
    trend = compute_trend_direction(df, long_window=TREND_LONG_WINDOW)
    df["entry"] = apply_trend_filter(raw_entry, trend)

    last_processed = state.get("last_processed_bar_time")
    if last_processed is not None:
        new_bars = df[df["time"] > pd.Timestamp(last_processed)]
    else:
        # Run pertama kali -- mulai dari bar terakhir saja, jangan
        # "menemukan" sinyal lama di riwayat sebagai sinyal baru.
        new_bars = df.tail(1)

    if len(new_bars) == 0:
        logger.info("[%s] Tidak ada bar baru sejak run terakhir.", symbol)
        return

    for _, bar in new_bars.iterrows():
        state = _process_bar(symbol, state, bar)

    state["last_processed_bar_time"] = str(new_bars.iloc[-1]["time"])
    _save_state(symbol, state)


if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "observer.log"), logging.StreamHandler()],
    )

    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["EURUSD"]
    for symbol in symbols:
        try:
            observe_once(symbol)
        except Exception:
            logger.exception("[%s] Gagal jalan kali ini.", symbol)
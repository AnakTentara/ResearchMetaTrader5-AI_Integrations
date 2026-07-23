"""
fetch_historical.py

Tarik data historis (OHLC) dari terminal MT5 yang sudah berjalan di mesin
yang sama, lalu cache ke disk sebagai CSV -- supaya eksperimen backtest
berikutnya (coba-coba parameter sinyal) tidak perlu menarik ulang data
yang sama dari MT5 setiap kali.

Modul ini sengaja netral terhadap sinyal apa pun -- dipakai ulang oleh
sinyal apa saja yang dikembangkan di folder signals/.

CATATAN TIMEZONE (baca dulu sebelum curiga ada bug kalau hasil terlihat
geser beberapa jam): dokumentasi resmi MetaTrader5 menyatakan timestamp
bar disimpan dalam UTC, dan kode di bawah mengikuti itu -- date_from/
date_to dibuat eksplisit UTC-aware, kolom 'time' hasil dikonversi dengan
utc=True. Tapi di lapangan, cukup banyak laporan pengguna MT5 bahwa yang
sebenarnya terjadi adalah "waktu server broker", yang untuk kebanyakan
broker memang disamakan dengan UTC tapi tidak ada jaminan mutlak untuk
semua broker, dan tidak ada cara mengecek ini lewat API Python-nya
sendiri. Kalau nanti backtest terlihat konsisten geser beberapa jam dari
yang diharapkan, ini kemungkinan besar penyebabnya -- bukan bug di kode
ini.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as exc:
    raise ImportError(
        "Package 'MetaTrader5' belum terpasang. Jalankan: pip install MetaTrader5"
    ) from exc

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "data"


def _cache_path(symbol: str, timeframe_name: str) -> Path:
    return CACHE_DIR / f"{symbol}_{timeframe_name}.csv"


def fetch_historical(
    symbol: str = "EURUSD",
    timeframe: int = mt5.TIMEFRAME_H1,
    timeframe_name: str = "H1",
    tahun_terakhir: float = 2.0,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Kembalikan DataFrame OHLC historis untuk `symbol`.

    Pakai cache di data/{symbol}_{timeframe_name}.csv kalau sudah ada,
    kecuali force_refresh=True. Kolom hasil: time (UTC, tz-aware), open,
    high, low, close, tick_volume, spread, real_volume.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(symbol, timeframe_name)

    if not force_refresh and cache_file.exists():
        logger.info("Pakai cache: %s (set force_refresh=True untuk tarik ulang)", cache_file)
        df = pd.read_csv(cache_file)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df

    if not mt5.initialize():
        code, desc = mt5.last_error()
        raise RuntimeError(
            f"mt5.initialize() gagal ({code}: {desc}). Pastikan terminal "
            "MetaTrader 5 sedang terbuka dan sudah login ke akun sebelum "
            "menjalankan script ini."
        )

    try:
        if not mt5.symbol_select(symbol, True):
            code, desc = mt5.last_error()
            raise RuntimeError(
                f"Simbol {symbol} tidak bisa diaktifkan di Market Watch "
                f"({code}: {desc}). Buka Market Watch di MT5, klik kanan -> "
                f"Symbols, pastikan {symbol} ada dan dicentang."
            )

        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(days=int(tahun_terakhir * 365.25))

        rates = mt5.copy_rates_range(symbol, timeframe, date_from, date_to)

        if rates is None or len(rates) == 0:
            code, desc = mt5.last_error()
            raise RuntimeError(
                f"Tidak ada data untuk {symbol} ({timeframe_name}) dari "
                f"{date_from.date()} sampai {date_to.date()} ({code}: {desc}). "
                "Cek nama simbol persis sesuai Market Watch di MT5, dan "
                "pastikan simbolnya sudah 'visible' di sana."
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)

    finally:
        mt5.shutdown()

    df.to_csv(cache_file, index=False)
    logger.info("Tersimpan %d bar ke cache: %s", len(df), cache_file)

    return df


def fetch_recent_bars(symbol: str, timeframe: int, timeframe_seconds: int, count: int = 300) -> pd.DataFrame:
    """
    Tarik N bar TERAKHIR langsung dari MT5 (mt5.copy_rates_from_pos),
    TANPA cache -- untuk pemantauan berkala/live (dipakai
    forward_observation/observer.py), beda dari fetch_historical() yang
    untuk riset rentang panjang dengan cache.

    Buang bar yang masih berjalan (belum benar-benar close) secara
    eksplisit lewat perbandingan waktu -- jangan mengasumsikan
    start_pos tertentu otomatis melompati bar yang sedang berjalan,
    lebih aman verifikasi sendiri lewat waktu close yang diharapkan.
    """
    if not mt5.initialize():
        code, desc = mt5.last_error()
        raise RuntimeError(
            f"mt5.initialize() gagal ({code}: {desc}). Pastikan terminal "
            "MetaTrader 5 sedang terbuka dan sudah login."
        )
    try:
        if not mt5.symbol_select(symbol, True):
            code, desc = mt5.last_error()
            raise RuntimeError(
                f"Simbol {symbol} tidak bisa diaktifkan di Market Watch "
                f"({code}: {desc}). Buka Market Watch di MT5, klik kanan -> "
                f"Symbols, pastikan {symbol} ada dan dicentang."
            )
        # Beri waktu sebentar supaya terminal mulai streaming simbol ini --
        # copy_rates_from_pos sering kembali kosong kalau dipanggil
        # LANGSUNG setelah symbol_select tanpa jeda sama sekali.
        time.sleep(0.5)

        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + 2)
    finally:
        mt5.shutdown()

    if rates is None or len(rates) == 0:
        code, desc = mt5.last_error()
        raise RuntimeError(
            f"Tidak ada data live untuk {symbol} ({code}: {desc}). Kalau "
            f"symbol_select barusan berhasil tapi tetap kosong, coba buka "
            f"chart {symbol} manual sekali di MT5 dulu supaya datanya "
            f"benar-benar mulai mengalir, baru jalankan skrip ini lagi."
        )

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)

    now_utc = datetime.now(timezone.utc)
    expected_close = df["time"] + pd.Timedelta(seconds=timeframe_seconds)
    df = df[expected_close <= now_utc]

    return df.tail(count).reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    data = fetch_historical()
    print(data.head())
    print(data.tail())
    print(f"Total bar: {len(data)}")
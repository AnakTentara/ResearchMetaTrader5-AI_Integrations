# strategy_research/

Riset dan validasi statistik untuk strategi arah (Fase 2) — Strategy
Agent. Terpisah total dari `python_backend/`: tidak ada panggilan ke
Gemini/LLM apa pun di folder ini, murni data harga historis + statistik.
Tidak ada eksekusi order di sini — hasil akhirnya baru dipakai di Fase 3.

## Setup

```
pip install -r requirements.txt
```

Jalankan skrip di folder ini dengan terminal MetaTrader 5 sudah terbuka
dan login ke akun (demo/live) di mesin yang sama — package `MetaTrader5`
terhubung ke terminal lokal, bukan API cloud.

## Modul

### `fetch_historical.py`

Tarik data OHLC historis via package `MetaTrader5`, cache ke `data/`
sebagai CSV supaya eksperimen berikutnya tidak menarik ulang dari MT5.

Cara pakai:
```python
from fetch_historical import fetch_historical
df = fetch_historical(symbol="EURUSD", timeframe_name="H1", tahun_terakhir=2)
```

Cara uji cepat:
```
python fetch_historical.py
```
- Run pertama: menarik dari MT5 (agak lambat, tergantung rentang tahun).
- Run kedua: harus jauh lebih cepat karena baca dari `data/EURUSD_H1.csv`.
- Set `force_refresh=True` untuk sengaja menarik ulang (mis. kalau mau
  memperpanjang rentang tahun).

Kalau `mt5.initialize()` gagal, pesan errornya akan bilang persis
kenapa (biasanya: terminal belum dibuka / belum login).

### `signals/mean_reversion.py`

Sinyal Z-score dari moving average. Cuma menghitung sinyal per bar
(`rolling_mean`, `rolling_std`, `zscore`, entry mentah) — TIDAK
mensimulasikan siklus posisi (itu tugas `backtest_engine.py`, belum
dibuat).

Parameter (lewat `MeanReversionParams`): `lookback` (jumlah bar
riwayat), `entry_z`/`exit_z`/`stop_z` (ambang zscore), `max_hold_bars`
(batas lama posisi ditahan).

Cara pakai:
```python
from signals.mean_reversion import compute_zscore, compute_entry_signals, MeanReversionParams

df = compute_zscore(df, lookback=20)
params = MeanReversionParams()
df["entry"] = compute_entry_signals(df, params)
```

Cara uji cepat (baca dari cache `fetch_historical.py`, tidak perlu MT5):
```
python signals/mean_reversion.py
```
Mencetak 10 baris terakhir plus total sinyal BUY/SELL yang terdeteksi
selama rentang data yang di-cache.

### `signals/trend_filter.py`

Lapisan tambahan di atas `mean_reversion.py` — bukan pengganti, dan
`mean_reversion.py` sendiri tidak diubah sama sekali. Menghitung arah
MA jangka panjang (`long_window=200`, konvensi standar industri, bukan
hasil coba-coba) dan memblokir sinyal yang melawannya: BUY diblokir
saat downtrend, SELL diblokir saat uptrend. Fail-safe: saat arah tren
belum diketahui (200 bar pertama, masa warmup), KEDUA arah diblokir.

Dipicu oleh pola drawdown di `param_sweep.py` — mean-reversion murni
babak belur saat melawan tren kuat.

Cara pakai (menggabungkan dengan sinyal mean_reversion yang sudah ada):
```python
from signals.mean_reversion import compute_zscore, compute_entry_signals
from signals.trend_filter import compute_trend_direction, apply_trend_filter

df = compute_zscore(df, lookback=params.lookback)
raw_entry = compute_entry_signals(df, params)
trend = compute_trend_direction(df, long_window=200)
df["entry"] = apply_trend_filter(raw_entry, trend)
# df["entry"] sekarang siap dipakai run_backtest() seperti biasa —
# backtest_engine.py dan metrics.py juga tidak perlu diubah sama sekali.
```

Cara uji cepat (baca dari cache, tidak perlu MT5) — mencetak metrik
TANPA dan DENGAN filter berdampingan, pakai parameter terbaik dari
`param_sweep.py` (stop_z=3.0):
```
python signals/trend_filter.py
```

### `backtest_engine.py`

Simulasi siklus posisi lengkap: entry → tahan → keluar
(reverted/stop_loss/time_exit/end_of_data), dengan biaya transaksi
(spread + komisi + slippage). Input: DataFrame hasil `compute_zscore()`
+ `compute_entry_signals()`. Output: DataFrame trade individual (bukan
lagi sinyal mentah per-bar).

Disiplin "tanpa look-ahead bias" diterapkan konsisten: keputusan apa
pun (entry maupun keluar) ditentukan dari data di *close* bar ke-i,
eksekusi disimulasikan di *open* bar ke-(i+1).

Keterbatasan yang sengaja untuk v1 (detail di komentar kode): tidak ada
pembalikan posisi, dan `max_hold_bars` menghitung bar bukan jam
kalender asli (relevan untuk trade yang menyeberangi weekend).

Cara pakai:
```python
from backtest_engine import run_backtest, TransactionCost

cost = TransactionCost(spread_pips=0.1, commission_per_round_trip=0.0, slippage_pips=0.2)
trades = run_backtest(df, params, cost)
```

Cara uji cepat (baca dari cache, tidak perlu MT5):
```
python backtest_engine.py
```
Mencetak 10 trade pertama, total jumlah trade, total pnl_pips kasar
(tanpa position sizing — itu Fase 3), dan breakdown alasan keluar.

**Cek wajib begitu ini jalan:** bandingkan jumlah trade di sini dengan
hitungan sinyal mentah dari `mean_reversion.py` (1.127+1.085=2.212) —
jumlah trade HARUS jauh lebih sedikit, karena sinyal berturut-turut
selama satu posisi masih terbuka sekarang dikonsolidasi jadi satu
trade. Kalau angkanya masih dekat 2.212, ada yang salah di state
machine-nya.

### `metrics.py`

Ubah DataFrame trade dari `backtest_engine.py` jadi angka ringkas: win
rate, profit factor, max drawdown, Sharpe ratio (tahunan, dihitung dari
kurva ekuitas pip yang di-resample harian). Trade `end_of_data`
dikecualikan dari statistik (bukan hasil trading sungguhan), tapi tetap
dilaporkan jumlahnya secara terpisah.

Otomatis memberi peringatan kalau total trade di bawah 100
(`MIN_TRADES_FOR_SIGNIFICANCE`) — jangan percaya angka apa pun kalau
peringatan ini muncul.

Cara pakai:
```python
from metrics import compute_metrics
m = compute_metrics(trades)
print(m)
```

Cara uji cepat — ini menjalankan SELURUH pipeline Fase 2 sekaligus
(baca cache → hitung sinyal → backtest → metrics), tidak perlu MT5:
```
python metrics.py
```

**Penting saat baca hasilnya:** ini jalan di seluruh data sekaligus,
TANPA split in-sample/out-of-sample. Cukup untuk cek cepat "apakah
pipeline-nya jalan dan ada sinyal awal", tapi bukan pengganti disiplin
out-of-sample sebelum menyimpulkan strategi ini layak dipakai atau
tidak — itu tugas `run_research.py` di bawah.

### `param_sweep.py`

Alat eksplorasi cepat: jalankan beberapa kombinasi `MeanReversionParams`
sekaligus di data yang sama, cetak tabel perbandingan. Dipicu oleh hasil
baseline (`lookback=20, stop_z=3.5`) yang profit factor-nya 1,03 dan
Sharpe 0,16 — terlalu tipis untuk lanjut ke `run_research.py` tanpa
coba variasi dulu.

Bukan pengganti `run_research.py` — ini murni in-sample, seluruh data
sekaligus, buat menyaring kandidat sebelum diuji lebih serius.

Cara uji cepat (baca dari cache, tidak perlu MT5):
```
python param_sweep.py
```

### (Selanjutnya) `run_research.py`

Belum dibuat — orkestrasi resmi: split in-sample (75%) / out-of-sample
(25%, terkunci) → sinyal → backtest → metrik di in-sample → SATU kali
cek di out-of-sample di akhir. Baru layak dibangun setelah
`param_sweep.py` menunjukkan ada kombinasi yang jelas lebih baik dari
baseline.

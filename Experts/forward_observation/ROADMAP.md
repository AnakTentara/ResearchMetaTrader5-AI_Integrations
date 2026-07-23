# Roadmap HaikaruTrade

> Status per fase. Update bagian status tiap kali sesuatu selesai —
> lihat ARCHITECTURE.md untuk detail *kenapa* keputusan di bawah
> diambil, bukan cuma *apa*-nya.

## Fase 1 — Risk-Context Backend + Fondasi EA

**Status: selesai secara fungsional, satu verifikasi kecil masih
menggantung.**

- [x] `python_backend/` — pipeline 2 tahap Gemma, key rotation, quota
      tracking, atomic write ke `signal.json`. Diuji end-to-end,
      berhasil (`safe_to_trade=False, tone=mixed`). Bug `tzdata` di
      Windows ditemukan dan diperbaiki (lihat ARCHITECTURE.md).
- [x] `HaikaruTrade.mq5` + `SignalReader.mqh` — baca `signal.json`,
      validasi kadaluarsa, tampilkan status di chart. Belum ada
      eksekusi order (sesuai rencana — nunggu Fase 3).
- [ ] **Verifikasi terakhir**: konfirmasi ulang di chart MT5 sekarang
      bahwa EA menunjukkan status yang benar (bukan pesan "signal.json
      tidak ada" yang sempat muncul sebelumnya). Kemungkinan besar itu
      cuma sisa sebelum run pertama selesai, tapi belum ada konfirmasi
      eksplisit — cukup lihat `Comment()` di chart sekarang.

## Fase 2 — Riset & Validasi Strategi Direksional

**Status: tooling selesai, menunggu keputusan dari hasil out-of-sample.**

Ruang lingkup sengaja dipersempit: EURUSD, H1, mean-reversion Z-score
dulu (bukan stat-arb pairs — itu iterasi lanjutan setelah ini terbukti
jalan).

- [x] `fetch_historical.py` — tarik + cache data historis via package
      `MetaTrader5`. Tervalidasi dengan data asli (2024–2026, 12.393
      bar H1).
- [x] `signals/mean_reversion.py` — Z-score (tanpa look-ahead bias) +
      sinyal entry mentah.
- [x] `backtest_engine.py` — state machine posisi (entry → tahan →
      exit/stop/time-exit), biaya transaksi realistis. Tervalidasi:
      2.212 sinyal mentah terkonsolidasi jadi 718 trade sungguhan
      (baseline awal) — konfirmasi state machine bekerja benar, bukan
      cuma meloloskan tiap sinyal mentah sebagai trade terpisah.
- [x] `metrics.py` — Sharpe ratio, max drawdown, win rate, profit
      factor, dengan peringatan otomatis kalau trade < 100.
- [x] **Temuan #1 (parameter default):** profit factor 1,03, Sharpe
      0,16, max drawdown -630 pips vs total profit +220,6 pips — edge
      terlalu tipis untuk dipercaya.
- [x] `param_sweep.py` *(modul tambahan, tidak direncanakan di awal)* —
      6 kombinasi dicoba. Terbaik: `stop_z=3.0` (profit factor 1,04,
      Sharpe 0,24). Lookback lebih panjang (50) dan entry lebih
      selektif (2,5) justru memperburuk hasil — dua hipotesis yang
      kelihatannya masuk akal, terbukti salah di data ini.
- [x] `signals/trend_filter.py` *(modul tambahan, dipicu pola
      drawdown)* — filter arah MA 200-bar (konvensi standar, bukan
      hasil coba-coba), memblokir sinyal yang melawan tren. **Perbaikan
      signifikan** dibanding `stop_z=3.0` tanpa filter: profit factor
      1,04→1,21, Sharpe 0,24→0,87, max drawdown -561,7→-243,0 pips,
      total pnl +307,5→+693,4 pips. Semua masih di atas SELURUH data
      (in-sample penuh, belum displit).
- [x] `run_research.py` — orkestrasi resmi, digeneralisasi menerima
      simbol lain (`python run_research.py EURUSD AUDUSD USDCAD`).
      Parameter dibekukan (`lookback=20, stop_z=3.0` + filter tren
      `long_window=200`), cek out-of-sample sekali per simbol.
- [x] `cross_instrument_check.py` — validasi silang instrumen
      (full-data, belum displit): GBPUSD (13 trade) dan USDJPY (18
      trade) sampelnya terlalu kecil untuk berarti (Sharpe 5,16 di
      USDJPY kemungkinan besar noise sampel kecil). AUDUSD (379 trade,
      PF 1,17) dan USDCAD (341 trade, PF 1,21) konsisten dengan EURUSD
      full-data (PF 1,21) — sinyal ini generalisasi lintas instrumen di
      level ini.

### Verdict Fase 2 (cek out-of-sample penuh: EURUSD + AUDUSD + USDCAD)

**Hasil: konsisten turun dari in-sample ke out-of-sample di ketiga
instrumen** (profit factor: 1,29→0,98 / 1,26→0,98 / 1,22→1,16). Catatan
metodologis penting: ketiga split jatuh di tanggal kalender yang nyaris
sama, jadi ini lebih tepat dibaca sebagai "satu periode kalender,
dilihat lewat tiga instrumen berkorelasi" — bukan tiga observasi
independen (detail di ARCHITECTURE.md, bagian "Batasan yang diketahui").

**Keputusan: strategi Z-score + filter tren dengan parameter ini BELUM
lanjut ke Fase 3.** Sesuai disiplin yang sudah dipegang sejak awal,
parameter ini TIDAK disetel ulang lagi di data yang sama. Dua jalur ke
depan dipilih untuk dikerjakan **paralel**: (a) eksplorasi hipotesis
sinyal yang benar-benar baru, bukan variasi dari z-score yang sama, dan
(b) observasi maju di `forward_observation/` — dimulai duluan karena
faktor waktu tidak bisa dipercepat.

## Observasi Maju (berjalan paralel, berkelanjutan)

**Status: berjalan.** `forward_observation/observer.py` — state
machine yang mengamati sinyal (parameter beku, sama persis dengan
`strategy_research/`) di harga live tiap jam, mencatat keputusan yang
AKAN diambil TANPA eksekusi order sungguhan. Menghasilkan
`logs/trades_{symbol}.csv` dengan skema identik trade DataFrame
`backtest_engine.py` — bisa langsung dianalisis pakai `metrics.py` yang
sama begitu cukup terkumpul (ambang sama: ~100 trade).

Ini yang menjawab bagian "testimoni Buy Sell with Machine" yang
disebut jauh sebelumnya — tapi dalam bentuk logging aman, bukan
eksekusi order sungguhan, karena strategi belum lolos validasi
out-of-sample.

## Fase 3 — Implementasi Strategi + Manajemen Risiko di EA

**Status: belum dimulai.** Menunggu Fase 2 menghasilkan strategi yang
lolos validasi out-of-sample. Port aturan ke `HaikaruTrade.mq5`, tambah
position sizing, SL/TP, circuit breaker max-daily-loss. Tiap order
wajib lolos gate `safe_to_trade` dari Fase 1 dulu.

## Fase 4 — Data Logging

**Status: belum dimulai.** Riwayat tiap sinyal, keputusan, trade, kurva
equity — sumber data dashboard nanti. Beda dari `quota.db` yang sudah
ada sekarang (itu khusus kuota API, bukan riwayat trading).

## Fase 5 — Dashboard

**Status: belum dimulai.** Web dashboard untuk monitoring — paling
akhir, setelah semua di atas terbukti jalan end-to-end.

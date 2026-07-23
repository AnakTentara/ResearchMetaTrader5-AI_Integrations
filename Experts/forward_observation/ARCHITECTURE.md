# Arsitektur HaikaruTrade

> Dokumen ini adalah sumber kebenaran tunggal untuk keputusan desain
> sistem. Kalau mulai sesi AI baru (chat lain, atau alat lain), paste
> dokumen ini dulu supaya konteksnya tidak perlu dijelaskan ulang dari
> nol.
>
> Terakhir diperbarui: setelah Fase 2 (`fetch_historical.py` +
> `signals/mean_reversion.py`) selesai dan tervalidasi dengan data asli.

## Ringkasan

HaikaruTrade adalah bot trading algoritmik untuk MetaTrader 5,
terinspirasi pendekatan kuantitatif Jim Simons/Renaissance
Technologies. Kombinasi: analisis sentimen berita berbasis LLM (sebagai
filter risiko, BUKAN pemberi sinyal arah) + strategi arah berbasis
statistik yang divalidasi lewat backtesting.

## Prinsip inti

### 1. Otak dan tangan terpisah

Python menangani analisis yang lambat/berat ("otak"): panggilan LLM,
riset statistik. MQL5 EA menangani eksekusi yang cepat ("tangan"): baca
sinyal, kelola posisi, kirim order. Keduanya tidak saling menunggu
secara langsung — komunikasi lewat file (`signal.json`), bukan
panggilan sinkron.

### 2. LLM adalah filter risiko, bukan peramal arah

Pipeline Gemini (`python_backend/`) HANYA menghasilkan `safe_to_trade`
(boolean) — tidak pernah field `direction`. Alasan: tidak ada LLM yang
punya *genuine forward-looking market edge*; menyuruhnya berperan
sebagai trader top hanya membuat tebakan tanpa dasar terdengar lebih
percaya diri. Sinyal arah harus datang dari riset statistik tervalidasi
(`strategy_research/`), bukan dari LLM.

Ini sempat berbeda dari deskripsi awal proyek ("Model Kedua"
menggabungkan sentimen + teknikal langsung jadi BUY/SELL) — sudah
diselesaikan dengan memisahkan jadi dua peran: **Strategy Agent**
(statistik, `strategy_research/`) menghasilkan arah, **pipeline
Gemini** (`python_backend/`) menghasilkan gate keamanan. Fase 2 sudah
dibangun konsisten dengan pemisahan ini.

### 3. Modular, satu potong kecil sekaligus

Tiap fase dan tiap modul dalam fase punya folder/file sendiri,
divalidasi (pseudocode dulu, lalu diuji di demo/data nyata) sebelum
lanjut ke modul berikutnya.

### 4. Fail-safe di semua titik gagal

Kalau ragu, sistem harus jatuh ke kondisi AMAN (tidak trading), bukan
diam-diam menganggap semuanya baik-baik saja. Contoh: parse gagal →
`tone: unknown`; semua API key habis → biarkan sinyal lama (EA akan
menganggapnya basi); file signal tidak terbaca → EA anggap TIDAK aman.

## Komponen sistem

| Komponen | Lokasi | Peran | Status |
|---|---|---|---|
| Risk-filter backend | `python_backend/` | Analisis berita 2 tahap → `safe_to_trade` | Selesai, tervalidasi end-to-end |
| EA eksekusi | `HaikaruTrade.mq5` + `SignalReader.mqh` | Baca `signal.json`, validasi kadaluarsa, tampilkan status | Selesai untuk Fase 1 (belum ada eksekusi order — sesuai rencana) |
| Riset strategi | `strategy_research/` | Cari & validasi sinyal arah lewat data historis | Tooling selesai; hasil out-of-sample EURUSD/AUDUSD/USDCAD belum cukup meyakinkan — lihat ROADMAP.md |
| Observasi maju | `forward_observation/` | Catat keputusan strategi di harga live, TANPA eksekusi order — kumpulkan data out-of-sample baru | Berjalan (paralel dengan eksplorasi sinyal baru) |
| Manajemen risiko | *(belum dibuat)* | Position sizing, SL/TP, circuit breaker | Fase 3 |
| Data logging | *(belum dibuat)* | Riwayat sinyal/trade/equity | Fase 4 |
| Dashboard | *(belum dibuat)* | Monitoring web | Fase 5 |

## Kontrak data: `signal.json`

Ditulis atomik (`.tmp` lalu rename) oleh `signal_writer.py`, dibaca EA
lewat `FILE_COMMON`.

| Field | Tipe | Sumber |
|---|---|---|
| `symbol` | string | konstanta di `orchestrator.py` |
| `generated_at_unix` | number (float) | `time.time()` saat ditulis |
| `generated_at_utc` | string | representasi manusia-terbaca, tidak dipakai untuk logika |
| `calendar_blackout` | bool | `economic_calendar.py`, non-AI |
| `calendar_reason` | string atau null | idem |
| `news_tone` | string | `news_analyst.py` (Gemma 26B-A4B) |
| `safe_to_trade` | bool | `financial_reviewer.py` (Gemma 31B) DAN `calendar_blackout` |
| `review_reason` | string | `financial_reviewer.py` |

**Tidak ada field arah (BUY/SELL) di sini — sengaja, lihat Prinsip #2.**

## Keputusan desain (kenapa, bukan cuma apa)

- **Gemma 26B-A4B (MoE) untuk tahap 1, Gemma 31B dense untuk tahap 2** —
  tahap 1 (grounded search) dipanggil lebih sering/perlu cepat, MoE
  cocok. Tahap 2 (checklist review) jarang dipanggil, butuh reasoning
  lebih dalam, dense cocok. Diverifikasi lewat dokumentasi resmi Google
  (rilis April 2026) — arsitekturnya memang dirancang untuk pembagian
  peran seperti ini.
- **EA MQL5 untuk eksekusi, bukan package Python `MetaTrader5`** — MQL5
  native jauh lebih andal untuk eksekusi cepat live. Package Python
  dipakai HANYA untuk riset data historis offline
  (`strategy_research/fetch_historical.py`), tidak pernah untuk live
  order.
- **`TimeGMT()`, bukan `TimeCurrent()`, di sisi MQL5** — `TimeCurrent()`
  itu waktu tick server terakhir (bisa macet saat sepi/weekend).
  `TimeGMT()` dihitung dari jam PC lokal + offset GMT, sepadan dengan
  `time.time()` Python. (Di dalam Strategy Tester, `TimeGMT()` ikut
  waktu simulasi — lihat "Batasan yang diketahui" di bawah.)
- **Parser JSON manual di MQL5, bukan library pihak ketiga** — MQL5
  tidak punya JSON parser bawaan; skema `signal.json` flat dan tetap,
  jadi parser kecil buatan sendiri cukup, tanpa dependency tambahan.
- **Z-score dari moving average untuk sinyal Fase 2 pertama** (bukan
  Bollinger Bands atau RSI) — matematis mirip Bollinger tapi lebih
  murni statistik, dan pondasinya bisa dipakai ulang untuk stat-arb
  (Z-score dari *spread* dua instrumen) kalau nanti sampai ke situ.
- **`signals/mean_reversion.py` cuma hitung sinyal, tidak simulasi
  posisi** — logika buka/tahan/tutup posisi itu generik (dipakai untuk
  sinyal apa pun), jadi dipisah ke `backtest_engine.py` supaya tidak
  ditulis ulang tiap ada sinyal baru.
- **Backtest engine ditulis sendiri, bukan pakai library siap pakai** —
  untuk proyek belajar, menulis sendiri mengajarkan hal-hal seperti
  look-ahead bias dengan cara yang tidak didapat kalau logikanya
  disembunyikan di dalam library orang lain.

## Batasan yang diketahui (desain di sekitarnya, jangan coba dihindari)

- **MT5 Strategy Tester tidak bisa menguji lapisan risk-filter (LLM).**
  Dua alasan independen: (1) `TimeGMT()`/`TimeCurrent()` di dalam
  tester mengikuti waktu simulasi, bukan waktu nyata, merusak
  perbandingan kadaluarsa terhadap `generated_at_unix` yang selalu
  waktu nyata; (2) Google Search grounding selalu mengambil hasil HARI
  INI, tidak bisa "diputar ulang" ke tanggal historis manapun. Strategi
  arah (Fase 2) divalidasi lewat backtest Python murni terhadap harga
  historis; lapisan risk-filter divalidasi lewat observasi live/forward
  di demo, bukan backtest historis.
- **Timestamp MT5 didokumentasikan UTC, tapi beberapa laporan komunitas
  menyebut ini sebenarnya "waktu server broker".** Tidak ada cara
  memverifikasi ini lewat API Python-nya sendiri. Kalau backtest
  terlihat geser beberapa jam secara konsisten, ini kemungkinan besar
  penyebabnya.
- **`tzdata` wajib di-install eksplisit di Windows** untuk modul apa
  pun yang pakai `zoneinfo` (mis. `quota_tracker.py`) — Windows tidak
  punya database IANA bawaan seperti Linux/macOS. Sudah masuk
  `python_backend/requirements.txt`.
- **Jumlah sinyal mentah per-bar bukan jumlah trade.** Sinyal
  mean-reversion yang tetap terpicu selama beberapa bar berturut-turut
  (mis. saat harga terus menjauh selama tren kuat) akan terhitung
  berkali-kali di `mean_reversion.py` sampai `backtest_engine.py`
  menerapkan aturan "sudah ada posisi terbuka, abaikan sinyal masuk
  baru". Jangan simpulkan apa pun dari hitungan mentah sebelum
  `backtest_engine.py` ada.
- **Split in-sample/out-of-sample dengan rasio & rentang tahun yang
  sama di beberapa instrumen menghasilkan periode out-of-sample yang
  TUMPANG TINDIH secara kalender, bukan periode independen.** Ditemukan
  saat menguji EURUSD/AUDUSD/USDCAD sekaligus — ketiganya kebetulan
  split di tanggal yang nyaris sama (awal Januari 2026), jadi "tiga
  konfirmasi out-of-sample" itu sebenarnya lebih dekat ke "satu periode
  kalender, dilihat lewat tiga instrumen berkorelasi (sama-sama
  pasangan USD)" — bukan tiga observasi independen. Kalau butuh
  independensi temporal yang sungguhan lintas instrumen, perlu titik
  potong yang berbeda-beda per instrumen, bukan rasio 75/25 yang sama
  untuk semua.

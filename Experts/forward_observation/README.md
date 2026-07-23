# forward_observation/

Observasi maju (walk-forward, live) dari strategi Fase 2 (Z-score +
filter tren, parameter beku) — TANPA eksekusi order sungguhan. Tujuan:
kumpulkan data out-of-sample yang genuinely baru, berjalan ke depan
dari sekarang, melengkapi hasil backtest historis di
`strategy_research/` yang menunjukkan edge belum terbukti stabil.

**Bukan Fase 3** — tidak ada order ke MT5 sama sekali, cuma pencatatan
"apa yang AKAN dilakukan strategi ini kalau berjalan sungguhan".

## Setup

Butuh `strategy_research/` ada persis sejajar (folder ini mengimpor
langsung dari situ — parameter, fungsi sinyal — bukan menyalin ulang).

```
python observer.py                       # default: EURUSD
python observer.py EURUSD AUDUSD USDCAD   # beberapa simbol sekaligus
```

**Wajib dijalankan berkala** (disarankan: tiap jam, beberapa menit
setelah bar H1 semestinya close, mis. menit ke-3), bukan sekali saja.

### Setup Task Scheduler Windows (ringkas)
1. Task Scheduler → Create Basic Task.
2. Trigger: Daily, repeat every 1 hour, mulai beberapa menit setelah
   jam bulat (mis. 00:03).
3. Action: Start a program → Program: path ke `python.exe`, Arguments:
   `observer.py EURUSD AUDUSD USDCAD`, Start in: folder ini.
4. Pastikan terminal MT5 tetap berjalan & login di jadwal itu.

## Yang dihasilkan

- `state/state_{symbol}.json` — status internal (posisi paper yang
  sedang berjalan, kalau ada). Jangan diedit manual.
- `logs/trades_{symbol}.csv` — riwayat trade paper yang SUDAH selesai.
  Skema kolomnya sama persis dengan trade DataFrame di
  `backtest_engine.py`, jadi bisa langsung dipakai ulang:
  ```python
  import pandas as pd
  from metrics import compute_metrics  # dari strategy_research/
  trades = pd.read_csv("forward_observation/logs/trades_EURUSD.csv",
                        parse_dates=["entry_time", "exit_time"])
  print(compute_metrics(trades))
  ```
- `logs/observer.log` — log naratif tiap kali skrip jalan, untuk
  debugging kalau ada yang terlihat aneh.

## Disiplin penting

- Parameter TIDAK boleh diubah selama observasi berjalan — kalau
  diubah di tengah jalan, data sebelum dan sesudah tidak bisa dianggap
  satu seri yang konsisten.
- Jangan buru-buru menyimpulkan dari beberapa trade pertama. Sesuai
  ambang yang sama dengan `metrics.py`, butuh waktu (kemungkinan
  berbulan-bulan, tergantung frekuensi sinyal) sampai terkumpul ~100
  trade sebelum angkanya berarti.
- `logs/trades_{symbol}.csv` itu data berharga yang tidak bisa
  digantikan kalau hilang (beda dari cache data historis yang bisa
  ditarik ulang kapan saja) — sengaja TIDAK di-gitignore, biarkan
  ter-commit berkala supaya ada jejak riwayatnya.

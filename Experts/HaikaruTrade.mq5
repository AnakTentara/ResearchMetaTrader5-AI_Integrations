//+------------------------------------------------------------------+
//|                                                 HaikaruTrade.mq5 |
//|                                       Copyright 2026, HaikalDev. |
//|                                     https://www.haikaldev.my.id/ |
//+------------------------------------------------------------------+
//| Fase 1 (EA side): baca signal.json dari python_backend/, validasi|
//| kadaluarsa ("penjaga akhir" yang disebut di README backend), dan |
//| tampilkan statusnya di chart. TIDAK ADA eksekusi order di sini.  |
//|                                                                    |
//| Eksekusi BUY/SELL baru masuk di Fase 3, setelah Fase 2 (strategi |
//| direksional tervalidasi lewat backtesting) tersedia. Menaruh     |
//| order sekarang berarti mengeksekusi tanpa strategi -- justru     |
//| yang ingin dihindari lewat pemisahan otak/tangan ini.            |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, HaikalDev."
#property link      "https://www.haikaldev.my.id/"
#property version   "1.01"

#include "SignalReader.mqh"

//--- Input: bisa diubah dari tab Inputs di MT5 tanpa recompile
input int InpMaxSignalAgeMinutes = 45;   // Batas basi sinyal (menit)
input int InpTimerSeconds        = 60;   // Interval baca signal.json (detik)

//--- State internal, dipakai lintas OnTimer/OnTick
bool   g_safeToTrade = false;
string g_lastTone    = "n/a";
string g_lastReason  = "belum ada sinyal dibaca";
double g_lastAgeSec  = -1;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(InpTimerSeconds);

   // Baca sekali saat init -- supaya status pertama langsung muncul
   // di chart, tidak perlu menunggu satu siklus timer penuh.
   RefreshSignalState();

   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment(""); // bersihkan chart saat EA dilepas
  }
//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   // SENGAJA KOSONG untuk Langkah 1 ini.
   // g_safeToTrade sudah tersedia untuk dipakai nanti -- tapi logika
   // BUY/SELL baru masuk di Fase 3. Lihat catatan di header file ini.
  }
//+------------------------------------------------------------------+
//| Timer function                                                   |
//+------------------------------------------------------------------+
void OnTimer()
  {
   RefreshSignalState();
  }
//+------------------------------------------------------------------+
//| Trade function                                                   |
//+------------------------------------------------------------------+
void OnTrade()
  {
  }
//+------------------------------------------------------------------+
//| Baca signal.json, validasi kadaluarsa, lalu update state + chart |
//+------------------------------------------------------------------+
void RefreshSignalState()
  {
   SignalData data;

   if(!SR_ReadSignal("signal.json", data))
     {
      g_safeToTrade = false;
      g_lastReason  = "signal.json tidak ada / gagal dibaca / rusak";
      g_lastAgeSec  = -1;
      PrintFormat("[HaikaruTrade] %s", g_lastReason);
      ShowStatus();
      return;
     }

   double ageSec = 0;
   bool fresh = SR_IsFresh(data, InpMaxSignalAgeMinutes, ageSec);
   g_lastAgeSec = ageSec;
   g_lastTone   = data.news_tone;

   if(!fresh)
     {
      g_safeToTrade = false;
      g_lastReason  = "sinyal basi (umur " + DoubleToString(ageSec, 0) + " detik)";
      PrintFormat("[HaikaruTrade] %s", g_lastReason);
      ShowStatus();
      return;
     }

   g_safeToTrade = data.safe_to_trade;
   g_lastReason  = data.review_reason;
   ShowStatus();
  }
//+------------------------------------------------------------------+
//| Tampilkan status terkini di pojok chart                          |
//+------------------------------------------------------------------+
void ShowStatus()
  {
   string ageText = (g_lastAgeSec < 0) ? "n/a" : (DoubleToString(g_lastAgeSec, 0) + " detik");

   Comment(
      "HaikaruTrade -- Fase 1 (risk-context only, belum ada order)\n",
      "Safe to trade : ", (g_safeToTrade ? "YA" : "TIDAK"), "\n",
      "Tone berita   : ", g_lastTone, "\n",
      "Umur sinyal   : ", ageText, "\n",
      "Alasan        : ", g_lastReason
     );
  }
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//|                                                 SignalReader.mqh |
//|                                       Copyright 2026, HaikalDev. |
//+------------------------------------------------------------------+
//| Modul kecil, satu tanggung jawab: baca signal.json yang ditulis  |
//| python_backend/signal_writer.py, lalu validasi apakah masih      |
//| segar. TIDAK ada logika order/eksekusi di sini (itu Fase 3).     |
//|                                                                    |
//| Parser JSON manual dipilih dengan sengaja: MQL5 tidak punya JSON |
//| parser bawaan, dan skema signal.json ini flat + tetap — pakai    |
//| library pihak ketiga untuk kasus sesederhana ini cuma menambah   |
//| dependency yang tidak perlu buat proyek belajar seperti ini.     |
//+------------------------------------------------------------------+
#ifndef SIGNAL_READER_MQH
#define SIGNAL_READER_MQH

struct SignalData
{
   string symbol;
   double generated_at_unix;
   bool   safe_to_trade;
   string news_tone;
   string review_reason;
};

//+------------------------------------------------------------------+
//| Ambil nilai string untuk pola "key":"value". Null-safe: kalau    |
//| value-nya JSON null (mis. calendar_reason saat tidak blackout),  |
//| berhenti di situ -- jangan lanjut cari kutip, nanti malah        |
//| kebaca kutip milik key berikutnya.                                |
//+------------------------------------------------------------------+
string SR_ExtractString(const string &json, const string key)
  {
   string pattern = "\"" + key + "\"";
   int pos = StringFind(json, pattern);
   if(pos < 0) return "";

   int colon = StringFind(json, ":", pos);
   if(colon < 0) return "";

   int start = colon + 1;
   while(start < StringLen(json) && StringGetCharacter(json, start) == ' ')
      start++;

   if(StringSubstr(json, start, 4) == "null")
      return "";

   int q1 = StringFind(json, "\"", start);
   if(q1 < 0) return "";
   int q2 = StringFind(json, "\"", q1 + 1);
   if(q2 < 0) return "";

   return StringSubstr(json, q1 + 1, q2 - q1 - 1);
  }

//+------------------------------------------------------------------+
//| Ambil nilai numerik untuk pola "key":number (dipakai untuk       |
//| generated_at_unix, yang ditulis Python sebagai float mentah).    |
//+------------------------------------------------------------------+
double SR_ExtractNumber(const string &json, const string key, double fallback)
  {
   string pattern = "\"" + key + "\"";
   int pos = StringFind(json, pattern);
   if(pos < 0) return fallback;

   int colon = StringFind(json, ":", pos);
   if(colon < 0) return fallback;

   int start = colon + 1;
   int len = StringLen(json);
   while(start < len && StringGetCharacter(json, start) == ' ')
      start++;

   int end = start;
   while(end < len)
     {
      ushort c = StringGetCharacter(json, end);
      bool isNumChar = (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E';
      if(!isNumChar) break;
      end++;
     }
   if(end == start) return fallback;
   return StringToDouble(StringSubstr(json, start, end - start));
  }

//+------------------------------------------------------------------+
//| Ambil nilai boolean untuk pola "key":true/false.                 |
//+------------------------------------------------------------------+
bool SR_ExtractBool(const string &json, const string key, bool fallback)
  {
   string pattern = "\"" + key + "\"";
   int pos = StringFind(json, pattern);
   if(pos < 0) return fallback;

   int colon = StringFind(json, ":", pos);
   if(colon < 0) return fallback;

   int start = colon + 1;
   while(start < StringLen(json) && StringGetCharacter(json, start) == ' ')
      start++;

   if(StringSubstr(json, start, 4) == "true")  return true;
   if(StringSubstr(json, start, 5) == "false") return false;
   return fallback;
  }

//+------------------------------------------------------------------+
//| Baca signal.json dari folder Common\Files dan isi struct out.    |
//| Return false untuk SEMUA kegagalan (file tidak ada, kosong,      |
//| atau timestamp tidak terbaca) -- pemanggil wajib menganggap ini  |
//| sebagai "tidak aman", bukan mengasumsikan apa pun.                |
//+------------------------------------------------------------------+
bool SR_ReadSignal(const string filename, SignalData &out)
  {
   int handle = FileOpen(filename, FILE_READ | FILE_TXT | FILE_COMMON);
   if(handle == INVALID_HANDLE)
      return false;

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

   if(StringLen(content) == 0)
      return false;

   out.symbol            = SR_ExtractString(content, "symbol");
   out.generated_at_unix = SR_ExtractNumber(content, "generated_at_unix", 0.0);
   out.safe_to_trade     = SR_ExtractBool(content, "safe_to_trade", false);
   out.news_tone         = SR_ExtractString(content, "news_tone");
   out.review_reason     = SR_ExtractString(content, "review_reason");

   // Kalau timestamp gagal terbaca (masih 0), file dianggap rusak --
   // gagal aman, jangan diam-diam anggap sinyal ini baru saja ditulis.
   if(out.generated_at_unix <= 0.0)
      return false;

   return true;
  }

//+------------------------------------------------------------------+
//| Cek apakah sinyal masih segar dibanding waktu sekarang (UTC).    |
//| Pakai TimeGMT(), bukan TimeCurrent(): TimeCurrent() itu waktu    |
//| server dari tick terakhir (bisa macet saat sepi/weekend),        |
//| sedangkan TimeGMT() itu jam UTC sungguhan -- yang sepadan dengan |
//| time.time() di sisi Python yang menulis generated_at_unix.       |
//+------------------------------------------------------------------+
bool SR_IsFresh(const SignalData &data, int maxAgeMinutes, double &ageSecondsOut)
  {
   double now_unix = (double)TimeGMT();
   ageSecondsOut = now_unix - data.generated_at_unix;

   // Umur negatif (jam PC lebih lambat dari saat Python menulis) juga
   // dianggap tidak valid -- daripada diam-diam menerima kejanggalan jam.
   if(ageSecondsOut < 0)
      return false;

   return ageSecondsOut <= (maxAgeMinutes * 60);
  }

#endif // SIGNAL_READER_MQH
# Hermes Agent Control Panel (XAMPP Style)

Software desktop Control Panel untuk **Hermes Agent** (Nous Research autonomous AI agent framework) dengan arsitektur & tampilan visual terinspirasi dari **XAMPP Control Panel**.

---

## 🚀 Fitur Utama

1. **Dashboard & Modules Table (XAMPP Style)**
   - **Hermes Web Dashboard** (Port: `9119` - Official web UI & session manager)
   - **Hermes Messaging Gateway** (Daemon worker untuk Telegram, Discord, WhatsApp)
   - **Hermes RPC Backend** (Port: `8642` - Headless JSON-RPC/WebSocket server)
   - **Hermes Chat Workspace** (Port: `8645` - Local testing & prompt playground)
   - Status badge real-time (`RUNNING`, `STOPPED`, `STARTING`)
   - Indikator PID dan Port aktif
   - Tombol kontrol per service: `[Start]`, `[Stop]`, `[Restart]`, `[Config]`, `[Open ↗]`, `[Admin/Test]`

2. **Top Action Toolbar**
   - `[Start All]` / `[Stop All]`: Jalankan atau hentikan seluruh background daemon sekaligus.
   - `[Shell]`: Buka PowerShell yang langsung terhubung ke environment isolated Hermes Agent.
   - `[CLI Chat]`: Buka jendela terminal baru dan langsung jalankan `hermes chat`.
   - `[TUI]`: Buka Fullscreen Terminal User Interface (`hermes --tui`).
   - `[YOLO]`: Buka mode tanpa konfirmasi manual (`hermes --yolo`).
   - `[Explorer]`: Buka folder instalasi, folder config `~/.hermes`, atau logs di Windows Explorer.
   - `[Config]`: Buka editor visual konfigurasi global.

3. **Model & Provider Switcher**
   - Mendukung berbagai provider: **OpenRouter**, **Nous Portal**, **OpenAI**, **Anthropic Claude**, **Groq**, **DeepSeek**, **Ollama (Lokal)**, **LM Studio (Lokal)**, atau Custom Endpoint.
   - Presets model siap pakai (Hermes 3 405B, 70B, 8B, GPT-4o, Claude 3.5 Sonnet, DeepSeek V3, dll).
   - Pengaturan API Key dengan tombol toggle hide/show.
   - Penyimpanan langsung ke `~/.hermes/config.yaml` dan `~/.hermes/.env`.

4. **Live Event & Output Console**
   - Log timestamped dengan pewarnaan level: `INFO` (Cyan), `SUCCESS` (Hijau), `WARN` (Kuning), `ERROR` (Merah).
   - Auto-scroll real-time.
   - Tombol `Copy Logs` dan `Clear Console`.

5. **Integrated API Tester**
   - Uji respon Hermes Gateway langsung dari Control Panel tanpa perlu membuka browser atau curl terminal.

---

## 🖥️ Cara Menjalankan

### Cara 1: Lewat Desktop Shortcut
- Double-click icon **"Hermes Control Panel"** di Desktop Anda.

### Cara 2: Lewat Windows Search / Start Menu
- Buka Start Menu, ketik **"Hermes Control Panel"**, lalu tekan Enter.

### Cara 3: Lewat Terminal / Batch File
```powershell
cd "C:\path\to\hermes-control-panel"
.\run.bat
```

### Cara 4: Akses Lewat Browser
- Jalankan `python app.py --web` atau buka:
  `http://127.0.0.1:8640`

---

## 📁 Struktur Direktori

```
C:\path\to\hermes-control-panel\
│
├── app.py                  # Entry point desktop (WebView2 native window)
├── hermes_manager.py       # Core backend controller (Service, PID, Ports, Config)
├── webui_server.py         # HTTP REST API server
├── run.bat                 # Windows batch launcher
├── run_silent.vbs          # Silent background launcher
├── icon.ico                # Official Hermes emblem icon
├── README.md               # Dokumentasi lengkap
│
└── ui\
    ├── index.html          # Layout XAMPP-style dashboard
    ├── style.css           # Modern dark-mode UI styling
    ├── app.js              # Interaksi frontend & live polling
    └── favicon.ico         # Web favicon
```

## Lisensi
MIT, lihat [LICENSE](LICENSE).

> Proyek independen, tidak berafiliasi dengan Nous Research. Hermes Agent harus diinstal terpisah.

# Teleops DVB 📺

**Teleops DVB** is a lightweight Python desktop application (built with Tkinter) designed for watching and recording DVB-C (Cable) and DVB-T/T2 (Terrestrial) TV and radio channels. It leverages `dvb-tools` for tuning and scanning, and **MPV** as the underlying playback engine, featuring full EPG (TV Guide) support and DVB subtitles.

---

## 🌟 Features

- 📡 **Automatic Channel Scanning:** Supports DVB-C (Cable) and DVB-T/T2 (Terrestrial) channel discovery.
- 📺 **MPV Player Integration:** High-performance video and audio playback via IPC socket control.
- 📋 **Live EPG (TV Guide):** Real-time display of current and upcoming programs with progress bars on the MPV OSD, plus a dedicated full guide window.
- 🔴 **Stream Recording:** Record live TV streams directly to `.ts` files.
- 💬 **DVB Subtitles:** Full support for DVB stream subtitles (including external/non-embedded streams).
- ⭐ **Favorites & Search:** Organize channels into TV, Radio, and Favorites with an instant search filter.
- 🌍 **Multilingual:** Built-in interface support for Romanian, English, and Italian.

---

## 🛠️ System Requirements & Dependencies

The application runs on Linux distributions (Ubuntu, Debian, Linux Mint, Arch, etc.).

Install the required dependencies on Debian/Ubuntu using:

```bash
sudo apt update
sudo apt install python3-tk mpv dvb-tools
```

*(Note: MPV installed via Flatpak `io.mpv.Mpv` is also automatically detected. No need to install mpv if you already have flatpak version).*

---

## 🚀 Installation & Usage

You don't need advanced Git skills to run this application. You can download and run it directly:

### Option A: Direct Download (ZIP)
1. Click the green **Code** button at the top of this repository page and select **Download ZIP**.
2. Extract the ZIP archive on your computer.
3. Open a terminal inside the extracted folder.
4. Run the script:
   ```bash
   python3 teleops.py
   ```

### Option B: Using Git
```bash
git clone https://github.com/lolopoco32/TeleopsDVB.git
cd TeleopsDVB
chmod +x teleops.py
./teleops.py
```

---
## ⌨️ Keyboard shortcuts
| Action | Shortcut |
|---|---|
| EPG info | `I` |
| Start/stop recording | `Ctrl + R` *(new)* |
| Fullscreen | `F` / `F11` *(new)* |
| Hide/show interface | `.` / double-click on video *(new)* |
| Quit program | `Ctrl + Shift + X` *(new)* |

---

## 📄 License

This project is licensed under the GNU General Public License v3.0 (GPLv3). Anyone is free to modify and redistribute this software, provided that any derivative works are also open-sourced under the same license terms.

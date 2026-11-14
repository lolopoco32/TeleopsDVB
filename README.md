# Teleops DVB 📺

**Teleops DVB** is a lightweight Python desktop application (built with Tkinter) designed for watching and recording DVB-C (Cable) and DVB-T/T2 (Terrestrial) TV and radio channels. It leverages `dvb-tools` (`dvbv5-scan`, `dvbv5-zap`, `dvb-fe-tool`) for tuning, scanning, and signal probing, and **MPV** (native or Flatpak `io.mpv.Mpv`) as the embedded playback engine, featuring live and full EPG (TV Guide), scheduled recordings, automatic channel switching, DVB subtitles, audio tone controls, and anti-sleep system integration.

---

## 🌟 Features

- 📡 **Automatic Channel & Scrambled Detection:** Supports full-spectrum DVB-C (Cable) and DVB-T/T2 (Terrestrial) scanning (`dvbv5-scan`) with tuner warm-up and automatic/manual scrambled channel detection (`🔑`) based on actual TS scrambling bits and SDT service types.

- 📺 **Embedded MPV Player Integration:** High-performance video and audio playback embedded into the Tkinter window via `--wid` and controlled over an IPC socket, including a custom mini-OSC overlay (subtitles, audio tracks, mute), signal info overlay, and seek/pause guards for live TV.

- 📋 **Live & Full EPG (TV Guide):** Real-time display of current and upcoming programs with progress bars and remaining time on the MPV OSD, live now/next display in the side panel, plus a dedicated EPG window with programme descriptions.

- ⏺️ **Manual & Scheduled Stream Recording:** Record live TV streams directly to `.ts` files (`~/Videos/TeleopsDVB` or custom folder) manually or schedule recordings from the EPG with pre/post margins (`±2 min`), conflict handling, and automatic channel tuning.

- 📺 **“I Want to Watch” Reminders:** Schedule automatic channel switching (`1 min` before start) from the EPG when watching another channel, respecting active or conflicting scheduled recordings.

- 💬 **DVB Subtitles & Audio Controls:** Full support for DVB subtitles, preferred audio/subtitle languages, volume/mute control, bass and treble (`±10 dB`) audio filtering, and an MPV configuration dialog (`mpv.conf` block management + config validation).

- 🖼️ **Channel Logos, Posters & Quick Jump:** Optional channel logos (via `iptv-org` & TOT country detection), movie/show posters (Apple/iTunes, IMDb, TVmaze, optional TMDB with IMDb link), Favorites (`★`), instant list search, and a `J` quick-jump overlay.

- 💤 **System & Desktop Integration:** Single-instance lock, sleep/screensaver/display inhibition (D-Bus, `systemd-inhibit`, X11), borderless/frameless mode with edge resizing and drag-to-move, left/right video panel placement, optional autoplay of the last channel, fast channel switching, and interface support for **Romanian**, **English**, and **Italian**.

---

## 🛠️ System Requirements & Dependencies

The application runs on Linux distributions (Ubuntu, Debian, Linux Mint, Arch, etc.).

Install the required dependencies on Debian/Ubuntu using:

```bash
sudo apt update
sudo apt install python3-tk mpv dvb-tools
```

*(Note: MPV installed via Flatpak `io.mpv.Mpv` is also automatically detected. No need to install mpv if you already have flatpak version. `dvb-fe-tool` from `dvb-tools` is also used when probing tuner names and supported delivery systems).*

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

*(Tip: Run with `TELEOPS_DEBUG=1 python3 teleops.py` for debug logging).*

### Option B: Using Git
```bash
git clone https://github.com/lolopoco32/TeleopsDVB.git
cd TeleopsDVB
chmod +x teleops.py
./teleops.py
```

---

## ⌨️ Keyboard shortcuts & controls
| Action | Shortcut |
|---|---|
| Play channel | `Double click` / `Enter` |
| Add / Remove Favorites | `CTRL + Left Click` |
| Show/hide search | `Right Click on list` |
| Jump to channel (quick search) | `J` |
| Previous channel | `Backspace` |
| Hide list; logo, poster | `Ctrl + H` / `Click on the title` |
| Channel info (EPG + signal) | `I` |
| TV Guide (EPG) | `CTRL + I` |
| Start/stop recording | `CTRL + R` |
| Subtitles / audio / mute | `Right click on video` |
| Volume | `Mouse wheel on video` |
| Volume / bass / treble knobs | `Drag or mouse wheel; double click = reset` |
| Mute / Unmute | `M` |
| Fullscreen | `F` / `F11` |
| Hide/show interface | `.` / `double click on video` |
| Quit program | `CTRL + SHIFT + X` |

---

## 📄 License

This project is licensed under the GNU General Public License v3.0 (GPLv3). Anyone is free to modify and redistribute this software, provided that any derivative works are also open-sourced under the same license terms.

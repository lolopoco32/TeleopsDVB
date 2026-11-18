# Teleops DVB 📺

**Teleops DVB** is a lightweight Python desktop application (built with Tkinter) designed for watching and recording DVB-C (Cable) and DVB-T/T2 (Terrestrial) TV and radio channels. It leverages `dvb-tools` (`dvbv5-scan`, `dvbv5-zap`, `dvb-fe-tool`) for tuning, scanning, and signal probing, and **MPV** (native or Flatpak `io.mpv.Mpv`) as the embedded playback engine, featuring live TV timeshift, live and full EPG (TV Guide), scheduled recordings, automatic channel switching, DVB subtitles, retro audio tone controls, dark mode, and anti-sleep system integration.

---

## 🌟 Features

- 📡 **Dedicated TV Tuner & Scrambled Detection:** Manage tuner selection, full-spectrum DVB-C (Cable) and DVB-T/T2 (Terrestrial) channel scanning (`dvbv5-scan`) with non-blocking background tuner warm-up, and automatic/manual scrambled channel detection (`🔑`) based on actual TS scrambling bits and SDT service types in a clean, dedicated **TV Tuner** window.

- 📺 **Embedded MPV Player Integration:** High-performance video and audio playback embedded into the Tkinter window via `--wid` and controlled over an IPC socket, including a custom mini-OSC overlay (subtitles, audio tracks, mute) and signal info overlay, with broad compatibility across older and newer MPV versions as well as Flatpak sandboxes.

- ⏪ **Live TV Timeshift (Pause & Rewind):** Pause live television, rewind, or fast-forward using an adjustable RAM and disk buffer (`512 MB`, `1024 MB`, or `2048 MB`, with automatic disk fallback when RAM is limited), complete with a dedicated on-screen control bar and automatic cleanup of leftover cache files.

- 📋 **Live & Full EPG (TV Guide) & Schedule Manager:** Real-time display of current and upcoming programs with progress bars and remaining time on the MPV OSD, live now/next display in the side panel, plus a dedicated EPG window featuring programme descriptions and a **"My Schedule"** tab to view, manage, or cancel all upcoming scheduled recordings and channel-switch reminders in one place.

- ⏺️ **Manual & Scheduled Stream Recording:** Record live TV streams directly to `.ts` files (`~/Videos/TeleopsDVB` or custom folder) manually or schedule recordings from the EPG with pre/post margins (`±2 min`), conflict handling, and automatic channel tuning.

- ⏰ **“I Want to Watch” Reminders:** Schedule automatic channel switching (`1 min` before start) from the EPG when watching another channel, respecting active or conflicting scheduled recordings.

- 🎛️ **DVB Subtitles, Retro Audio Controls & Expanded MPV Settings:** Full support for DVB subtitles, preferred audio/subtitle languages, mute control, rotary amplifier-style knobs for **Volume**, **Bass**, and **Treble** (`±10 dB`) audio filtering, a retro speaker grille emblem in the channel info view, and an expanded MPV configuration dialog (covering video, color, audio, subtitle, and stream options with safe `mpv.conf` updates and config validation).

- 🖼️ **Channel Logos, Posters, News Banner & Quick Surfing:** Optional channel logos (via `iptv-org` & TOT country detection, clickable in the info view to open the channel's Wikipedia page), movie/show posters (Apple/iTunes, IMDb, TVmaze, optional TMDB with clickable IMDb link), a dedicated news banner for news broadcasts, Favorites (`★`), instant list search, a `J` quick-jump overlay, and video-overlay channel zapping with a countdown banner (`Enter` to switch immediately, `Esc` to cancel).

- 🎨 **Dark Mode & Automatic Theme Switching:** Includes a sleek Dark / Slate Hi-Fi theme alongside the classic light theme, plus an **Automatic** mode that follows your desktop system theme.

- 💤 **System & Desktop Integration:** Single-instance lock, sleep/screensaver/display inhibition across desktop environments (D-Bus, `systemd-inhibit`, X11), borderless/frameless mode with edge resizing and drag-to-move, left/right video panel placement, optional autoplay of the last channel, fast non-blocking channel switching with a modular architecture, a one-click program reset option (preserving your recordings), and interface support for **Romanian**, **English**, and **Italian**.

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
| Preview / surf channels (on video) | `↑` / `↓` (`Enter` to switch immediately, `Esc` to cancel) |
| Add / Remove Favorites | `CTRL + Left Click` |
| Show/hide search | `Right Click on list` |
| Jump to channel (quick search) | `J` |
| Previous channel | `Backspace` |
| Pause / Play live TV (Timeshift) | `Space` |
| Seek 10 seconds (Timeshift) | `CTRL + ←` / `CTRL + →` |
| Jump back to live TV | `CTRL + 0` |
| Hide list; logo, poster | `Ctrl + H` / `Click on the title` |
| Channel info (EPG + signal) | `I` |
| Open channel Wikipedia page | `Click on channel logo (in info view)` |
| TV Guide (EPG) & My Schedule | `CTRL + I` |
| Start/stop recording | `CTRL + R` |
| Subtitles / audio / mute | `Right click on video` |
| Volume | `Mouse wheel` or `←` / `→` on video |
| Volume / bass / treble knobs | `Drag or mouse wheel; double click = reset` |
| Mute / Unmute | `M` |
| Fullscreen | `F` / `F11` |
| Hide/show interface | `.` / `double click on video` |
| Quit program | `CTRL + SHIFT + X` |

---

## 📄 License

This project is licensed under the GNU General Public License v3.0 (GPLv3). Anyone is free to modify and redistribute this software, provided that any derivative works are also open-sourced under the same license terms.
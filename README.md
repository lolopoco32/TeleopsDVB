# Teleops DVB 📺

**Teleops DVB** is a Python desktop application (using Tkinter) designed for watching and recording TV and Radio channels via DVB tuners (DVB-C and DVB-T/T2). The application uses `dvb-tools` for frequency tuning and `mpv` as the media player engine.

## 🌟 Features

* **Automatic Scanning:** Supports DVB-C (Cable) and DVB-T/T2 (Terrestrial) channel scanning.

* **TV Guide (EPG):** Displays current and upcoming program details (with a progress bar on the MPV OSD) + a dedicated window showing full show descriptions.

* **DVB Subtitles:** Support for full DVB stream subtitles (including external/non-embedded streams).

* **Recording:** Stream TV channels directly to `.ts` files.

* **Favorites & Search:** Easily organize channels into TV, Radio, and Favorites, with a built-in search bar.

* **Multilingual:** Includes interface support for Romanian, English, and Italian.

## 🛠️ Prerequisites & Dependencies

The application runs on Linux distributions (Ubuntu, Debian, Linux Mint, etc.).

To install the required dependencies, run the following command in your terminal:

```bash
sudo apt update
sudo apt install python3-tk mpv dvb-tools
```

*(Optional: If you use `mpv` via Flatpak, the application will automatically detect and use it).*

## 🚀 Getting Started

1. Clone or download this repository:

   ```bash
   git clone https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
   cd YOUR-REPOSITORY
   ```

2. Make the script executable:

   ```bash
   chmod +x teleops.py
   ```

3. Launch the application:

   ```bash
   ./teleops.py
   ```

   *or*

   ```bash
   python3 teleops.py
   ```

## ⌨️ Hotkeys & Shortcuts

* `CTRL + i` — Show OSD with current EPG info inside the MPV player window.

* `Right Click on list` — Toggle the search bar visibility.

* `CTRL + Left Click on channel` — Add or remove a channel from your Favorites.

* `Double Click / Enter` — Tune to the selected channel.

* `Click on title ("Teleops DVB")` — Toggle settings and tuner configuration panel.

## 📄 License

This project is licensed under the MIT License. Feel free to contribute or modify!
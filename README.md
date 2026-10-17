# Teleops DVB

**Teleops DVB** is a modern PyQt6-based application for Linux designed to scan, stream, and record DVB-C (Cable) and DVB-T/T2 (Terrestrial) digital television broadcasts using standard `dvb-tools` and `mpv`

## Key Features
* **Multi-Frontend Support:** Interfaces with DVB adapters and frontends for cable and terrestrial scanning (`dvbv5-scan`, `dvbv5-zap`)
* **Integrated Video Playback:** Streams television channels directly through a controlled `mpv` instance with high-quality video profiles and automatic DVB/Teletext subtitle selection[cite: 1].
* **Stream Recording:** Allows real-time recording of live broadcasts directly into timestamped `.ts` files inside the user's `Videos` directory
* **Multilingual Interface:** Built-in localization support for Romanian, English, and Italian[cite: 1].
* **Customizable Settings:** Preserves window geometry, volume levels, scroll positions, and provides quick access to advanced `mpv.conf` configurations

## Requirements
* Python 3 & PyQt6
* `mpv` player (or the Flatpak version `io.mpv.Mpv`)
* `dvb-tools` (`dvbv5-scan`, `dvbv5-zap`)


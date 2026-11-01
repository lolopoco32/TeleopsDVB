# Teleops DVB

**Teleops DVB** is a modern PyQt6-based application for Linux designed to scan, stream, and record DVB-C (Cable) and DVB-T/T2 (Terrestrial) digital television broadcasts using standard `dvb-tools` and `mpv`

## Key Features
* **Multi-Frontend Support:** Interfaces with DVB adapters and frontends for cable and terrestrial scanning (`dvbv5-scan`, `dvbv5-zap`)
* **Integrated Video Playback:** Streams television channels directly through a controlled `mpv` instance with high-quality video profiles and automatic DVB/Teletext subtitle selection
* **Stream Recording:** Allows real-time recording of live broadcasts directly into timestamped `.ts` files inside the user's `Videos` directory
* **Multilingual Interface:** Built-in localization support for Romanian, English, and Italian
* **Customizable Settings:** Preserves window geometry, volume levels, scroll positions, and provides quick access to advanced `mpv.conf` configurations

## Requirements
* `mpv` player (or the Flatpak version `io.mpv.Mpv`)
* `dvb-tools` (`dvbv5-scan`, `dvbv5-zap`)

<img width="450" height="1198" alt="Screenshot_20261101_070240" src="https://github.com/user-attachments/assets/ff4b3f2d-1e95-462b-a7a3-b4e427c9c6e0" />
<img width="2243" height="1083" alt="Screenshot_20261101_070422" src="https://github.com/user-attachments/assets/152aecb0-4dc4-4646-8306-78929801441e" />

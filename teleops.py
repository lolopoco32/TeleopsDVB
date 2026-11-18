#!/usr/bin/env python3
"""Teleops DVB - player TV/radio DVB: Tkinter + mpv + dvbv5-zap, cu EPG, subtitrări DVB și înregistrări programate.

Dependențe: python3-tk, mpv (sau Flatpak io.mpv.Mpv), dvb-tools (dvbv5-scan, dvbv5-zap, dvb-fe-tool).
Rulare:     python3 teleops.py          (TELEOPS_DEBUG=1 pentru mesaje de depanare)
Teste:      python3 -m unittest test_teleops -v        (fișierul test_teleops.py e opțional)

UN SINGUR FIȘIER, DAR MODULAR
Fișierul e împărțit în SECȚIUNI (marcate `# SECȚIUNE strat/nume`), grupate pe STRATURI, în ordinea de mai jos.
Regula: straturile sunt ordonate de jos în sus (config, i18n, system, core, player, ui, app), exact în ordinea din
fișier. O secțiune poate folosi doar nume din propriul strat sau din straturile LISTATE ÎNAINTEA ei; niciodată din
cele de după. `tkinter` e permis doar în straturile `ui` și `app`.
Regula e verificată automat de test_teleops.py (LayerTests), așa că structura nu se degradează pe nesimțite.

Căutare rapidă: caută "SECȚIUNE" ca să sari între secțiuni, sau numele secțiunii (ex. "SECȚIUNE core/schedule").

HARTA SECȚIUNILOR
    config   Setări: căi, settings.json, mpv.conf
             · paths: Căi și constante globale. Stratul cel mai de jos: nu importă nimic din proiect.
             · settings: Setările utilizatorului (settings.json).
             · mpv_conf: Fișierul mpv.conf: valorile implicite, blocul gestionat de program și scrierea atomică.
    i18n     Texte ale interfeței (ro / en / it)
             · strings: Textele interfeței (ro, en, it). Dialogul mpv: secțiunea i18n/strings_mpv.
             · strings_mpv: Texte pentru dialogul „Configurează MPV”. Format: cheie: (ro, en, it).
             · strings_rec: Texte pentru înregistrările programate și vizionările programate din EPG. Format: cheie: (ro, en, it).
             · strings_ext: Texte pentru Timeshift, tema ferestrei, fereastra „Tuner TV”, tastele noi și „Programările mele” din EPG. Format: cheie: (ro, en, it).
             · translate: Traduceri: `tr(lang, cheie)`.
    system   Integrare cu sistemul: mediu, X11, D-Bus, anti-sleep, editor, instanță unică
             · dbus_min: Client D-Bus minimal, fără dependențe: doar apeluri de metodă pe session bus.
             · x11: Ajutor peste libX11 prin ctypes (fără dependențe de Tk).
             · env: Mediul de execuție: variabile curate pentru procese copil, căutarea mpv și a uneltelor DVB.
             · theme: Tema sistemului (luminoasă / întunecată), pentru setarea „Automată”.
             · opener: Deschiderea unui fișier într-un editor de text.
             · single_instance: Doar o instanță a programului.
             · inhibit: Blochează suspend-ul, screensaver-ul și stingerea ecranului cât rulează programul.
    core     Logică DVB pură, fără UI: SI/EPG, canale, tunere, scanare, programări
             · dvb_si: MPEG-TS / DVB SI: filtrarea unui serviciu din transponder, EPG (EIT), SDT, text DVB.
             · dvb_tools: Capabilitățile uneltelor DVB instalate.
             · channels: Lista de canale (channels.conf) și metadatele serviciilor (services.json).
             · tuners: Detectarea tunerelor DVB.
             · scanning: Scanarea canalelor, „încălzirea” tunerului și detecția canalelor codate.
             · schedule: Programarea înregistrărilor din EPG: lista de joburi + deciziile (fără UI, fără Tk, testabil).
             · watch: „Vreau să vizionez”: comutarea automată pe canalul unei emisiuni, fără conflict cu înregistrările.
    player   mpv + dvbv5-zap: redare, script OSC, opțiuni și validare mpv
             · osc_script: Mini-OSC Lua încorporat în mpv (subtitrare / audio / mute, OSD EPG cu bară de progres, info video/audio, bara Timeshift, banner de canal, blocarea seek-ului fără Timeshift). Se scrie în CONF_DIR la fiecare pornire.
             · mpv_options: Opțiunile mpv oferite în dialogul „Configurează MPV” și transformarea lor în linii de mpv.conf.
             · mpv_check: Validarea unei configurații mpv înainte s-o salvăm: pornește scurt mpv pe o sursă de test.
             · streamer: Redarea unui canal: dvbv5-zap -> (filtru TS) -> mpv încorporat în fereastra Tk, cu control prin IPC.
    ui       Interfața Tkinter (singurul strat care folosește tkinter)
             · constants: Constante ale interfeței.
             · geometry: Geometria redimensionării unei ferestre fără bordură (funcții pure, fără Tk, ușor de testat).
             · widgets: Widgeturi Tk reutilizabile: lista de canale și tooltip.
             · window_chrome: Comportamentul ferestrei: mutare prin tragere, fără bordură/titlebar și redimensionare fără margini.
             · epg_window: Fereastra cu programul TV (EPG) al canalului curent și fila „Programările mele”.
             · mpv_dialog: Dialogul „Configurează MPV”: opțiuni alese din liste (potrivite pentru TV), plus acces la mpv.conf.
             · tuner_window: Fereastra „Tuner TV”: alegerea tunerului, scanările de canale și detectarea canalelor codate (dimensiuni fixe).
             · main_window: Fereastra principală: panou cu comenzi + zonă video (mpv încorporat), listă de canale, scanare, înregistrare.
    app      Punctul de pornire: compune totul
             · app: Punctul de pornire: verifică dependențele, pregătește configurația și rulează fereastra principală.

CUM ADAUGI...
  · o opțiune mpv în dialog: o declari în `OPTIONS` (player/mpv_options) și îi tratezi valoarea în `render_block`;
    textele (`mo_<cheie>`, `mh_<cheie>`, `mc_*`) merg în secțiunea i18n/strings_mpv.
  · un text: i18n/strings (cheie -> (ro, en, it)).
  · o decizie de programare/înregistrare: core/schedule (funcția `plan`), apoi execuția în `Main._run_job`.
  · o decizie de comutare automată („Vreau să vizionez”): core/watch (funcția `watch_plan`), apoi execuția în `Main._watch_tick`.
"""

import configparser
import ctypes
import base64
import ctypes.util
import fcntl
import difflib
import functools
import hashlib
import gzip
import json
import math
import logging
import os
import queue
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import zlib
import tkinter.font as tkfont
import unicodedata
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: config  ·  Setări: căi, settings.json, mpv.conf
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE config/paths
#   Căi și constante globale. Stratul cel mai de jos: nu importă nimic din proiect.
# ──────────────────────────────────────────────────────────────────────────────

TITLE = "Teleops DVB"
VERSION = "4.6.1"
WM_NAME, WM_CLASS = "teleops", "Teleops"   # WM_CLASS al ferestrei: GNOME/KDE îl potrivesc cu fișierul .desktop (iconiță în bara de activități)
CONF_DIR = Path.home() / ".config" / "TeleopsDVB"
CHANNELS = CONF_DIR / "channels.conf"
MPV_CONF = CONF_DIR / "mpv.conf"
MPV_CONF_BAK = CONF_DIR / "mpv.conf.bak"           # copia de siguranță de dinainte de prima modificare automată
SETTINGS = CONF_DIR / "settings.json"
SCHEDULE = CONF_DIR / "schedule.json"              # înregistrările programate din EPG
WATCH = CONF_DIR / "watch.json"                    # emisiunile marcate „Vreau să vizionez” (comutare automată)
SERVICES = CONF_DIR / "services.json"              # tip serviciu + flag 'codat' (din SDT), scris după scanare
OSC_PATH = CONF_DIR / "teleops-osc.lua"
REC_DIR = Path.home() / "Videos" / "TeleopsDVB"

PROJECT_DIR = Path(__file__).resolve().parent  # lângă teleops.py (și în bundle-ul PyInstaller)
ICON_PATH = PROJECT_DIR / "icon.png"
if not ICON_PATH.exists():
    ICON_PATH = Path("/usr/share/icons/hicolor/256x256/apps/teleops.png")


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE config/settings
#   Setările utilizatorului (settings.json).
# ──────────────────────────────────────────────────────────────────────────────

def load_settings():
    try: return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception: return {}


def save_settings(d):
    try: SETTINGS.write_text(json.dumps(d), encoding="utf-8")
    except OSError: pass


def update_settings(**changes):
    """Actualizează doar cheile date, fără să atingă restul fișierului."""
    d = load_settings()
    d.update(changes)
    save_settings(d)


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE config/mpv_conf
#   Fișierul mpv.conf: valorile implicite, blocul gestionat de program și scrierea atomică.
#
#   Programul scrie ce alegi în dialogul „Configurează MPV” într-un BLOC delimitat de markere, la
#   SFÂRȘITUL fișierului (ultima valoare câștigă în mpv, deci blocul are prioritate). Tot ce e în afara
#   blocului rămâne exact cum ai scris tu; o opțiune lăsată „Implicit” în dialog nu scrie nimic.
# ──────────────────────────────────────────────────────────────────────────────

BLOCK_BEGIN = "# >>> TELEOPS-DVB: generat de dialogul „Configurează MPV” — nu edita între markere >>>"
BLOCK_END = "# <<< TELEOPS-DVB <<<"
_BLOCK_RE = re.compile(r"^# >>> TELEOPS-DVB.*?^# <<< TELEOPS-DVB.*?$\n?", re.M | re.S)

DEFAULT_CONF = """# MPV configuration file
profile=gpu-hq
gpu-api=opengl
vo=gpu
hwdec=auto
gpu-context=auto
video-output-levels=full
target-prim=auto
target-trc=auto
scale=spline36
cscale=mitchell
dscale=mitchell
dither-depth=auto
temporal-dither=yes
keep-open=yes
cursor-autohide=1000

# Subtitrări (sid=auto și sub-visibility=yes sunt forțate și din linia de comandă)
slang=rum,ron,ro,en,it
sub-font-size=36
demuxer-lavf-probesize=10000000
demuxer-lavf-analyzeduration=10.0
demuxer-readahead-secs=5
"""


# Nume de opțiuni greșite care au circulat în versiunile vechi (mpv le respinge cu „option not found”)
RENAMED = {"demuxer-lavf-probe-size": "demuxer-lavf-probesize",
           "demuxer-readahead-seconds": "demuxer-readahead-secs"}


def fix_mpv_renamed(text):
    """Înlocuiește numele greșite cunoscute, doar la început de linie (ca opțiune, nu în comentarii)."""
    for old, new in RENAMED.items():
        text = re.sub(rf"^(\s*){re.escape(old)}(\s*=)", rf"\1{new}\2", text, flags=re.M)
    return text


def ensure_mpv_conf():
    """Creează mpv.conf cu valorile implicite dacă nu există; altfel corectează numele vechi greșite."""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    if not MPV_CONF.exists():
        MPV_CONF.write_text(DEFAULT_CONF, encoding="utf-8")
        return
    old = read_mpv_conf()
    new = fix_mpv_renamed(old)
    if new != old:
        write_mpv_conf(new)         # face și copia .bak


def read_mpv_conf():
    try: return MPV_CONF.read_text(encoding="utf-8")
    except OSError: return ""


def strip_mpv_block(text):
    return _BLOCK_RE.sub("", text)


def compose_mpv_conf(text, block_lines):
    """`text` fără vechiul bloc + blocul nou la sfârșit (sau doar `text` curățat dacă nu sunt linii)."""
    base = strip_mpv_block(text).rstrip("\n")
    if not block_lines:
        return base + "\n" if base else ""
    return (base + "\n\n" if base else "") + "\n".join([BLOCK_BEGIN, *block_lines, BLOCK_END]) + "\n"


def write_mpv_conf(text):
    """Scriere atomică (fișier temporar + replace); face o singură dată o copie .bak a originalului."""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    if MPV_CONF.exists() and not MPV_CONF_BAK.exists():
        MPV_CONF_BAK.write_bytes(MPV_CONF.read_bytes())
    tmp = MPV_CONF.with_name(MPV_CONF.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, MPV_CONF)


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: i18n  ·  Texte ale interfeței (ro / en / it)
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE i18n/strings
#   Textele interfeței (ro, en, it). Dialogul mpv: secțiunea i18n/strings_mpv.
# ──────────────────────────────────────────────────────────────────────────────

LANGS = ("Română", "English", "Italiano")
T = {  # cheie: (ro, en, it)
    "tuner_label": ("Tuner / Frontend activ:", "Active Tuner / Frontend:", "Sintonizzatore / Frontend attivo:"),
    "lang_label": ("Limbă:", "Language:", "Lingua:"),
    "scan_c": ("📡 Scanează DVB-C (Cablu)", "📡 Scan DVB-C (Cable)", "📡 Scansiona DVB-C (Cavo)"),
    "scan_t": ("🗼 Scanează DVB-T (Terestru)", "🗼 Scan DVB-T (Terrestrial)", "🗼 Scansiona DVB-T (Terrestre)"),
    "cfg_mpv": ("⚙️ Configurează MPV", "⚙️ Configure MPV", "⚙️ Configura MPV"),
    "rec_dir": ("📁 Dosar înregistrare", "📁 Recording folder", "📁 Cartella registrazione"),
    "rec_dir_title": ("Alege dosarul pentru înregistrări", "Choose the recordings folder", "Scegli la cartella delle registrazioni"),
    "search_ph": ("🔍 Caută canal...", "🔍 Search channel...", "🔍 Cerca canale..."),
    "epg_btn": ("📋 Program TV (EPG)", "📋 TV Guide (EPG)", "📋 Guida TV (EPG)"),
    "epg_wait": ("EPG: se încarcă...", "EPG: loading...", "EPG: caricamento..."),
    "epg_na": ("EPG indisponibil (dvbv5-zap fără opțiunea -P)", "EPG unavailable (dvbv5-zap lacks -P)", "EPG non disponibile (dvbv5-zap senza -P)"),
    "now": ("Acum", "Now", "Ora"),
    "next": ("Urmează", "Next", "Segue"),
    "rec_off": ("🔴 Înregistrează", "🔴 Record", "🔴 Registra"),
    "rec_on": ("⏹️ Oprește înregistrarea", "⏹️ Stop Recording", "⏹️ Ferma Registrazione"),
    "stop_play": ("✖️ Oprește redarea", "✖️ Stop Playback", "✖️ Ferma Riproduzione"),
    "scan_cancel": ("✖️ Anulează scanarea", "✖️ Cancel scan", "✖️ Annulla scansione"),
    "fav_title": ("★ FAVORITE", "★ FAVORITES", "★ PREFERITI"),
    "tv_title": ("📺 CANALE TV", "📺 TV CHANNELS", "📺 CANALI TV"),
    "radio_title": ("📻 CANALE RADIO", "📻 RADIO CHANNELS", "📻 CANALI RADIO"),
    "scan_done": ("Scanare finalizată! Găsite:", "Scan completed! Found:", "Scansione completata! Trovati:"),
    "scan_err": ("Scanare eșuată", "Scan failed", "Scansione fallita"),
    "play_err": ("Eroare redare", "Playback error", "Errore di riproduzione"),
    "no_tuner": ("Niciun tuner detectat", "No tuner detected", "Nessun sintonizzatore rilevato"),
    "refresh_tip": ("Reîmprospătează lista de tunere", "Refresh tuner list", "Aggiorna elenco sintonizzatori"),
    "tuner_crash": ("Tunerul DVB s-a blocat (Eroare 255) sau a fost deconectat. Reconectați dispozitivul USB.", "DVB tuner crashed (Error 255) or disconnected. Reconnect the USB device.", "Sintonizzatore DVB bloccato (Errore 255) o disconnesso. Ricollegare il dispositivo USB."),
    # Comenzi rapide (afișate deasupra barei de volum când setările sunt vizibile)
    "hk_title": ("⌨️ Comenzi rapide", "⌨️ Hotkeys", "⌨️ Scorciatoie"),
    "hk_search": ("Arată/ascunde căutarea", "Show/hide search", "Mostra/nascondi ricerca"),
    "hk_search_k": ("Click Dreapta pe listă", "Right Click on list", "Clic destro sulla lista"),
    "hk_epg": ("Informații canal", "Channel info", "Info canale"),
    "hk_epg_k": ("I", "I", "I"),
    "hk_epgwin": ("Program TV (EPG)", "TV Guide (EPG)", "Guida TV (EPG)"),
    "hk_epgwin_k": ("CTRL + I", "CTRL + I", "CTRL + I"),
    "hk_fav": ("Adaugă / Elimină din Favorite", "Add / Remove Favorites", "Aggiungi / Rimuovi Preferiti"),
    "hk_fav_k": ("CTRL + Click Stânga", "CTRL + Left Click", "CTRL + Clic sinistro"),
    "hk_play": ("Redă canalul", "Play channel", "Riproduci il canale"),
    "hk_play_k": ("Dublu click / Enter", "Double click / Enter", "Doppio clic / Invio"),
    "hk_ui": ("Ascunde/arată interfața", "Hide/show interface", "Nascondi/mostra interfaccia"),
    "hk_ui_k": (". / dublu click pe video", ". / double click on video", ". / doppio clic sul video"),
    "hk_fs": ("Ecran complet", "Fullscreen", "Schermo intero"),
    "hk_fs_k": ("F / F11", "F / F11", "F / F11"),
    "hk_rec": ("Pornește/oprește înregistrarea", "Start/stop recording", "Avvia/ferma la registrazione"),
    "hk_rec_k": ("CTRL + R", "CTRL + R", "CTRL + R"),
    "hk_osc": ("Subtitrare / audio / mute", "Subtitles / audio / mute", "Sottotitoli / audio / muto"),
    "hk_vol": ("Volum", "Volume", "Volume"),
    "hk_vol_k": ("Rotiță mouse pe video", "Mouse wheel on video", "Rotellina del mouse sul video"),
    "hk_mute": ("Mute / Unmute", "Mute / Unmute", "Mute / Unmute"),
    "hk_mute_k": ("M", "M", "M"),
    "hk_osc_k": ("Click dreapta pe video", "Right click on video", "Clic destro sul video"),
    "hk_prev": ("Canalul anterior", "Previous channel", "Canale precedente"),
    "hk_prev_k": ("Backspace", "Backspace", "Backspace"),
    "hk_jump": ("Salt la canal (căutare rapidă)", "Jump to channel (quick search)", "Vai al canale (ricerca rapida)"),
    "hk_jump_k": ("J", "J", "J"),
    "hk_knob": ("Volum / joase / înalte", "Volume / bass / treble", "Volume / bassi / acuti"),
    "hk_knob_k": ("Trage sau rotiță mouse; dublu click = resetare", "Drag or mouse wheel; double click = reset",
                  "Trascina o rotellina; doppio clic = reset"),
    "knob_bass": ("Joase", "Bass", "Bassi"),
    "knob_treble": ("Înalte", "Treble", "Acuti"),
    "jump_title": ("Salt la canal", "Jump to channel", "Vai al canale"),
    "jump_none": ("Niciun canal găsit", "No channel found", "Nessun canale trovato"),
    "prev_none": ("Niciun canal anterior", "No previous channel", "Nessun canale precedente"),
    "about_close": ("Închide", "Close", "Chiudi"),
    "hk_info": ("Ascunde lista; logo, poster, difuzor", "Hide list; logo, poster, speaker", "Nascondi elenco; logo, poster, altoparlante"),
    "hk_info_k": ("Ctrl+H sau click pe titlu", "Ctrl+H or click on the title", "Ctrl+H o clic sul titolo"),
    "poster_none": ("Fără poster", "No poster", "Nessun poster"),
    "autoplay_last": ("Redă ultimul canal la pornire", "Play last channel at startup", "Riproduci l'ultimo canale all'avvio"),
    "show_media": ("Logo canal și poster film (imprecis)", "Channel logo and movie poster (imprecise)", "Logo canale e locandina film (impreciso)"),
    "fast_switch": ("Schimbare rapidă a canalelor", "Fast channel switching", "Cambio canale rapido"),
    "fast_tip": ("Imaginea și sunetul apar cât mai repede: fluxul se analizează mai puțin la pornire, iar oprirea "
                 "canalului vechi nu mai blochează fereastra. Calitatea video/audio nu se schimbă; subtitrările și "
                 "pistele audio suplimentare pot apărea cu o mică întârziere. Înlocuiește „Analiză flux” din Configurează MPV.",
                 "Picture and sound appear as fast as possible: the stream is analysed less at start-up and stopping "
                 "the old channel no longer blocks the window. Video/audio quality is unchanged; subtitles and extra "
                 "audio tracks may show up a little later. Overrides “Stream analysis” from Configure MPV.",
                 "Immagine e audio compaiono il più rapidamente possibile: il flusso viene analizzato meno all'avvio e "
                 "l'arresto del canale precedente non blocca più la finestra. La qualità video/audio non cambia; "
                 "sottotitoli e tracce audio extra possono comparire con un lieve ritardo. Sostituisce «Analisi flusso» di Configura MPV."),
    "hk_quit": ("Închide programul", "Quit program", "Chiudi il programma"),
    "hk_quit_k": ("CTRL + SHIFT + X", "CTRL + SHIFT + X", "CTRL + SHIFT + X"),
    # „Despre” (fereastră separată, nerdimensionabilă, deschisă din butonul din setări)
    "about_btn": ("Despre Teleops DVB", "About Teleops DVB", "Informazioni su Teleops DVB"),
    "about_title": ("Teleops DVB, versiunea {v}", "Teleops DVB, version {v}", "Teleops DVB, versione {v}"),
    "about_desc": (
        "Un player TV/radio DVB (TV Tuner Player) construit în Python Tk, cu EPG, subtitrări DVB și înregistrări programate. "
        "Folosește dvbv5-scan, dvbv5-zap și dvb-fe-tool din pachetul dvb-tools pentru scanarea canalelor și recepție, "
        "iar mpv pentru redarea video și audio.",
        "A DVB TV/radio player (TV Tuner Player) built with Python Tk, with EPG, DVB subtitles and scheduled recordings. "
        "It uses dvbv5-scan, dvbv5-zap and dvb-fe-tool from the dvb-tools package for channel scanning and reception, "
        "and mpv for video and audio playback.",
        "Un player TV/radio DVB (TV Tuner Player) realizzato con Python Tk, con EPG, sottotitoli DVB e registrazioni programmate. "
        "Usa dvbv5-scan, dvbv5-zap e dvb-fe-tool del pacchetto dvb-tools per la scansione dei canali e la ricezione, "
        "e mpv per la riproduzione video e audio."),
    "about_tab_prog": ("Despre program", "About", "Informazioni"),
    "about_tab_keys": ("Comenzi rapide", "Hotkeys", "Scorciatoie"),
    "about_version": ("Versiunea {v}", "Version {v}", "Versione {v}"),
    "about_services": ("Serviciile online folosite:", "Online services used:", "Servizi online utilizzati:"),
    "about_services_list": (
        "• iptv-org (iptv-org.github.io): baza de canale și logo-uri\n"
        "• Wikimedia Commons, Imgur ș.a.: găzduirea imaginilor de logo indicate de iptv-org\n"
        "• IMDb: postere filme și seriale\n"
        "• Apple iTunes Search: postere filme și seriale\n"
        "• TVmaze: afișe seriale și emisiuni\n"
        "• TMDB (opțional, cu cheie proprie): postere, în limba țării alese",
        "• iptv-org (iptv-org.github.io): channel and logo database\n"
        "• Wikimedia Commons, Imgur etc.: hosting of the logo images listed by iptv-org\n"
        "• IMDb: movie and series posters\n"
        "• Apple iTunes Search: movie and series posters\n"
        "• TVmaze: series and show artwork\n"
        "• TMDB (optional, with your own key): posters, in the chosen country's language",
        "• iptv-org (iptv-org.github.io): database di canali e logo\n"
        "• Wikimedia Commons, Imgur ecc.: hosting dei loghi indicati da iptv-org\n"
        "• IMDb: locandine di film e serie\n"
        "• Apple iTunes Search: locandine di film e serie\n"
        "• TVmaze: immagini di serie e programmi\n"
        "• TMDB (facoltativo, con chiave propria): locandine, nella lingua del paese scelto"),
    "about_dev": (
        "Dezvoltat de Valentin Iacob, turock_valentin@gmail.com",
        "Developed by Valentin Iacob, turock_valentin@gmail.com",
        "Sviluppato da Valentin Iacob, turock_valentin@gmail.com"),
    "loading": ("Se încarcă...", "Loading...", "Caricamento..."),
    "osc_sub": ("Subtitrare", "Subtitles", "Sottotitoli"),
    "osc_audio": ("Coloană sonoră", "Audio track", "Traccia audio"),
    "osc_off": ("Dezactivat", "Off", "Disattivato"),
    "quit_app": ("⏻ Închide programul", "⏻ Quit program", "⏻ Chiudi il programma"),
    "borderless": ("Fără margini și bară de titlu", "No window borders / titlebar", "Senza bordi e barra del titolo"),
    "x11_na": ("Funcția cere X11/XWayland (libX11 indisponibil).", "This needs X11/XWayland (libX11 unavailable).", "Richiede X11/XWayland (libX11 non disponibile)."),
    "side_btn": ("⇄ Mută panoul GUI", "⇄ Move GUI panel", "⇄ Sposta pannello GUI"),
    # Localizare OSD MPV
    "osd_loading": ("Se încarcă EPG...", "Loading EPG...", "Caricamento EPG..."),
    "osd_na": ("Indisponibil", "Unavailable", "Non disponibile"),
    # Informații video/audio afișate de mpv la pornirea canalului (stânga jos)
    "info_video": ("Video", "Video", "Video"),
    "info_audio": ("Audio", "Audio", "Audio"),
    "info_wait": ("se detectează...", "detecting...", "rilevamento..."),
    "info_noaud": ("fără audio", "no audio", "nessun audio"),
    "scrambled": ("Canal codat (criptat): nu poate fi redat fără card/CAM.", "Scrambled (encrypted) channel: it can't be played without a card/CAM.", "Canale criptato: non riproducibile senza card/CAM."),
    "chlist_btn": ("📺 Lista Canale TV", "📺 TV Channel List", "📺 Elenco canali TV"),
    "cfg_tip": ("Setări", "Settings", "Impostazioni"),
    "country_label": ("Țara (logo și poster)", "Country (logo & poster)", "Paese (logo e poster)"),
    "country_auto": ("Automat", "Automatic", "Automatico"),
    "country_tip": ("Țara al cărei conținut e căutat primul pentru logo-uri și postere (limba titlurilor, magazinul de filme, \n"
                    "programul TV). „Automat” = țara citită din semnal (TOT) sau din sistem.",
                    "Country searched first for logos and posters (title language, movie store, TV schedule). \n"
                    "“Automatic” = country read from the signal (TOT) or the system.",
                    "Paese cercato per primo per logo e poster (lingua dei titoli, store dei film, palinsesto TV). \n"
                    "«Automatico» = paese letto dal segnale (TOT) o dal sistema."),
    "news_lines": ("BREAKING NEWS\nTotul va fi bine!",
                   "BREAKING NEWS\nEverything will be fine!",
                   "ULTIM'ORA\nAndrà tutto bene!"),
    "reset_btn": ("🧹 Resetare program", "🧹 Reset program", "🧹 Ripristina programma"),
    "reset_tip": ("Șterge tot ce a salvat programul: lista de canale, setările, configurația MPV, programările, cache-ul și "
                  "jurnalele. Programul revine la starea de după instalare și se închide. Înregistrările video NU se șterg.",
                  "Deletes everything the program saved: channel list, settings, MPV configuration, schedules, cache and "
                  "logs. The program returns to its freshly installed state and closes. Video recordings are NOT deleted.",
                  "Elimina tutto ciò che il programma ha salvato: elenco canali, impostazioni, configurazione MPV, "
                  "programmazioni, cache e log. Il programma torna allo stato iniziale e si chiude. Le registrazioni NON vengono eliminate."),
    "reset_confirm": ("Sigur vrei să resetezi programul?\n\nSe șterg lista de canale, setările, configurația MPV, "
                      "programările, cache-ul și jurnalele. Înregistrările video rămân.\nProgramul se va închide.",
                      "Are you sure you want to reset the program?\n\nThe channel list, settings, MPV configuration, "
                      "schedules, cache and logs will be deleted. Video recordings are kept.\nThe program will close.",
                      "Vuoi davvero ripristinare il programma?\n\nVerranno eliminati elenco canali, impostazioni, configurazione MPV, "
                      "programmazioni, cache e log. Le registrazioni restano.\nIl programma si chiuderà."),
    "reset_done": ("Resetare finalizată. Pornește din nou programul.", "Reset finished. Start the program again.",
                   "Ripristino completato. Avvia di nuovo il programma."),
    "ca_btn": ("🔑 Detectează canalele codate", "🔑 Detect scrambled channels", "🔑 Rileva canali criptati"),
    "ca_done": ("Detecție finalizată! Canale codate:", "Detection finished! Scrambled channels:", "Rilevamento completato! Canali criptati:"),
    "already": ("Teleops DVB rulează deja.", "Teleops DVB is already running.", "Teleops DVB è già in esecuzione."),
    "osd_rem": ("Rămas", "Left", "Rimasti"),
    "osd_volume": ("Volum", "Volume", "Volume"),
    "osd_mute_on": ("Mute: Pornit", "Mute: On", "Mute: Attivo"),
    "osd_mute_off": ("Mute: Oprit", "Mute: Off", "Mute: Disattivo"),
    "epg_date": ("Dată", "Date", "Data"),
    "epg_time": ("Oră", "Time", "Ora"),
    "epg_title": ("Emisiune / Film", "Show / Movie", "Programma / Film"),
    "epg_desc": ("Descriere detaliată", "Detailed description", "Descrizione dettagliata"),
    "epg_nodesc": ("Fără descriere disponibilă.", "No description available.", "Nessuna descrizione disponibile."),
    "epg_none": ("Niciun program disponibil.", "No program available.", "Nessun programma disponibile."),
}


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE i18n/strings_mpv
#   Texte pentru dialogul „Configurează MPV”. Format: cheie: (ro, en, it).
#   Chei: mo_<opțiune> = etichetă, mh_<opțiune> = indiciu (tooltip), mc_* = alegeri traduse.
# ──────────────────────────────────────────────────────────────────────────────

MPV_T = {
    "mo_title": ("Configurare MPV", "MPV settings", "Impostazioni MPV"),
    "mo_tab_video": ("Video", "Video", "Video"),
    "mo_tab_color": ("Culori", "Colors", "Colori"),
    "mo_tab_audio": ("Audio", "Audio", "Audio"),
    "mo_tab_stream": ("Flux și cache", "Stream & cache", "Flusso e cache"),
    "mo_tab_sub": ("Subtitrări", "Subtitles", "Sottotitoli"),
    "mo_tab_advanced": ("Avansat", "Advanced", "Avanzate"),
    "mo_reset_one": ("Revino la implicit", "Back to default", "Torna al predefinito"),
    "mo_note": ("Opțiunile marcate „Implicit” nu modifică nimic: rămâne valoarea din mpv.conf. Ce alegi aici se scrie într-un bloc la sfârșitul fișierului și are prioritate. Se aplică prin repornirea canalului curent.",
                "Options set to “Default” change nothing: the value from mpv.conf stays. Your choices are written in a block at the end of the file and take priority. They apply by restarting the current channel.",
                "Le opzioni su «Predefinito» non cambiano nulla: resta il valore di mpv.conf. Le scelte vengono scritte in un blocco in fondo al file e hanno priorità. Si applicano riavviando il canale corrente."),
    "mo_open_conf": ("📝 Deschide mpv.conf", "📝 Open mpv.conf", "📝 Apri mpv.conf"),
    "mo_recommended": ("★ Recomandat pentru TV", "★ Recommended for TV", "★ Consigliato per la TV"),
    "mo_reset": ("↺ Resetează tot", "↺ Reset all", "↺ Ripristina tutto"),
    "mo_save": ("Salvează", "Save", "Salva"),
    "mo_cancel": ("Anulează", "Cancel", "Annulla"),
    "mo_checking": ("Se verifică configurația cu mpv...", "Checking the settings with mpv...", "Verifica delle impostazioni con mpv..."),
    "mo_invalid": ("mpv a respins configurația:\n\n{err}\n\nSalvezi oricum?", "mpv rejected the settings:\n\n{err}\n\nSave anyway?", "mpv ha rifiutato le impostazioni:\n\n{err}\n\nSalvare comunque?"),
    "mo_unchecked": ("Configurația nu a putut fi verificată ({err}).\n\nSalvezi oricum?", "The settings could not be checked ({err}).\n\nSave anyway?", "Impossibile verificare le impostazioni ({err}).\n\nSalvare comunque?"),
    "mo_write_err": ("Nu s-a putut scrie mpv.conf", "Could not write mpv.conf", "Impossibile scrivere mpv.conf"),
    "mo_no_editor": ("Fișierul există la:\n{path}\n\nNu s-a găsit niciun editor de text.", "The file is at:\n{path}\n\nNo text editor was found.", "Il file si trova in:\n{path}\n\nNessun editor di testo trovato."),

    "mc_default": ("Implicit (nu modifica)", "Default (don't change)", "Predefinito (non modificare)"),
    "mc_default_short": ("implicit", "default", "predefinito"),
    "mc_yes": ("Da", "Yes", "Sì"),
    "mc_no": ("Nu", "No", "No"),
    "mc_prof_fast": ("fast (PC slab)", "fast (weak PC)", "fast (PC debole)"),
    "mc_prof_hq": ("gpu-hq (calitate maximă)", "gpu-hq (best quality)", "gpu-hq (qualità massima)"),
    "mc_hw_no": ("no (doar procesor)", "no (CPU only)", "no (solo CPU)"),
    "mc_dm_off": ("Oprit", "Off", "Disattivato"),
    "mc_dm_interlaced": ("Automat – doar cadrele interlaced", "Auto – interlaced frames only", "Auto – solo fotogrammi interlacciati"),
    "mc_dm_all": ("Forțat – toate cadrele", "Forced – all frames", "Forzato – tutti i fotogrammi"),
    "mc_dmt_mpv": ("mpv automat (hardware dacă se poate)", "mpv automatic (hardware if possible)", "mpv automatico (hardware se possibile)"),
    "mc_dr_frame": ("Rată păstrată (25/30 fps)", "Keep frame rate (25/30 fps)", "Frequenza invariata (25/30 fps)"),
    "mc_dr_field": ("Rată dublată (50/60 fps, mișcare fluidă)", "Double rate (50/60 fps, smoother)", "Frequenza doppia (50/60 fps, più fluido)"),
    "mc_sm_off": ("Oprită (sincron cu sunetul)", "Off (sync to audio)", "Disattivata (sincro con audio)"),
    "mc_sm_on": ("Interpolare cadre (mișcare fluidă)", "Frame interpolation (smooth motion)", "Interpolazione (movimento fluido)"),
    "mc_pr_fast": ("Rapid (schimbare rapidă de canal)", "Fast (quick channel change)", "Veloce (cambio canale rapido)"),
    "mc_pr_bal": ("Echilibrat", "Balanced", "Bilanciato"),
    "mc_pr_full": ("Complet (recomandat: subtitrări DVB)", "Full (recommended: DVB subtitles)", "Completo (consigliato: sottotitoli DVB)"),

    "mo_profile": ("Profil de calitate", "Quality profile", "Profilo di qualità"),
    "mh_profile": ("„fast” cere puțin de la placa video (PC-uri slabe); „gpu-hq” dă cea mai bună imagine, dar încarcă GPU-ul.",
                   "“fast” is light on the GPU (weak PCs); “gpu-hq” gives the best picture but loads the GPU.",
                   "«fast» pesa poco sulla GPU (PC deboli); «gpu-hq» dà l'immagine migliore ma carica la GPU."),
    "mo_hwdec": ("Decodare hardware", "Hardware decoding", "Decodifica hardware"),
    "mh_hwdec": ("Recomandat: auto-safe. vaapi = Intel/AMD, nvdec = NVIDIA. Variantele „-copy” sunt mai compatibile cu filtrele software (bwdif/yadif).",
                 "Recommended: auto-safe. vaapi = Intel/AMD, nvdec = NVIDIA. The “-copy” variants work better with software filters (bwdif/yadif).",
                 "Consigliato: auto-safe. vaapi = Intel/AMD, nvdec = NVIDIA. Le varianti «-copy» funzionano meglio con i filtri software (bwdif/yadif)."),
    "mo_deint_mode": ("Deinterlace", "Deinterlace", "Deinterlacciamento"),
    "mh_deint_mode": ("Multe canale (mai ales HD 1080i) sunt interlaced; fără deinterlace apar „dinți” la mișcare. „Automat” atinge doar cadrele marcate interlaced, deci e sigur și pe canalele progresive.",
                      "Many channels (especially 1080i HD) are interlaced; without deinterlacing you get combing on motion. “Auto” only touches frames flagged interlaced, so it is safe on progressive channels too.",
                      "Molti canali (soprattutto HD 1080i) sono interlacciati; senza deinterlacciamento compaiono i «denti» nel movimento. «Auto» tocca solo i fotogrammi marcati interlacciati, quindi è sicuro anche sui canali progressivi."),
    "mo_deint_method": ("Metodă deinterlace", "Deinterlace method", "Metodo di deinterlacciamento"),
    "mh_deint_method": ("mpv automat folosește hardware (VAAPI etc.) când poate, altfel yadif. bwdif (CPU) are calitate mai bună decât yadif, la cost similar.",
                        "mpv automatic uses hardware (VAAPI etc.) when possible, otherwise yadif. bwdif (CPU) has better quality than yadif at a similar cost.",
                        "mpv automatico usa l'hardware (VAAPI ecc.) quando può, altrimenti yadif. bwdif (CPU) ha qualità migliore di yadif a costo simile."),
    "mo_deint_rate": ("Rata cadrelor (bwdif/yadif)", "Frame rate (bwdif/yadif)", "Frequenza (bwdif/yadif)"),
    "mh_deint_rate": ("Rată dublată (50/60 fps) dă mișcare mai fluidă la sport, dar cere mai mult procesor și un ecran la 50/60 Hz.",
                      "Double rate (50/60 fps) gives smoother motion for sports but needs more CPU and a 50/60 Hz display.",
                      "La frequenza doppia (50/60 fps) dà movimento più fluido per lo sport ma richiede più CPU e uno schermo a 50/60 Hz."),
    "mo_scale": ("Scalare imagine (mărire)", "Upscaling", "Scalatura (ingrandimento)"),
    "mh_scale": ("Algoritmul de mărire a imaginii SD/HD pe ecran. bilinear = rapid, spline36 = echilibrat, ewa_lanczossharp = cel mai clar.",
                 "Algorithm used to enlarge SD/HD pictures. bilinear = fast, spline36 = balanced, ewa_lanczossharp = sharpest.",
                 "Algoritmo per ingrandire l'immagine SD/HD. bilinear = veloce, spline36 = bilanciato, ewa_lanczossharp = più nitido."),
    "mo_smooth": ("Fluiditate mișcare", "Motion smoothness", "Fluidità del movimento"),
    "mh_smooth": ("Interpolarea reduce sacadarea la 25 fps pe ecrane de 60 Hz, dar cere mai multă putere de calcul.",
                  "Interpolation reduces judder of 25 fps content on 60 Hz displays, but needs more processing power.",
                  "L'interpolazione riduce lo scatto dei 25 fps su schermi a 60 Hz, ma richiede più potenza."),

    "mo_levels": ("Interval negru–alb", "Black–white range", "Intervallo nero–bianco"),
    "mh_levels": ("Dacă negrul pare cenușiu sau albul „ars”, încearcă alt interval. Pe monitoare PC de obicei „auto” sau „full”; pe TV prin HDMI uneori „limited”.",
                  "If blacks look grey or whites clipped, try another range. PC monitors usually want “auto” or “full”; TVs over HDMI sometimes “limited”.",
                  "Se i neri sembrano grigi o i bianchi bruciati, prova un altro intervallo. Monitor PC: «auto» o «full»; TV via HDMI a volte «limited»."),
    "mo_trc": ("Gamma ecran", "Display gamma", "Gamma dello schermo"),
    "mh_trc": ("Curba de luminozitate a ecranului. bt.1886 = TV, srgb / gamma2.2 = monitoare PC.",
               "The display's brightness curve. bt.1886 = TV, srgb / gamma2.2 = PC monitors.",
               "La curva di luminosità dello schermo. bt.1886 = TV, srgb / gamma2.2 = monitor PC."),
    "mo_prim": ("Gamut culori (primare)", "Color gamut (primaries)", "Gamut colori (primari)"),
    "mo_brightness": ("Luminozitate", "Brightness", "Luminosità"),
    "mo_contrast": ("Contrast", "Contrast", "Contrasto"),
    "mo_saturation": ("Saturație", "Saturation", "Saturazione"),
    "mo_gamma": ("Gamma (corecție)", "Gamma (correction)", "Gamma (correzione)"),
    "mo_hue": ("Nuanță", "Hue", "Tonalità"),

    "mo_audio_channels": ("Canale audio", "Audio channels", "Canali audio"),
    "mh_audio_channels": ("Dacă ai doar boxe stereo și canalele cu sunet 5.1 (AC3) sună încet sau lipsesc voci, alege „stereo”.",
                          "If you only have stereo speakers and 5.1 (AC3) channels sound quiet or lack dialogue, choose “stereo”.",
                          "Se hai solo casse stereo e i canali 5.1 (AC3) suonano deboli o senza dialoghi, scegli «stereo»."),
    "mo_downmix_norm": ("Normalizează volumul la mixarea în stereo", "Normalize volume when downmixing", "Normalizza il volume nel downmix"),
    "mo_audio_delay": ("Decalaj audio", "Audio delay", "Ritardo audio"),
    "mh_audio_delay": ("Corectează sunetul care nu se potrivește cu buzele. Valoare pozitivă = sunetul întârzie, negativă = sunetul vine mai devreme.",
                       "Fixes lip-sync. Positive = audio later, negative = audio earlier.",
                       "Corregge la sincronia labiale. Positivo = audio in ritardo, negativo = audio in anticipo."),
    "mo_alang": ("Limbi audio preferate", "Preferred audio languages", "Lingue audio preferite"),
    "mh_alang": ("Coduri de limbă separate prin virgulă, în ordinea preferinței. Ex.: ron,en", "Comma-separated language codes in order of preference. E.g.: ron,en", "Codici lingua separati da virgola, in ordine di preferenza. Es.: ron,en"),

    "mo_probe": ("Analiză flux la pornire", "Stream analysis on start", "Analisi del flusso all'avvio"),
    "mh_probe": ("Cu cât analizează mai mult, cu atât mai sigur apar subtitrările DVB și toate pistele audio, dar canalul pornește mai încet.",
                 "The longer it analyzes, the more reliably DVB subtitles and all audio tracks appear, but the channel starts slower.",
                 "Più analizza, più affidabili compaiono i sottotitoli DVB e tutte le tracce audio, ma il canale parte più lentamente."),
    "mo_slang": ("Limbi subtitrare preferate", "Preferred subtitle languages", "Lingue sottotitoli preferite"),
    "mh_slang": ("Coduri de limbă separate prin virgulă. Ex.: rum,ron,ro,en", "Comma-separated language codes. E.g.: rum,ron,ro,en", "Codici lingua separati da virgola. Es.: rum,ron,ro,en"),
    "mo_sub_size": ("Mărime subtitrare", "Subtitle size", "Dimensione sottotitoli"),

    # ---- alegeri noi
    "mc_par_tff": ("tff (primul câmpul de sus)", "tff (top field first)", "tff (prima il campo superiore)"),
    "mc_par_bff": ("bff (primul câmpul de jos)", "bff (bottom field first)", "bff (prima il campo inferiore)"),
    "mc_dyn_norm": ("Normalizare dinamică (volum egal între scene)", "Dynamic normalizer (even volume between scenes)", "Normalizzazione dinamica (volume uniforme tra le scene)"),
    "mc_dyn_comp": ("Compresor (dialog mai clar, explozii mai blânde)", "Compressor (clearer dialogue, softer explosions)", "Compressore (dialoghi più chiari, esplosioni più morbide)"),
    "mc_col_white": ("Alb", "White", "Bianco"),
    "mc_col_yellow": ("Galben", "Yellow", "Giallo"),
    "mc_col_cyan": ("Cyan", "Cyan", "Ciano"),
    "mc_col_green": ("Verde", "Green", "Verde"),
    "mc_never": ("Niciodată", "Never", "Mai"),
    "mc_always": ("Mereu", "Always", "Sempre"),

    # ---- Video (nou)
    "mo_deint_parity": ("Ordinea câmpurilor (bwdif/yadif)", "Field order (bwdif/yadif)", "Ordine dei campi (bwdif/yadif)"),
    "mh_deint_parity": ("„auto” e corect aproape mereu. Schimbă-l doar dacă mișcarea pare să sară înapoi: pe TV-ul european e de obicei tff.",
                        "“auto” is right almost always. Change it only if motion seems to jump backwards: European TV is usually tff.",
                        "«auto» è giusto quasi sempre. Cambialo solo se il movimento sembra tornare indietro: la TV europea è di solito tff."),
    "mo_cscale": ("Scalare crominanță", "Chroma scaling", "Scalatura crominanza"),
    "mh_cscale": ("Algoritmul pentru culorile imaginii (rezoluție mai mică decât luminanța). spline36 e un compromis bun.",
                  "Algorithm for the picture's color channels (lower resolution than luma). spline36 is a good compromise.",
                  "Algoritmo per i canali colore (risoluzione inferiore alla luminanza). spline36 è un buon compromesso."),
    "mo_dscale": ("Scalare la micșorare", "Downscaling", "Scalatura in riduzione"),
    "mh_dscale": ("Folosit când imaginea e mai mare decât fereastra (ex. HD într-o fereastră mică). mitchell e rapid și curat.",
                  "Used when the picture is larger than the window (e.g. HD in a small window). mitchell is fast and clean.",
                  "Usato quando l'immagine è più grande della finestra (es. HD in una finestra piccola). mitchell è veloce e pulito."),
    "mo_deband": ("Reducere benzi de culoare (deband)", "Banding reduction (deband)", "Riduzione del banding (deband)"),
    "mh_deband": ("Netezește degradeurile cu „trepte” vizibile din canalele cu bitrate mic. Costă puțin GPU.",
                  "Smooths visible color “steps” in gradients on low-bitrate channels. Costs a little GPU.",
                  "Leviga i «gradini» visibili nelle sfumature dei canali a basso bitrate. Costa poco GPU."),
    "mo_aspect": ("Forțează raportul de aspect", "Force aspect ratio", "Forza il rapporto d'aspetto"),
    "mh_aspect": ("Util când un canal e marcat greșit și imaginea apare întinsă sau turtită. Implicit = cel din flux.",
                  "Useful when a channel is flagged wrongly and the picture looks stretched or squashed. Default = the one in the stream.",
                  "Utile quando un canale è marcato male e l'immagine appare allungata o schiacciata. Predefinito = quello del flusso."),
    "mo_panscan": ("Umple ecranul (taie marginile)", "Fill the screen (crop edges)", "Riempi lo schermo (taglia i bordi)"),
    "mh_panscan": ("0% = benzi negre, 100% = imaginea umple toată fereastra, cu marginile tăiate.",
                   "0% = black bars, 100% = the picture fills the whole window with the edges cropped.",
                   "0% = bande nere, 100% = l'immagine riempie tutta la finestra con i bordi tagliati."),

    # ---- Culori (nou)
    "mo_tone_mapping": ("Tone mapping (HDR)", "Tone mapping (HDR)", "Tone mapping (HDR)"),
    "mh_tone_mapping": ("Contează doar la canalele HDR (rare). bt.2390 e o alegere bună.",
                        "Only matters for HDR channels (rare). bt.2390 is a good choice.",
                        "Conta solo per i canali HDR (rari). bt.2390 è una buona scelta."),
    "mo_hdr_peak": ("Detectare automată vârf HDR", "Automatic HDR peak detection", "Rilevamento automatico del picco HDR"),
    "mo_icc_auto": ("Profil ICC al monitorului", "Monitor ICC profile", "Profilo ICC del monitor"),
    "mh_icc_auto": ("Aplică profilul de culoare al monitorului, dacă sistemul îl are. Poate schimba ușor culorile.",
                    "Applies the monitor's color profile if the system has one. May change colors slightly.",
                    "Applica il profilo colore del monitor, se il sistema ne ha uno. Può cambiare leggermente i colori."),

    # ---- Audio (nou)
    "mo_audio_dyn": ("Egalizare volum (mod noapte)", "Volume leveling (night mode)", "Livellamento volume (modo notte)"),
    "mh_audio_dyn": ("Reduce diferența dintre scenele liniștite și cele tari, și dintre reclame și film.",
                     "Reduces the gap between quiet and loud scenes, and between ads and the programme.",
                     "Riduce il divario tra scene silenziose e rumorose, e tra pubblicità e programma."),
    "mo_volume_max": ("Volum maxim", "Maximum volume", "Volume massimo"),
    "mh_volume_max": ("Peste 100% sunetul se amplifică digital (poate distorsiona). Slider-ul de volum din program se ajustează singur.",
                      "Above 100% the sound is digitally amplified (may distort). The program's volume slider adjusts itself.",
                      "Oltre il 100% il suono è amplificato digitalmente (può distorcere). Il cursore del volume del programma si adegua."),
    "mo_ao": ("Driver audio", "Audio driver", "Driver audio"),
    "mh_ao": ("Lasă „Implicit” dacă sunetul merge. pipewire/pulse pentru desktop modern, alsa pentru acces direct.",
              "Leave “Default” if the sound works. pipewire/pulse for modern desktops, alsa for direct access.",
              "Lascia «Predefinito» se l'audio funziona. pipewire/pulse per desktop moderni, alsa per accesso diretto."),
    "mo_audio_device": ("Dispozitiv audio", "Audio device", "Dispositivo audio"),
    "mh_audio_device": ("Ex.: pulse/nume_dispozitiv sau alsa/hdmi. Lista o vezi cu: mpv --audio-device=help",
                        "E.g.: pulse/device_name or alsa/hdmi. See the list with: mpv --audio-device=help",
                        "Es.: pulse/nome_dispositivo o alsa/hdmi. Vedi l'elenco con: mpv --audio-device=help"),
    "mo_spdif": ("Trecere directă digitală (S/PDIF/HDMI)", "Digital passthrough (S/PDIF/HDMI)", "Passthrough digitale (S/PDIF/HDMI)"),
    "mh_spdif": ("Trimite sunetul AC3/DTS nedecodat către un receiver AV. Folosește doar dacă ai așa ceva conectat.",
                 "Sends AC3/DTS sound undecoded to an AV receiver. Use only if you have one connected.",
                 "Invia l'audio AC3/DTS non decodificato a un ricevitore AV. Usalo solo se ne hai uno collegato."),
    "mo_audio_samplerate": ("Frecvență de eșantionare", "Sample rate", "Frequenza di campionamento"),
    "mh_audio_samplerate": ("Sunetul DVB e de obicei 48 kHz; fixarea ei poate evita rezampling-ul.",
                            "DVB audio is usually 48 kHz; fixing it can avoid resampling.",
                            "L'audio DVB è di solito a 48 kHz; fissarla può evitare il ricampionamento."),

    # ---- Subtitrări
    "mo_sub_color": ("Culoare subtitrare", "Subtitle color", "Colore dei sottotitoli"),
    "mo_sub_border": ("Grosime contur subtitrare", "Subtitle outline width", "Spessore contorno sottotitoli"),
    "mh_sub_border": ("Conturul negru ajută la citire pe fundaluri deschise.", "The black outline helps readability on bright backgrounds.", "Il contorno nero aiuta la lettura su sfondi chiari."),
    "mo_sub_bold": ("Subtitrare îngroșată", "Bold subtitles", "Sottotitoli in grassetto"),
    "mo_sub_font": ("Font subtitrare", "Subtitle font", "Font dei sottotitoli"),
    "mh_sub_font": ("Numele unui font instalat, ex.: DejaVu Sans. Se aplică subtitrărilor text, nu celor bitmap DVB.",
                    "Name of an installed font, e.g. DejaVu Sans. Applies to text subtitles, not DVB bitmap ones.",
                    "Nome di un font installato, es.: DejaVu Sans. Vale per i sottotitoli di testo, non per quelli bitmap DVB."),
    "mo_sub_pos": ("Poziție verticală subtitrare", "Subtitle vertical position", "Posizione verticale dei sottotitoli"),
    "mh_sub_pos": ("100% = jos; valori mai mici ridică subtitrarea.", "100% = bottom; lower values raise the subtitle.", "100% = in basso; valori minori alzano il sottotitolo."),
    "mo_sub_delay": ("Decalaj subtitrare", "Subtitle delay", "Ritardo dei sottotitoli"),
    "mh_sub_delay": ("Pozitiv = subtitrarea apare mai târziu, negativ = mai devreme.", "Positive = subtitle appears later, negative = earlier.", "Positivo = il sottotitolo appare dopo, negativo = prima."),

    # ---- Flux și cache
    "mo_cache": ("Cache", "Cache", "Cache"),
    "mh_cache": ("Memorarea în avans a fluxului. Pe TV live „Nu” reduce întârzierea, dar poate face imaginea mai sensibilă la semnal slab.",
                 "Pre-buffering of the stream. On live TV “No” lowers delay but makes the picture more sensitive to a weak signal.",
                 "Pre-memorizzazione del flusso. Sulla TV live «No» riduce il ritardo ma rende l'immagine più sensibile a un segnale debole."),
    "mo_cache_pause": ("Pauză când se golește bufferul", "Pause when buffer runs out", "Pausa quando il buffer si svuota"),
    "mh_cache_pause": ("„Nu” = imaginea continuă fără să se oprească la semnal slab (poate sacada); „Da” = se oprește și reia după reumplere.",
                       "“No” = playback continues without stopping on a weak signal (may stutter); “Yes” = it pauses and resumes after refilling.",
                       "«No» = la riproduzione continua senza fermarsi con segnale debole (può scattare); «Sì» = si ferma e riprende dopo il riempimento."),
    "mo_readahead": ("Citire în avans", "Read-ahead", "Lettura anticipata"),
    "mh_readahead": ("Câte secunde de flux citește mpv în avans. Valori mari = mai stabil, dar canalul pornește mai greu.",
                     "How many seconds of the stream mpv reads ahead. Higher = more stable but slower channel start.",
                     "Quanti secondi di flusso mpv legge in anticipo. Valori alti = più stabile ma avvio canale più lento."),
    "mo_demuxer_max": ("Memorie maximă pentru flux", "Maximum stream memory", "Memoria massima per il flusso"),

    # ---- Avansat
    "mo_framedrop": ("Sărire cadre când PC-ul nu ține pasul", "Frame dropping when the PC can't keep up", "Salto fotogrammi se il PC non regge"),
    "mh_framedrop": ("Ajută pe PC-uri slabe: sare cadre în loc să rămână în urma sunetului. „decoder+vo” e cel mai agresiv.",
                     "Helps on weak PCs: drops frames instead of falling behind the audio. “decoder+vo” is the most aggressive.",
                     "Aiuta sui PC deboli: salta fotogrammi invece di restare indietro rispetto all'audio. «decoder+vo» è il più aggressivo."),
    "mo_vd_threads": ("Fire de decodare (CPU)", "Decoding threads (CPU)", "Thread di decodifica (CPU)"),
    "mh_vd_threads": ("0 = automat. Contează doar la decodare software (fără hwdec).", "0 = automatic. Only matters for software decoding (no hwdec).", "0 = automatico. Conta solo per la decodifica software (senza hwdec)."),
    "mo_vd_fast": ("Decodare rapidă (calitate mai mică)", "Fast decoding (lower quality)", "Decodifica veloce (qualità minore)"),
    "mh_vd_fast": ("Accelerează decodarea software pe PC-uri slabe, cu mici artefacte.", "Speeds up software decoding on weak PCs, with minor artifacts.", "Accelera la decodifica software sui PC deboli, con piccoli artefatti."),
    "mo_skiploopfilter": ("Sari peste filtrul de buclă H.264", "Skip H.264 loop filter", "Salta il filtro di loop H.264"),
    "mh_skiploopfilter": ("Economisește CPU la HD pe PC foarte slabe; imaginea devine puțin mai „blocată”.", "Saves CPU on HD on very weak PCs; the picture becomes slightly blockier.", "Risparmia CPU in HD su PC molto deboli; l'immagine diventa un po' più a blocchi."),
    "mo_audio_buffer": ("Buffer audio", "Audio buffer", "Buffer audio"),
    "mh_audio_buffer": ("Mic = latență mică, dar riscul de pocnituri. Util dacă sunetul întârzie față de imagine.", "Small = low latency but risk of crackling. Useful if the sound lags behind the picture.", "Piccolo = bassa latenza ma rischio di scoppiettii. Utile se l'audio è in ritardo rispetto all'immagine."),
    "mo_video_latency": ("Latență video redusă", "Reduced video latency", "Latenza video ridotta"),
    "mh_video_latency": ("Aplică trucuri care reduc întârzierea imaginii; poate afecta fluiditatea.", "Applies tricks that reduce picture delay; may affect smoothness.", "Applica trucchi che riducono il ritardo dell'immagine; può influire sulla fluidità."),
    "mo_cursor_autohide": ("Ascunde cursorul după", "Hide cursor after", "Nascondi il cursore dopo"),
    "mo_stop_screensaver": ("mpv oprește screensaver-ul", "mpv stops the screensaver", "mpv blocca lo screensaver"),
    "mh_stop_screensaver": ("Programul blochează oricum suspendarea singur; asta e doar plasa de siguranță a mpv.", "The program blocks sleep by itself anyway; this is only mpv's own safety net.", "Il programma blocca comunque la sospensione da solo; questa è solo la rete di sicurezza di mpv."),
    "mo_log_file": ("Scrie jurnal mpv în fișier", "Write mpv log to file", "Scrivi il log di mpv su file"),
    "mh_log_file": ("Util la depanare: scrie ~/.config/TeleopsDVB/mpv.log. Dezactivează-l după, ca să nu crească fișierul.", "Useful for debugging: writes ~/.config/TeleopsDVB/mpv.log. Turn it off afterwards so the file doesn't grow.", "Utile per il debug: scrive ~/.config/TeleopsDVB/mpv.log. Disattivalo dopo, così il file non cresce."),
    "mo_log_level": ("Nivel detaliu jurnal", "Log detail level", "Livello di dettaglio del log"),
    "mo_extra": ("Linii suplimentare mpv.conf", "Extra mpv.conf lines", "Righe extra di mpv.conf"),
    "mh_extra": ("Câte o opțiune pe linie, ca în mpv.conf: cheie=valoare (ex. hwdec-codecs=all). Liniile invalide sunt ignorate. Se adaugă la sfârșitul blocului.",
                 "One option per line as in mpv.conf: key=value (e.g. hwdec-codecs=all). Invalid lines are ignored. Added at the end of the block.",
                 "Un'opzione per riga come in mpv.conf: chiave=valore (es. hwdec-codecs=all). Le righe non valide vengono ignorate. Aggiunte alla fine del blocco."),

    "mh_prim": ("bt.709 pentru HD, bt.601-625 pentru canalele SD PAL. „auto” alege după flux.", "bt.709 for HD, bt.601-625 for SD PAL channels. “auto” follows the stream.", "bt.709 per l'HD, bt.601-625 per i canali SD PAL. «auto» segue il flusso."),
    "mh_hdr_peak": ("Pentru canale HDR: calculează luminozitatea maximă automat. Costă puțin GPU.", "For HDR channels: computes peak brightness automatically. Costs a little GPU.", "Per i canali HDR: calcola automaticamente la luminosità di picco. Costa poco GPU."),
    "mh_downmix_norm": ("La mixarea 5.1 → stereo, ridică volumul ca să nu sune mai încet decât stereo nativ.", "When mixing 5.1 → stereo, raises the volume so it isn't quieter than native stereo.", "Nel downmix 5.1 → stereo, alza il volume per non suonare più piano dello stereo nativo."),
    "mh_sub_size": ("Se aplică subtitrărilor text. Cele DVB bitmap își au mărimea lor fixă.", "Applies to text subtitles. DVB bitmap ones have a fixed size.", "Vale per i sottotitoli di testo. Quelli bitmap DVB hanno dimensione fissa."),
    "mh_demuxer_max": ("Plafonul memoriei folosite pentru memorarea fluxului. Valorile mari ajută la întreruperi scurte de semnal.", "Cap on memory used to buffer the stream. Larger values help with short signal drops.", "Limite di memoria per il buffer del flusso. Valori alti aiutano con brevi cali di segnale."),
    "mh_cursor_autohide": ("Ascunde cursorul mouse-ului peste imaginea mpv după un timp de inactivitate.", "Hides the mouse cursor over the mpv picture after a period of inactivity.", "Nasconde il cursore del mouse sull'immagine mpv dopo un periodo di inattività."),
    "mh_log_level": ("Cât de detaliat e jurnalul: warn = doar probleme, v = foarte detaliat.", "How detailed the log is: warn = problems only, v = very detailed.", "Quanto è dettagliato il log: warn = solo problemi, v = molto dettagliato."),
}


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE i18n/strings_rec
#   Texte pentru înregistrările programate din EPG. Format: cheie: (ro, en, it).
# ──────────────────────────────────────────────────────────────────────────────

REC_T = {
    "epg_rec_btn": ("⏺ Înregistrează emisiunea / filmul", "⏺ Record this programme / film", "⏺ Registra programma / film"),
    "epg_rec_cancel": ("✖ Anulează programarea", "✖ Cancel scheduled recording", "✖ Annulla la registrazione programmata"),
    "epg_rec_tip": ("Pornește cu 2 minute înainte și se oprește la 2 minute după emisiune. ⏺ = programată.",
                    "Starts 2 minutes before and stops 2 minutes after the programme. ⏺ = scheduled.",
                    "Inizia 2 minuti prima e si ferma 2 minuti dopo il programma. ⏺ = programmata."),
    "epg_rec_added": ("Înregistrare programată: {start}–{end}, cu {margin} min înainte și după.",
                      "Recording scheduled: {start}–{end}, with {margin} min before and after.",
                      "Registrazione programmata: {start}–{end}, con {margin} min prima e dopo."),
    "epg_rec_removed": ("Programarea a fost anulată.", "The scheduled recording was cancelled.", "La registrazione programmata è stata annullata."),
    "epg_rec_past": ("Emisiunea s-a încheiat deja.", "That programme has already ended.", "Il programma è già terminato."),
    "sched_busy": ("Programarea „{title}” ({channel}) a fost anulată: în acel moment se înregistra deja alt canal.",
                   "The scheduled recording “{title}” ({channel}) was cancelled: another channel was already being recorded.",
                   "La registrazione programmata «{title}» ({channel}) è stata annullata: si stava già registrando un altro canale."),
    "sched_fail": ("Programarea „{title}” ({channel}) a fost anulată: canalul nu a putut fi pornit.",
                   "The scheduled recording “{title}” ({channel}) was cancelled: the channel could not be started.",
                   "La registrazione programmata «{title}» ({channel}) è stata annullata: impossibile avviare il canale."),
    "sched_started": ("● Înregistrare programată pornită: {title}", "● Scheduled recording started: {title}", "● Registrazione programmata avviata: {title}"),
    "sched_finished": ("Înregistrare programată încheiată: {title}", "Scheduled recording finished: {title}", "Registrazione programmata terminata: {title}"),
    "rec_watch_dropped": ("Vizionarea programată pentru {items} a fost anulată: se suprapune cu înregistrarea, care are prioritate.",
                          "The scheduled viewing of {items} was cancelled: it overlaps the recording, which has priority.",
                          "La visione programmata di {items} è stata annullata: si sovrappone alla registrazione, che ha la priorità."),
    # „Vreau să vizionez”: comutare automată pe canalul emisiunii
    "epg_watch_btn": ("📺 Vreau să vizionez", "📺 I want to watch", "📺 Voglio guardare"),
    "epg_watch_cancel": ("✖ Anulează vizionarea", "✖ Cancel viewing", "✖ Annulla la visione"),
    "epg_watch_tip": ("Comută singur pe acest canal cu {lead} min înainte de începerea emisiunii, dacă te uiți la alt canal. Nu comută dacă înregistrezi alt canal. 📺 = programată.",
                      "Switches to this channel by itself {lead} min before the programme starts, if you are watching another channel. It does not switch while another channel is being recorded. 📺 = scheduled.",
                      "Passa da solo a questo canale {lead} min prima dell'inizio del programma, se stai guardando un altro canale. Non passa se si sta registrando un altro canale. 📺 = programmato."),
    "epg_watch_added": ("Vizionare programată: emisiunea începe la {start}; se trece automat pe acest canal cu {lead} min înainte.",
                        "Viewing scheduled: the programme starts at {start}; the player will switch to this channel automatically {lead} min earlier.",
                        "Visione programmata: il programma inizia alle {start}; si passa automaticamente a questo canale {lead} min prima."),
    "epg_watch_removed": ("Vizionarea programată a fost anulată.", "The scheduled viewing was cancelled.", "La visione programmata è stata annullata."),
    "epg_watch_running": ("Emisiunea rulează deja pe canalul curent.", "That programme is already on the current channel.", "Il programma è già in onda sul canale corrente."),
    "epg_watch_clash": ("Nu s-a programat: în acel interval se înregistrează „{title}” ({channel}), iar tunerul nu poate face ambele. Anulează întâi înregistrarea.",
                        "Not scheduled: “{title}” ({channel}) is being recorded in that time slot, and the tuner can't do both. Cancel the recording first.",
                        "Non programmato: in quell'intervallo si registra «{title}» ({channel}) e il sintonizzatore non può fare entrambe le cose. Annulla prima la registrazione."),
    "watch_skip_rec": ("Nu s-a comutat pe {channel} pentru „{title}”: se înregistrează alt canal.",
                       "Did not switch to {channel} for “{title}”: another channel is being recorded.",
                       "Nessun cambio su {channel} per «{title}»: si sta registrando un altro canale."),
    "watch_skip_busy": ("Nu s-a comutat pe {channel} pentru „{title}”: tunerul e ocupat cu scanarea.",
                        "Did not switch to {channel} for “{title}”: the tuner is busy scanning.",
                        "Nessun cambio su {channel} per «{title}»: il sintonizzatore è occupato con la scansione."),
    "watch_fail": ("Nu s-a putut comuta pe {channel} pentru „{title}”: canalul nu mai există în listă.",
                   "Could not switch to {channel} for “{title}”: the channel is no longer in the list.",
                   "Impossibile passare a {channel} per «{title}»: il canale non è più nell'elenco."),
}


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE i18n/strings_ext
#   Texte pentru Timeshift, tema ferestrei, fereastra „Tuner TV”, tastele noi și „Programările mele” din EPG.
#   Format: cheie: (ro, en, it).
# ──────────────────────────────────────────────────────────────────────────────

EXT_T = {
    # Timeshift (pauză / derulare la TV live)
    "ts_enable": ("Activare Timeshift", "Enable Timeshift", "Attiva Timeshift"),
    "ts_size_label": ("Buffer maxim:", "Maximum buffer:", "Buffer massimo:"),
    "ts_tip": ("Pauză și derulare înapoi/înainte la TV live, cu bufferul mpv (RAM + disc). Space = pauză, "
               "Ctrl+←/→ = derulare 10 s, Ctrl+0 = înapoi la live; bara de comandă apare la pauză, la derulare sau cu click dreapta pe video. "
               "Bufferul se golește la schimbarea canalului. Se aplică imediat dacă nu înregistrezi; altfel, la următorul canal.",
               "Pause and rewind/fast-forward on live TV, using the mpv buffer (RAM + disk). Space = pause, "
               "Ctrl+←/→ = seek 10 s, Ctrl+0 = back to live; the control bar shows when paused, when seeking or on right click over the video. "
               "The buffer is cleared when the channel changes. Applies at once unless you are recording; then it applies to the next channel.",
               "Pausa e riavvolgimento/avanzamento nella TV in diretta, con il buffer di mpv (RAM + disco). Spazio = pausa, "
               "Ctrl+←/→ = salto di 10 s, Ctrl+0 = torna alla diretta; la barra di controllo appare in pausa, durante il salto o con clic destro sul video. "
               "Il buffer si svuota al cambio di canale. Si applica subito se non stai registrando; altrimenti al canale successivo."),
    "ts_later": ("Timeshift se va aplica la următoarea schimbare de canal.",
                 "Timeshift will apply on the next channel change.",
                 "Timeshift si applicherà al prossimo cambio di canale."),
    "ts_mode_label": ("Buffer în:", "Buffer in:", "Buffer in:"),
    "ts_mode_ram": ("Memorie RAM (max. 1024 MB)", "RAM (max. 1024 MB)", "RAM (max. 1024 MB)"),
    "ts_mode_disk": ("Disc (dosarul înregistrărilor)", "Disk (recordings folder)", "Disco (cartella registrazioni)"),
    "ts_fp_fallback": ("mpv (Flatpak) nu poate scrie în dosarul înregistrărilor: bufferul e în cache-ul Flatpak. "
                       "Dă-i acces: flatpak override --user --filesystem=<dosar> io.mpv.Mpv",
                       "mpv (Flatpak) cannot write to the recordings folder: the buffer is in the Flatpak cache. "
                       "Grant access: flatpak override --user --filesystem=<folder> io.mpv.Mpv",
                       "mpv (Flatpak) non può scrivere nella cartella delle registrazioni: il buffer è nella cache Flatpak. "
                       "Concedi l'accesso: flatpak override --user --filesystem=<cartella> io.mpv.Mpv"),
    "ts_no_disk": ("mpv-ul instalat nu are cache pe disc (mpv prea vechi): Timeshift folosește RAM, max. 1024 MB.",
                   "The installed mpv has no on-disk cache (mpv too old): Timeshift uses RAM, max. 1024 MB.",
                   "L'mpv installato non ha la cache su disco (mpv troppo vecchio): Timeshift usa la RAM, max. 1024 MB."),
    # Tema
    "theme_label": ("Temă:", "Theme:", "Tema:"),
    "theme_light": ("Luminoasă", "Light", "Chiaro"),
    "theme_dark": ("Întunecată", "Dark", "Scuro"),
    "theme_auto": ("Automată (după sistem)", "Auto (follow system)", "Automatico (come il sistema)"),
    # Fereastra „Tuner TV”
    "tuner_btn": ("📡 Tuner TV", "📡 TV Tuner", "📡 Sintonizzatore TV"),
    "tuner_title": ("Tuner TV", "TV Tuner", "Sintonizzatore TV"),
    "tuner_close": ("Închide", "Close", "Chiudi"),
    # Taste noi (fila „Comenzi rapide” din „Despre”)
    "hk_chan": ("Canal următor / anterior (după 3 s)", "Next / previous channel (after 3 s)", "Canale successivo / precedente (dopo 3 s)"),
    "hk_chan_k": ("↑ / ↓ pe video; Enter = acum; Esc = anulează", "↑ / ↓ on video; Enter = now; Esc = cancel", "↑ / ↓ sul video; Invio = subito; Esc = annulla"),
    "hk_volkeys": ("Volum (tastatură)", "Volume (keyboard)", "Volume (tastiera)"),
    "hk_volkeys_k": ("← / → pe video", "← / → on video", "← / → sul video"),
    "hk_ts_pause": ("Pauză / redare (Timeshift)", "Pause / play (Timeshift)", "Pausa / riproduzione (Timeshift)"),
    "hk_ts_pause_k": ("Space", "Space", "Spazio"),
    "hk_ts_seek": ("Înapoi / înainte 10 s (Timeshift)", "Back / forward 10 s (Timeshift)", "Indietro / avanti 10 s (Timeshift)"),
    "hk_ts_seek_k": ("CTRL + ← / →", "CTRL + ← / →", "CTRL + ← / →"),
    "hk_ts_live": ("Salt la live (Timeshift)", "Jump to live (Timeshift)", "Vai alla diretta (Timeshift)"),
    "hk_ts_live_k": ("CTRL + 0", "CTRL + 0", "CTRL + 0"),
    "hk_ts_bar": ("Bară Timeshift cu mouse-ul", "Timeshift bar with the mouse", "Barra Timeshift con il mouse"),
    "hk_stats": ("Informații mpv (pagini 1-5)", "mpv info (pages 1-5)", "Informazioni mpv (pagine 1-5)"),
    "hk_stats_k": ("Butonul i din bara video", "The i button in the video bar", "Pulsante i nella barra video"),
    "hk_ts_bar_k": ("Click dreapta pe video", "Right click on video", "Clic destro sul video"),
    # EPG: fila „Programările mele”
    "epg_tab_prog": ("Program TV", "TV Guide", "Guida TV"),
    "epg_tab_my": ("Programările mele", "My schedule", "Le mie programmazioni"),
    "my_rec": ("⏺ Înregistrare", "⏺ Recording", "⏺ Registrazione"),
    "my_watch": ("📺 Vizionare", "📺 Viewing", "📺 Visione"),
    "my_col_type": ("Tip", "Type", "Tipo"),
    "my_col_channel": ("Canal", "Channel", "Canale"),
    "my_delete": ("🗑 Șterge programarea", "🗑 Delete item", "🗑 Elimina"),
    "my_clear": ("Golește tot", "Clear all", "Svuota tutto"),
    "my_empty": ("Nu ai nicio înregistrare sau vizionare programată.",
                 "You have no scheduled recordings or viewings.",
                 "Non hai registrazioni o visioni programmate."),
    "my_deleted": ("Programarea a fost ștearsă.", "The item was deleted.", "La programmazione è stata eliminata."),
    "my_cleared": ("Toate programările au fost șterse.", "All scheduled items were deleted.", "Tutte le programmazioni sono state eliminate."),
    "my_clear_confirm": ("Ștergi toate programările (înregistrări și vizionări)?",
                         "Delete all scheduled items (recordings and viewings)?",
                         "Eliminare tutte le programmazioni (registrazioni e visioni)?"),
}


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE i18n/translate
#   Traduceri: `tr(lang, cheie)`.
# ──────────────────────────────────────────────────────────────────────────────

T.update(MPV_T)
T.update(REC_T)
T.update(EXT_T)


def tr(lang, key):
    return T[key][LANGS.index(lang) if lang in LANGS else 0]


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: system  ·  Integrare cu sistemul: mediu, X11, D-Bus, anti-sleep, editor, instanță unică
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE system/dbus_min
#   Client D-Bus minimal, fără dependențe: doar apeluri de metodă pe session bus.
#
#   Îl folosim ca să cerem „inhibit” (screensaver/sleep) fără `python3-dbus` sau `python3-gi`.
#   Un „inhibit” D-Bus e legat de conexiune: cât timp socketul rămâne deschis, blocarea rămâne activă,
#   iar când procesul moare (chiar și brusc) magistrala o eliberează singură.
#
#   Suportă doar tipurile de care avem nevoie: `s`, `o`, `u` (argumente) și `u`/`s`/`o`/`b` (răspuns).
# ──────────────────────────────────────────────────────────────────────────────

_METHOD_CALL, _METHOD_RETURN, _ERROR = 1, 2, 3
_PATH, _IFACE, _MEMBER, _ERR_NAME, _REPLY_SERIAL, _DEST, _SIG = 1, 2, 3, 4, 5, 6, 8


class DBusError(Exception):
    pass


def _align(buf, n):
    buf += b"\0" * (-len(buf) % n)


def _put_u32(buf, v):
    _align(buf, 4)
    buf += struct.pack("<I", v)


def _put_str(buf, s):
    data = s.encode("utf-8")
    _put_u32(buf, len(data))
    buf += data + b"\0"


def _put_sig(buf, s):
    buf.append(len(s))
    buf += s.encode("ascii") + b"\0"


def _marshal(sig, args):
    body = bytearray()
    if len(sig) != len(args):
        raise DBusError("semnătură/argumente nepotrivite")
    for t, v in zip(sig, args):
        if t in "so":
            _put_str(body, v)
        elif t == "u":
            _put_u32(body, v)
        else:
            raise DBusError(f"tip nesuportat: {t}")
    return bytes(body)


def _field(buf, code, typ, val):
    _align(buf, 8)
    buf.append(code)
    _put_sig(buf, typ)
    if typ in "so":
        _put_str(buf, val)
    elif typ == "g":
        _put_sig(buf, val)
    elif typ == "u":
        _put_u32(buf, val)


def build_call(serial, dest, path, iface, member, sig="", args=()):
    """Mesajul binar pentru un apel de metodă (little-endian)."""
    body = _marshal(sig, args)
    f = bytearray()
    _field(f, _PATH, "o", path)
    if iface:
        _field(f, _IFACE, "s", iface)
    _field(f, _MEMBER, "s", member)
    _field(f, _DEST, "s", dest)
    if sig:
        _field(f, _SIG, "g", sig)
    head = b"l" + bytes([_METHOD_CALL, 0, 1]) + struct.pack("<III", len(body), serial, len(f))
    pad = b"\0" * (-(len(head) + len(f)) % 8)
    return head + bytes(f) + pad + body


def _parse_fields(data):
    out, i = {}, 0
    while i < len(data):
        i += -i % 8
        if i >= len(data):
            break
        code = data[i]
        n = data[i + 1]
        sig = data[i + 2:i + 2 + n].decode("ascii")
        i += 3 + n
        if sig in ("s", "o"):
            i += -i % 4
            (ln,) = struct.unpack_from("<I", data, i)
            out[code] = data[i + 4:i + 4 + ln].decode("utf-8", "replace")
            i += 4 + ln + 1
        elif sig == "g":
            ln = data[i]
            out[code] = data[i + 1:i + 1 + ln].decode("ascii", "replace")
            i += 1 + ln + 1
        elif sig == "u":
            i += -i % 4
            (out[code],) = struct.unpack_from("<I", data, i)
            i += 4
        else:
            break
    return out


def _parse_body(sig, body):
    vals, i = [], 0
    for t in sig:
        if t in "so":
            i += -i % 4
            (ln,) = struct.unpack_from("<I", body, i)
            vals.append(body[i + 4:i + 4 + ln].decode("utf-8", "replace"))
            i += 4 + ln + 1
        elif t in "ub":
            i += -i % 4
            (v,) = struct.unpack_from("<I", body, i)
            vals.append(bool(v) if t == "b" else v)
            i += 4
        else:
            break               # tip pe care nu-l interpretăm: ne oprim, nu eșuăm
    return vals


def _session_address():
    addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    for part in addr.split(";"):
        if not part.startswith("unix:"):
            continue
        kv = dict(p.split("=", 1) for p in part[5:].split(",") if "=" in p)
        if "path" in kv:
            return kv["path"]
        if "abstract" in kv:
            return "\0" + kv["abstract"]
    return f"/run/user/{os.getuid()}/bus"


class DBusSession:
    """Conexiune la session bus. Se folosește dintr-un singur fir de execuție odată."""

    def __init__(self, timeout=2.0):
        self.serial = 0
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(_session_address())
            uid = str(os.getuid()).encode().hex()
            self.sock.sendall(b"\0AUTH EXTERNAL " + uid.encode() + b"\r\n")
            reply = self._read_line()
            if not reply.startswith(b"OK"):
                raise DBusError(f"autentificare refuzată: {reply!r}")
            self.sock.sendall(b"BEGIN\r\n")
            self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "Hello")
        except Exception:
            self.close()
            raise

    def _read_line(self):
        buf = b""
        while not buf.endswith(b"\r\n"):
            c = self.sock.recv(1)
            if not c:
                raise DBusError("conexiune închisă")
            buf += c
        return buf

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            c = self.sock.recv(n - len(buf))
            if not c:
                raise DBusError("conexiune închisă")
            buf += c
        return buf

    def _read_message(self):
        head = self._read_exact(16)
        if head[0:1] != b"l":
            raise DBusError("endianness nesuportat")
        mtype, _flags, _ver, blen, _serial, flen = struct.unpack("<BBBIII", head[1:16])
        fields = self._read_exact(flen)
        self._read_exact(-(16 + flen) % 8)
        body = self._read_exact(blen)
        return mtype, _parse_fields(fields), body

    def call(self, dest, path, iface, member, sig="", args=()):
        """Apelează o metodă și întoarce lista valorilor din răspuns. Ridică DBusError la eroare."""
        self.serial += 1
        serial = self.serial
        self.sock.sendall(build_call(serial, dest, path, iface, member, sig, args))
        while True:
            mtype, fields, body = self._read_message()
            if fields.get(_REPLY_SERIAL) != serial:
                continue            # semnale / alte mesaje: le ignorăm
            if mtype == _ERROR:
                raise DBusError(fields.get(_ERR_NAME, "eroare D-Bus"))
            if mtype == _METHOD_RETURN:
                return _parse_body(fields.get(_SIG, ""), body)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE system/x11
#   Ajutor peste libX11 prin ctypes (fără dependențe de Tk).
# ──────────────────────────────────────────────────────────────────────────────

class X11:
    """Ajutor mic peste libX11 (ctypes, conexiune proprie): poziția/butoanele mouse-ului (pentru tragerea
    ferestrei din mpv, care e fereastră X11 copil și nu trimite evenimentele către Tk) și hint-ul Motif
    prin care scoatem marginile/titlebar-ul. Merge pe X11 și pe XWayland."""
    BUTTON1 = 0x100

    def __init__(self):
        c = ctypes
        lib = self.lib = c.CDLL(c.util.find_library("X11") or "libX11.so.6")
        vp, ul, ci = c.c_void_p, c.c_ulong, c.c_int
        lib.XOpenDisplay.restype, lib.XOpenDisplay.argtypes = vp, [c.c_char_p]
        lib.XDefaultRootWindow.restype, lib.XDefaultRootWindow.argtypes = ul, [vp]
        lib.XInternAtom.restype, lib.XInternAtom.argtypes = ul, [vp, c.c_char_p, ci]
        lib.XQueryPointer.argtypes = [vp, ul, c.POINTER(ul), c.POINTER(ul), c.POINTER(ci), c.POINTER(ci),
                                      c.POINTER(ci), c.POINTER(ci), c.POINTER(c.c_uint)]
        lib.XQueryTree.argtypes = [vp, ul, c.POINTER(ul), c.POINTER(ul), c.POINTER(vp), c.POINTER(c.c_uint)]
        lib.XChangeProperty.argtypes = [vp, ul, ul, ul, ci, ci, vp, ci]
        lib.XFree.argtypes = [vp]
        lib.XFlush.argtypes = [vp]
        lib.XResetScreenSaver.argtypes = [vp]
        self.dpy = lib.XOpenDisplay(None)
        if not self.dpy:
            raise OSError("XOpenDisplay")
        self.root = lib.XDefaultRootWindow(self.dpy)

    @classmethod
    def create(cls):
        try: return cls()
        except Exception: return None

    def pointer(self):
        c = ctypes
        r, ch, m = c.c_ulong(), c.c_ulong(), c.c_uint()
        rx, ry, wx, wy = (c.c_int() for _ in range(4))
        self.lib.XQueryPointer(self.dpy, self.root, c.byref(r), c.byref(ch), c.byref(rx), c.byref(ry),
                               c.byref(wx), c.byref(wy), c.byref(m))
        return rx.value, ry.value, m.value

    def set_borderless(self, xid, on):
        c, lib = ctypes, self.lib
        atom = lib.XInternAtom(self.dpy, b"_MOTIF_WM_HINTS", 0)
        data = (c.c_ulong * 5)(2, 0, 0 if on else 1, 0, 0)      # flags=decorations, decorations=0 (fără) / 1 (toate)
        rr, parent, kids, n = c.c_ulong(), c.c_ulong(), c.c_void_p(), c.c_uint()
        lib.XQueryTree(self.dpy, xid, c.byref(rr), c.byref(parent), c.byref(kids), c.byref(n))
        if kids:
            lib.XFree(kids)
        # Tk își pune fereastra într-un „wrapper” – acela e fereastra gestionată de WM; setăm hint-ul pe ambele
        for win in {xid, parent.value} - {0, self.root}:
            lib.XChangeProperty(self.dpy, win, atom, atom, 32, 0, c.cast(data, c.c_void_p), 5)
        lib.XFlush(self.dpy)

    def reset_screensaver(self):
        """Repornește cronometrul screensaver/DPMS al serverului X (inclusiv XWayland)."""
        self.lib.XResetScreenSaver(self.dpy)
        self.lib.XFlush(self.dpy)


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE system/env
#   Mediul de execuție: variabile curate pentru procese copil, căutarea mpv și a uneltelor DVB.
# ──────────────────────────────────────────────────────────────────────────────

MPV_MISSING_MSG = ("Playerul MPV nu a fost găsit pe sistem.\n\nInstalează-l prin:\n  sudo apt install mpv\n"
                   "sau\n  flatpak install flathub io.mpv.Mpv")
DEPS_MISSING_TAIL = "\n\nInstalează-le prin:\n  sudo apt install dvb-tools"


def get_clean_env():
    """Mediu curățat de variabilele injectate de PyInstaller."""
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "LIBPATH", "PYTHONPATH"):
        env.pop(var, None)
        env.pop(f"{var}_ORIG", None)
    return env


def find_mpv():
    """Comanda de pornire a mpv (listă) sau None dacă nu e instalat."""
    if shutil.which("mpv"):
        return ["mpv"]
    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", "io.mpv.Mpv"], capture_output=True).returncode == 0:
        return ["flatpak", "run", "io.mpv.Mpv"]
    return None


def missing_dependencies():
    """Lista dependențelor obligatorii care lipsesc (text gata de afișat)."""
    missing = []
    if not shutil.which("dvbv5-zap") or not shutil.which("dvbv5-scan"):
        missing.append("dvb-tools (conține dvbv5-zap, dvbv5-scan)")
    return missing


def deps_message(missing):
    return "Următoarele dependențe lipsesc pe sistem:\n\n" + "\n".join(f"  • {m}" for m in missing) + DEPS_MISSING_TAIL


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE system/theme
#   Tema sistemului (luminoasă / întunecată), pentru setarea „Automată”. Fără dependențe: GNOME/GTK, KDE, GTK_THEME.
# ──────────────────────────────────────────────────────────────────────────────

def _read_ini(path):
    try:
        cp = configparser.RawConfigParser(strict=False)
        cp.read(path, encoding="utf-8")
        return cp
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None


def _gsettings(key):
    try:
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", key], capture_output=True, text=True,
                           timeout=2, env=get_clean_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip().strip("'\"").lower() if r.returncode == 0 else ""


def system_prefers_dark():
    """True dacă sistemul folosește o temă întunecată. Dacă nu se poate afla nimic, False (tema luminoasă)."""
    gtk_theme = os.environ.get("GTK_THEME", "").lower()
    if gtk_theme:
        return "dark" in gtk_theme
    scheme = _gsettings("color-scheme")
    if "dark" in scheme:
        return True
    if "light" in scheme:
        return False
    if "dark" in _gsettings("gtk-theme"):
        return True
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    kde = _read_ini(cfg / "kdeglobals")                  # KDE: luminanța fundalului ferestrelor (sau numele schemei)
    if kde is not None:
        try:
            r, g, b = (int(v) for v in kde.get("Colors:Window", "BackgroundNormal").split(",")[:3])
            return 0.299 * r + 0.587 * g + 0.114 * b < 128
        except (configparser.Error, ValueError):
            if "dark" in kde.get("General", "ColorScheme", fallback="").lower():
                return True
    for ver in ("gtk-4.0", "gtk-3.0"):
        ini = _read_ini(cfg / ver / "settings.ini")
        if ini is not None:
            if ini.get("Settings", "gtk-application-prefer-dark-theme", fallback="").strip().lower() in ("1", "true"):
                return True
            if "dark" in ini.get("Settings", "gtk-theme-name", fallback="").lower():
                return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE system/opener
#   Deschiderea unui fișier într-un editor de text.
# ──────────────────────────────────────────────────────────────────────────────

EDITORS = ("xdg-open", "gio open", "kate", "gedit", "kwrite", "mousepad", "xed", "pluma", "gnome-text-editor")


def open_in_editor(path):
    """True dacă s-a pornit un editor; False dacă nu s-a găsit niciunul."""
    for cmd in EDITORS:
        argv = cmd.split()
        if shutil.which(argv[0]):
            subprocess.Popen(argv + [str(path)], env=get_clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE system/single_instance
#   Doar o instanță a programului.
# ──────────────────────────────────────────────────────────────────────────────

_LOCK_FH = None


def acquire_single_instance():
    """Lacăt de fișier (eliberat automat de sistem când procesul se termină). False dacă rulează deja o instanță."""
    global _LOCK_FH
    _LOCK_FH = open(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "teleops-dvb.lock", "w")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE system/inhibit
#   Blochează suspend-ul, screensaver-ul și stingerea ecranului cât rulează programul.
#
#   Nu ne bazăm pe mpv (care o face doar cât are imagine și doar pe unele sisteme). Pornim în paralel
#   mai multe metode, toate „best effort”; dacă una nu există pe sistemul curent, e ignorată:
#
#    1. D-Bus (client propriu, dependență zero): org.freedesktop.ScreenSaver (KDE, GNOME, Xfce...),
#       org.freedesktop.PowerManagement, org.gnome.SessionManager, Cinnamon, MATE. Blocarea ține cât e
#       deschisă conexiunea; dacă procesul moare brusc, magistrala o eliberează singură.
#    2. systemd-logind: `systemd-inhibit` (idle + sleep). Folosit în „leasing-uri” scurte reînnoite periodic,
#       ca un proces mort brusc să nu lase o blocare fără sfârșit (maxim LEASE secunde).
#    3. X11: XResetScreenSaver periodic (screensaver/DPMS clasic, inclusiv prin XWayland).
#
#   Depanare: TELEOPS_DEBUG=1 afișează în terminal ce metode au fost activate.
# ──────────────────────────────────────────────────────────────────────────────

inhibit_log = logging.getLogger(__name__)

BEAT = 30       # secunde între reînnoiri
LEASE = 90      # cât durează un leasing systemd-inhibit (trebuie să fie > BEAT)

# (destinație, cale, interfață, semnătură argumente, metodă de eliberare)
_FDO = ("ss", "UnInhibit")
_SESSION_MGR = ("susu", "Uninhibit")     # (app_id, xid, motiv, flags); flags 4=suspend | 8=idle
_BACKENDS = (
    ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver", *_FDO),
    ("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", *_FDO),   # rezervă (KDE)
    ("org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement/Inhibit",
     "org.freedesktop.PowerManagement.Inhibit", *_FDO),
    ("org.gnome.SessionManager", "/org/gnome/SessionManager", "org.gnome.SessionManager", *_SESSION_MGR),
    ("org.cinnamon.SessionManager", "/org/cinnamon/SessionManager", "org.cinnamon.SessionManager", *_SESSION_MGR),
    ("org.mate.SessionManager", "/org/mate/SessionManager", "org.mate.SessionManager", *_SESSION_MGR),
)


class SleepInhibitor:
    def __init__(self, app="Teleops DVB", reason="Redare TV/radio DVB"):
        self.app, self.reason = app, reason
        self.active = []                    # numele metodelor activate (pentru depanare)
        self._stop = threading.Event()
        self._thread = None
        self._bus = None
        self._cookies = []                  # (dest, path, iface, release_member, cookie)
        self._leases = []                   # procese systemd-inhibit în viață
        self._x11 = None

    def start(self):
        """Pornește blocarea în fundal (nu întârzie deschiderea ferestrei)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="sleep-inhibit", daemon=True)
            self._thread.start()

    def stop(self):
        """Eliberează toate blocările (apelat la ieșire)."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._release()

    # ---- fir de fundal
    def _run(self):
        try:
            self._dbus_inhibit()
            while True:
                self._renew_lease()
                self._reset_x11()
                if self._stop.wait(BEAT):
                    break
        except Exception:
            inhibit_log.exception("inhibit: eroare neașteptată")

    def _dbus_inhibit(self):
        try:
            self._bus = DBusSession()
        except (OSError, DBusError) as e:
            inhibit_log.debug("inhibit: fără session bus (%s)", e)
            return
        got_fdo = False
        for dest, path, iface, sig, release in _BACKENDS:
            if dest == "org.freedesktop.ScreenSaver" and got_fdo:
                continue                    # al doilea path e doar rezervă
            args = (self.app, self.reason) if sig == "ss" else (self.app, 0, self.reason, 4 | 8)
            try:
                res = self._bus.call(dest, path, iface, "Inhibit", sig, args)
            except (OSError, DBusError) as e:
                inhibit_log.debug("inhibit: %s indisponibil (%s)", dest, e)
                continue
            if res:
                self._cookies.append((dest, path, iface, release, res[0]))
                self.active.append(f"dbus:{dest}")
                got_fdo = got_fdo or dest == "org.freedesktop.ScreenSaver"
        inhibit_log.info("inhibit: metode D-Bus active: %s", self.active)

    def _renew_lease(self):
        if not shutil.which("systemd-inhibit"):
            return
        self._leases = [p for p in self._leases if p.poll() is None]
        try:
            p = subprocess.Popen(
                ["systemd-inhibit", "--what=idle:sleep", f"--who={self.app}", f"--why={self.reason}",
                 "--mode=block", "sleep", str(LEASE)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            return
        self._leases.append(p)
        if "systemd-inhibit" not in self.active:
            self.active.append("systemd-inhibit")

    def _reset_x11(self):
        if self._x11 is None:
            self._x11 = X11.create() or False       # False = indisponibil, nu mai încercăm
            if self._x11:
                self.active.append("x11")
        if self._x11:
            try: self._x11.reset_screensaver()
            except Exception: self._x11 = False

    def _release(self):
        if self._bus:
            for dest, path, iface, release, cookie in self._cookies:
                try: self._bus.call(dest, path, iface, release, "u", (cookie,))
                except (OSError, DBusError): pass
            self._cookies.clear()
            self._bus.close()
            self._bus = None
        for p in self._leases:
            if p.poll() is None:
                p.terminate()
        self._leases.clear()


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: core  ·  Logică DVB pură, fără UI: SI/EPG, canale, tunere, scanare, programări
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE core/dvb_si
#   MPEG-TS / DVB SI: filtrarea unui serviciu din transponder, EPG (EIT), SDT, text DVB.
# ──────────────────────────────────────────────────────────────────────────────

def dvb_text(b):
    """Decodează un șir DVB (EN 300 468, anexa A)."""
    enc = None
    if b and b[0] < 0x20:                       # octet de selecție a setului de caractere
        c, b = b[0], b[1:]
        if c == 0x10: enc, b = f"iso-8859-{b[1]}", b[2:]
        else: enc = {0x11: "utf-16-be", 0x15: "utf-8"}.get(c, f"iso-8859-{c + 4}")
    try: s = b.decode(enc or "utf-8")
    except (UnicodeDecodeError, LookupError): s = b.decode("iso-8859-2", "replace")
    return re.sub(r"[\x80-\x9f]", lambda m: "\n" * (m.group() == "\x8a"), s).strip()   # 0x8A = rând nou


bcd = lambda x: (x >> 4) * 10 + (x & 15)


class TSFilter:
    def __init__(self, sid):
        self.sid, self.pmt_pid, self.keep = sid, None, {0}
        self.bufs, self.rest, self.epg = {}, b"", {}
        self.sdt = {}                            # sid -> (service_type, codat?)
        self.country3 = None                     # cod de țară ISO-3 din TOT (ex. «ROU»), pentru logo-uri
        self.genre = {}                          # (început, sfârșit, titlu) -> prima cifră din descriptorul de conținut (1 = film)

    def feed(self, data):
        data, out, i = self.rest + data, bytearray(), 0
        while i + 188 <= len(data):
            if data[i] != 0x47:                  # sincronizare pierdută
                i += 1
                continue
            if not data[i + 1] & 0x80:           # ignoră pachetele marcate cu eroare
                pid = (data[i + 1] & 0x1F) << 8 | data[i + 2]
                if pid in self.keep:
                    out += data[i:i + 188]
                if pid in (0, 0x11, 0x12, 0x14, self.pmt_pid):
                    for s in self.sections(pid, data[i:i + 188]):
                        try: self.parse(pid, s)
                        except Exception: pass
            i += 188
        self.rest = data[i:]
        return bytes(out)

    def sections(self, pid, pkt):
        afc = pkt[3] >> 4 & 3
        pl = pkt[5 + pkt[4]:] if afc & 2 else pkt[4:]
        if not afc & 1 or not pl:
            return
        buf = self.bufs.setdefault(pid, bytearray())
        if pkt[1] & 0x40:                        # începe o secțiune nouă
            buf += pl[1:1 + pl[0]]
            yield from self._drain(buf)
            buf.clear()
            buf += pl[1 + pl[0]:]
        else:
            buf += pl
        yield from self._drain(buf)

    @staticmethod
    def _drain(buf):
        while len(buf) >= 3 and buf[0] != 0xFF:
            n = 3 + ((buf[1] & 0xF) << 8 | buf[2])
            if len(buf) < n: return
            yield bytes(buf[:n])
            del buf[:n]
        if buf[:1] == b"\xff": buf.clear()

    def tot(self, s):
        """TOT (PID 0x14): descriptorul „local time offset” conține țara în care emite multiplexul."""
        end, j = min(len(s) - 4, 10 + ((s[8] & 0xF) << 8 | s[9])), 10
        while j + 2 <= end:
            tag, ln = s[j], s[j + 1]
            if tag == 0x58 and ln >= 3:
                try: self.country3 = bytes(s[j + 2:j + 5]).decode("ascii").upper()
                except UnicodeDecodeError: pass
                return
            j += 2 + ln

    def parse(self, pid, s):
        if pid == 0x14 and s and s[0] == 0x73 and len(s) >= 14:
            self.tot(s)
            return
        if len(s) < 12 or not s[5] & 1:
            return
        t, num = s[0], s[3] << 8 | s[4]
        if pid == 0 and t == 0:                  # PAT: găsește PMT-ul serviciului
            for j in range(8, len(s) - 4, 4):
                if (s[j] << 8 | s[j + 1]) == self.sid:
                    self.pmt_pid = (s[j + 2] & 0x1F) << 8 | s[j + 3]
                    self.keep.add(self.pmt_pid)
        elif pid == self.pmt_pid and t == 2 and num == self.sid:   # PMT: toate PID-urile serviciului
            pids = {(s[8] & 0x1F) << 8 | s[9]}
            i = 12 + ((s[10] & 0x0F) << 8 | s[11])
            while i + 5 <= len(s) - 4:
                pids.add((s[i + 1] & 0x1F) << 8 | s[i + 2])
                i += 5 + ((s[i + 3] & 0xF) << 8 | s[i + 3 + 1])
            self.keep = {0, self.pmt_pid} | pids
        elif pid == 0x12 and (t == 0x4E or 0x50 <= t <= 0x5F) and num == self.sid:
            self.eit(s)
        elif pid == 0x11 and t == 0x42:          # SDT actual: service_type + free_CA_mode
            i = 11
            while i + 5 <= len(s) - 4:
                sid, dl = s[i] << 8 | s[i + 1], (s[i + 3] & 0xF) << 8 | s[i + 4]
                stype, j = None, i + 5
                while j + 2 <= min(i + 5 + dl, len(s) - 4):
                    if s[j] == 0x48 and j + 2 < len(s): stype = s[j + 2]
                    j += 2 + s[j + 1]
                self.sdt[sid] = (stype, bool(s[i + 3] & 0x10))
                i += 5 + dl

    def eit(self, s):
        i = 14
        while i + 12 <= len(s) - 4:
            eid, mjd = s[i] << 8 | s[i + 1], s[i + 2] << 8 | s[i + 3]
            dl = (s[i + 10] & 0xF) << 8 | s[i + 11]
            d, j, name, text, ext, lang = s[i + 12:i + 12 + dl], 0, "", "", b"", None
            genre = None
            while j + 2 <= len(d):
                tag, ln = d[j], d[j + 1]
                b = d[j + 2:j + 2 + ln]
                if tag == 0x4D and lang is None:
                    lang, n = b[:3], b[3]
                    name, text = dvb_text(b[4:4 + n]), dvb_text(b[5 + n:5 + n + b[4 + n]])
                elif tag == 0x4E and (lang is None or b[1:4] == lang):
                    n = b[4]
                    ext += b[6 + n:6 + n + b[5 + n]]
                elif tag == 0x54 and ln >= 2:
                    genre = b[0] >> 4
                j += 2 + ln
            if mjd != 0xFFFF:
                start = (mjd - 40587) * 86400 + bcd(s[i + 4]) * 3600 + bcd(s[i + 5]) * 60 + bcd(s[i + 6])
                dur = bcd(s[i + 7]) * 3600 + bcd(s[i + 8]) * 60 + bcd(s[i + 9])
                self.epg[eid] = (start, start + dur, name, "\n".join(x for x in (text, dvb_text(ext)) if x))
                if genre is not None:
                    self.genre[(start, start + dur, name)] = genre
            i += 12 + dl

    def events(self):
        now = time.time()
        return sorted(e for e in list(self.epg.values()) if e[1] > now)


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE core/dvb_tools
#   Capabilitățile uneltelor DVB instalate.
# ──────────────────────────────────────────────────────────────────────────────

@functools.cache
def zap_all_pids():
    """True dacă dvbv5-zap are -P (tot transponderul): fără el nu există EPG/subtitrări în flux."""
    try:
        r = subprocess.run(["dvbv5-zap", "--help"], capture_output=True, text=True, timeout=5, env=get_clean_env())
        return bool(re.search(r"^\s*-P\b", r.stdout + r.stderr, re.M))
    except (OSError, subprocess.SubprocessError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE core/channels
#   Lista de canale (channels.conf) și metadatele serviciilor (services.json).
# ──────────────────────────────────────────────────────────────────────────────

def load_services():
    try: return json.loads(SERVICES.read_text(encoding="utf-8"))
    except Exception: return {}


def load_channels():
    """(tv, radio, codate). Numele rămân EXACT ca în channels.conf (inclusiv spațiile finale):
    dvbv5-zap caută canalul după numele exact din fișier."""
    cp = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    cp.optionxform = str
    cp.read(CHANNELS, encoding="utf-8")
    svc = load_services()
    tv, radio, locked = [], [], set()
    for n in cp.sections():
        if re.search(r"^SW |SW DL|SmartDTV", n):
            continue
        sec = cp[n]
        sid = sec.get("SERVICE_ID", "").strip()
        stype = sec.get("SERVICE_TYPE", "").strip()
        meta = svc.get(f"{sec.get('FREQUENCY', '').strip()}:{sid}", {})
        is_radio = bool(stype in ("2", "0x2") or meta.get("t") in (2, 0x0A)
                        or ("VIDEO_PID" not in sec and "AUDIO_PID" in sec)       # fără video = radio
                        or re.search(r"\bradio\b|\bfm\b|europa\s*fm", n.lower()))
        if meta.get("ca"):
            locked.add(n)
        (radio if is_radio else tv).append((n, int(sid) if sid.isdigit() else 0))
    tv.sort(key=lambda x: x[0].strip().lower())
    radio.sort(key=lambda x: x[0].strip().lower())
    return tv, radio, locked


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE core/tuners
#   Detectarea tunerelor DVB.
# ──────────────────────────────────────────────────────────────────────────────

def list_frontends():
    return sorted(tuple(map(int, re.findall(r"\d+", str(p)))) for p in Path("/dev/dvb").glob("adapter*/frontend*"))


def probe_tuner(a, f):
    name, systems = "", []
    if shutil.which("dvb-fe-tool"):
        try:
            r = subprocess.run(["dvb-fe-tool", "-a", str(a), "-f", str(f)], capture_output=True, text=True,
                               timeout=5, env=get_clean_env())
            out, grab = r.stdout + "\n" + r.stderr, False
            if m := re.search(r"Device (.+?) \(/dev/dvb", out):
                name = m.group(1).strip()
            for line in out.splitlines():
                if "Supported delivery systems" in line:
                    grab = True
                elif grab:
                    tok = line.strip().strip("[]")
                    if not (re.fullmatch(r"[A-Z0-9_/]+", tok) and line.startswith((" ", "\t"))):
                        break
                    systems.append(tok)
        except Exception:
            pass
    kinds = dict.fromkeys(re.sub(r"^(ISDB|DVB)", r"\1-", s.split("/")[0]) for s in systems)
    label = name or f"adapter{a} / frontend{f}"
    return (f"{label} ({', '.join(kinds)})" if kinds else label), f"adapter{a}/frontend{f}", systems


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE core/scanning
#   Scanarea canalelor, „încălzirea” tunerului și detecția canalelor codate.
# ──────────────────────────────────────────────────────────────────────────────

def scan_init(mode, systems=()):
    """Fișier inițial pentru dvbv5-scan, cu TOT spectrul.
    DVB-C: 58-866 MHz din 8 în 8 MHz (rastrul 114+8k), QAM64 și QAM256 la 6875 kS/s.
    DVB-T / T2: VHF canalele 5-12 (7 MHz) + UHF canalele 21-69 (8 MHz), separat DVB-T și DVB-T2."""
    ent = []
    if mode == "dvbc":
        for mhz in range(58, 867, 8):
            for q in ("QAM/64", "QAM/256"):
                ent.append(["DELIVERY_SYSTEM = DVBC/ANNEX_A", f"FREQUENCY = {mhz * 10**6}",
                            "SYMBOL_RATE = 6875000", f"MODULATION = {q}", "INVERSION = AUTO"])
    else:
        want_t = not systems or "DVBT" in systems
        want_t2 = not systems or "DVBT2" in systems
        chans = [(177_500_000 + 7_000_000 * i, 7_000_000) for i in range(8)] + \
                [(474_000_000 + 8_000_000 * i, 8_000_000) for i in range(49)]
        for fr, bw in chans:
            if want_t2:
                ent.append(["DELIVERY_SYSTEM = DVBT2", f"FREQUENCY = {fr}", f"BANDWIDTH_HZ = {bw}", "INVERSION = AUTO"])
            if want_t:
                ent.append(["DELIVERY_SYSTEM = DVBT", f"FREQUENCY = {fr}", f"BANDWIDTH_HZ = {bw}", "INVERSION = AUTO",
                            "CODE_RATE_HP = AUTO", "CODE_RATE_LP = AUTO", "MODULATION = QAM/AUTO",
                            "TRANSMISSION_MODE = AUTO", "GUARD_INTERVAL = AUTO", "HIERARCHY = NONE"])
    return "".join("[CHANNEL]\n" + "".join(f"\t{l}\n" for l in e) + "\n" for e in ent)


def _stop_proc(p):
    if p.poll() is None:
        p.terminate()
        try: p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()


def warm_up(adapter, channel=None, init=None, maxwait=8.0):
    """\"Bâzâit\" scurt al tunerului: la cold start primul tune/scan eșuează (firmware, demodulator
    neinițializat). Pornim scurt dvbv5-zap (sau dvbv5-scan pe o singură intrare), așteptăm lock-ul,
    apoi îl oprim curat; următoarea pornire reală merge din prima."""
    a, f = re.findall(r"\d+", adapter)[:2]
    tmp = CONF_DIR / "warm.tmp"
    if channel:
        cmd = ["dvbv5-zap", "-c", str(CHANNELS), "-a", a, "-f", f, "-o", "/dev/null", channel]
    else:
        cmd = ["dvbv5-scan", "-a", a, "-f", f, "-o", str(tmp), str(init)]
    for _ in range(2):
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                 errors="replace", env=get_clean_env())
        except OSError:
            return
        locked = threading.Event()

        def rd():
            for line in p.stderr:
                if "0x1f" in line.lower(): locked.set()
        threading.Thread(target=rd, daemon=True).start()
        t0 = time.time()
        while p.poll() is None and time.time() - t0 < maxwait:
            if locked.is_set():
                time.sleep(0.4)
                break
            time.sleep(0.1)
        quick_fail = p.poll() is not None and not locked.is_set() and time.time() - t0 < 3
        _stop_proc(p)
        time.sleep(0.5)
        if not quick_fail:
            break
        time.sleep(1.0)
    tmp.unlink(missing_ok=True)


class ScrambleCounter:
    """Numără pachetele cu date pe anumite PID-uri și câte dintre ele au bitul transport_scrambling_control
    setat. Asta e criteriul real: un canal e codat dacă pachetele lui video/audio chiar vin criptate
    (flag-ul free_CA din SDT e pus greșit de unii furnizori)."""

    def __init__(self, pids):
        self.total, self.scr, self.rest = dict.fromkeys(pids, 0), dict.fromkeys(pids, 0), b""

    def feed(self, data):
        data, i = self.rest + data, 0
        while i + 188 <= len(data):
            if data[i] != 0x47:
                i += 1
                continue
            pid = (data[i + 1] & 0x1F) << 8 | data[i + 2]
            if pid in self.total and not data[i + 1] & 0x80 and data[i + 3] & 0x10:   # are payload
                self.total[pid] += 1
                if data[i + 3] >> 6: self.scr[pid] += 1
            i += 188
        self.rest = data[i:]

    def verdict(self, pid, need=25):
        """True = codat, False = liber, None = nu sunt destule date ca să decidem."""
        t = self.total.get(pid, 0)
        if t < need: return None
        r = self.scr[pid] / t
        return True if r >= 0.8 else False if r <= 0.2 else None


def detect_services(adapter, cancelled, set_proc):
    """Pentru fiecare transponder citește câteva secunde de flux și decide, pe baza pachetelor reale,
    ce canale sunt codate. Din SDT ia doar tipul serviciului (radio/TV). Scrie services.json
    (cheie 'frecvență:service_id'). Canalele despre care nu se poate decide NU sunt marcate."""
    if not zap_all_pids():
        return
    a, f = re.findall(r"\d+", adapter)[:2]
    cp = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    cp.optionxform = str
    cp.read(CHANNELS, encoding="utf-8")
    groups = {}
    for n in cp.sections():
        sec = cp[n]
        fr, sid = sec.get("FREQUENCY", "").strip(), sec.get("SERVICE_ID", "").strip()
        if not (fr and sid.isdigit()):
            continue
        pids = re.findall(r"\d+", sec.get("VIDEO_PID", "")) or re.findall(r"\d+", sec.get("AUDIO_PID", ""))
        g = groups.setdefault(fr, [n, {}])
        g[1][int(sid)] = int(pids[0]) if pids else None
    res = {}
    for fr, (name, svcs) in groups.items():
        if cancelled(): return
        pids = {p for p in svcs.values() if p}
        sdt, cnt = TSFilter(0), ScrambleCounter(pids)
        for _ in range(2):
            p = subprocess.Popen(["dvbv5-zap", "-c", str(CHANNELS), "-a", a, "-f", f, "-r", "-P", "-o", "-", name],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=get_clean_env())
            set_proc(p)
            fd, t0 = p.stdout.fileno(), time.time()
            while time.time() - t0 < 12 and not cancelled():
                if select.select([fd], [], [], 0.5)[0]:
                    d = os.read(fd, 1 << 16)
                    if not d: break
                    sdt.feed(d)
                    cnt.feed(d)
                    enough = all(cnt.total[x] >= 60 for x in pids)
                    if enough and (set(svcs) <= set(sdt.sdt) or time.time() - t0 > 7): break
                elif p.poll() is not None:
                    break
            _stop_proc(p)
            if any(cnt.total.values()) or cancelled(): break
            time.sleep(1.0)
        for sid, pid in svcs.items():
            res[f"{fr}:{sid}"] = {"t": sdt.sdt.get(sid, (None,))[0], "ca": cnt.verdict(pid) if pid else None}
    if not cancelled():
        SERVICES.write_text(json.dumps(res), encoding="utf-8")


def run_scan(ad, mode, systems, *, cancelled, set_proc, wait_warm, is_warm, mark_warm, detect):
    """Scanarea completă (blocantă; se rulează într-un fir). Întoarce (ok, mesaj_eroare, anulat).

    Lista actuală de canale nu e atinsă dacă scanarea e anulată sau eșuează. Callback-urile leagă funcția
    de starea aplicației fără ca acest modul să știe de ea: `cancelled()`, `set_proc(proc)`,
    `wait_warm()` (așteaptă „încălzirea” din fundal), `is_warm()`/`mark_warm()`, `detect()` (marchează
    canalele codate/radio după o scanare reușită)."""
    a, f = re.findall(r"\d+", ad)[:2]
    init = CONF_DIR / f"auto-scan-{mode[-1]}.conf"
    init.write_text(scan_init(mode, systems))
    out = CONF_DIR / "channels.scan.tmp"
    out.unlink(missing_ok=True)
    warm_init = CONF_DIR / "warm-scan.conf"
    warm_init.write_text(init.read_text().split("\n\n")[0] + "\n\n")

    def has_channels():
        try: return out.exists() and bool(re.search(r"^\[", out.read_text(errors="replace"), re.M))
        except OSError: return False

    # 1) „bâzâit” al tunerului (doar dacă nu a fost deja făcut) - evită scanarea de două ori
    wait_warm()
    if not is_warm() and not cancelled():
        warm_up(ad, init=warm_init, maxwait=4.0)
        mark_warm()
    warm_init.unlink(missing_ok=True)
    # 2) scanarea propriu-zisă; reîncearcă singură dacă iese goală/eșuată
    cmd = ["dvbv5-scan", "-a", a, "-f", f, "-o", str(out), str(init)]
    rc, err = -1, ""
    for attempt in range(3):
        if cancelled():
            break
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=get_clean_env())
        set_proc(p)
        if cancelled():
            p.terminate()
        tail = deque(maxlen=20)
        for l in p.stdout:
            line = l.strip()
            if line:
                tail.append(line)
        rc = p.wait()
        if cancelled():
            break
        time.sleep(0.6)
        if rc == 0 and has_channels():
            break
        err = "\n".join(tail) or f"Cod ieșire {rc}"
        if attempt < 2:
            time.sleep(2.0)
    was_cancelled = cancelled()
    ok = (not was_cancelled) and rc == 0 and has_channels()
    if ok:
        os.replace(out, CHANNELS)
        SERVICES.unlink(missing_ok=True)
        try:   # 3) marchează canalele codate / radio (din SDT)
            detect()
        except Exception:
            pass
    else:
        out.unlink(missing_ok=True)
    return ok, err, was_cancelled


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE core/schedule
#   Programarea înregistrărilor din EPG: lista de joburi + deciziile (fără UI, fără Tk, testabil).
#
#   Un job înregistrează un canal de la `start - PRE` până la `end + POST`. Aplicația apelează `plan()` la
#   fiecare tick pentru joburile aflate în fereastra lor și execută acțiunea întoarsă:
#
#       start       -> canalul e pe ecran și nu se înregistrează nimic: pornește înregistrarea
#       tune        -> te uiți la alt canal (sau la nimic): schimbă canalul, apoi reia planul
#       wait        -> s-a schimbat canalul, așteptăm să pornească fluxul
#       merge       -> se înregistrează deja același canal printr-un alt job: prelungește-l pe acela
#       adopt       -> utilizatorul înregistra deja manual același canal: continuă și oprește la sfârșitul jobului
#       cancel_busy -> se înregistrează alt canal: jobul se anulează (nu întrerupem o înregistrare în curs)
#       cancel_fail -> canalul nu a pornit în TUNE_TIMEOUT secunde: jobul se anulează
# ──────────────────────────────────────────────────────────────────────────────

PRE, POST = 120, 120        # secunde înainte de început / după sfârșit
TUNE_TIMEOUT = 40           # cât așteptăm pornirea canalului după o schimbare automată

PENDING, TUNING, ACTIVE = "pending", "tuning", "active"


@dataclass
class Job:
    channel: str
    title: str
    start: float            # începutul emisiunii (epoch), conform EPG
    end: float              # sfârșitul emisiunii (epoch)
    state: str = PENDING
    t_tune: float = 0.0

    @property
    def begin(self):
        """Momentul în care începe înregistrarea."""
        return self.start - PRE

    @property
    def stop(self):
        """Momentul în care se oprește înregistrarea."""
        return self.end + POST

    @property
    def key(self):
        return (self.channel, int(self.start), int(self.end))


@dataclass
class Ctx:
    """Starea aplicației de care depinde decizia."""
    rec_on: bool            # se înregistrează acum (manual sau printr-un job)
    rec_job: object         # jobul care înregistrează acum, sau None (înregistrare manuală / nimic)
    cur: object             # canalul de pe ecran (str) sau None
    has_stream: bool        # există un flux pornit


def plan(job, ctx, now):
    if ctx.rec_on:
        if ctx.rec_job is not None:
            return "merge" if ctx.rec_job.channel == job.channel else "cancel_busy"
        return "adopt" if ctx.cur == job.channel else "cancel_busy"
    if ctx.has_stream and ctx.cur == job.channel:
        return "start"
    if job.state == TUNING:
        return "cancel_fail" if now - job.t_tune > TUNE_TIMEOUT else "wait"
    return "tune"


class RecordingSchedule:
    def __init__(self, path=None):
        self.path, self.jobs = path, []
        self.load()

    # ---- interogări
    def find(self, channel, start, end):
        key = (channel, int(start), int(end))
        return next((j for j in self.jobs if j.key == key), None)

    def due(self, now):
        """Joburile aflate în fereastra lor de înregistrare și încă nepornite."""
        return [j for j in self.jobs if j.state != ACTIVE and j.begin <= now < j.stop]

    def expired(self, now):
        """Joburi nepornite al căror interval a trecut (ex. aplicația era închisă)."""
        return [j for j in self.jobs if j.state != ACTIVE and now >= j.stop]

    def finished(self, now):
        return [j for j in self.jobs if j.state == ACTIVE and now >= j.stop]

    def clash(self, channel, begin, end):
        """Joburile de pe ALT canal a căror fereastră de înregistrare se suprapune cu [begin, end)."""
        return [j for j in self.jobs if j.channel != channel and j.begin < end and begin < j.stop]

    # ---- modificări
    def add(self, channel, title, start, end, now=None):
        """Job nou, sau None dacă emisiunea s-a încheiat deja. Dacă există deja, îl întoarce pe cel existent."""
        now = time.time() if now is None else now
        if end <= now:
            return None
        job = self.find(channel, start, end)
        if job is None:
            job = Job(channel, title, float(start), float(end))
            self.jobs.append(job)
            self.save()
        return job

    def remove(self, job):
        if job in self.jobs:
            self.jobs.remove(job)
            self.save()

    # ---- persistență (ca programările să supraviețuiască unei reporniri)
    def save(self):
        if not self.path:
            return
        try:
            self.path.write_text(json.dumps([[j.channel, j.title, j.start, j.end] for j in self.jobs]), encoding="utf-8")
        except OSError:
            pass

    def load(self, now=None):
        now = time.time() if now is None else now
        self.jobs = []
        if not self.path:
            return
        try:
            for ch, title, s, e in json.loads(self.path.read_text(encoding="utf-8")):
                job = Job(str(ch), str(title), float(s), float(e))
                if job.stop > now:
                    self.jobs.append(job)
        except (OSError, ValueError, TypeError):
            self.jobs = []


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE core/watch
#   „Vreau să vizionez”: la începutul unei emisiuni marcate din EPG, aplicația comută singură pe canalul ei
#   (fără UI, fără Tk, testabil). E independentă de înregistrări: are lista ei (watch.json) și nu înregistrează nimic.
#
#   Jobul e activ de la `start - WATCH_LEAD` până la `end`. Aplicația apelează `watch_plan()` la fiecare tick:
#
#       wait      -> încă nu e ora
#       expired   -> emisiunea s-a încheiat fără să comutăm: jobul dispare în liniște
#       already   -> ești deja pe canal (sau o înregistrare programată îl pune acum): nimic de făcut
#       switch    -> comută pe canalul emisiunii
#       skip_rec  -> se înregistrează alt canal (sau o înregistrare programată pe alt canal e în fereastra ei):
#                    NU comutăm; înregistrarea are prioritate
#       skip_busy -> tunerul e ocupat (scanare): nu comutăm
#
#   Înregistrarea are prioritate (există un singur tuner activ): la programarea unei înregistrări, vizionările suprapuse
#   pe alt canal se anulează (`WatchSchedule.clash()`); invers, o vizionare peste o înregistrare programată se refuză
#   (`RecordingSchedule.clash()`), iar la rulare `watch_plan` nu întrerupe niciodată o înregistrare.
# ──────────────────────────────────────────────────────────────────────────────

WATCH_LEAD = 60             # secunde înainte de începutul emisiunii când comutăm (un minut: nu ne bazăm pe punctualitatea canalelor)


@dataclass
class WatchJob:
    channel: str
    title: str
    start: float            # începutul emisiunii (epoch), conform EPG
    end: float              # sfârșitul emisiunii (epoch)

    @property
    def begin(self):
        """Momentul în care comutăm pe canal."""
        return self.start - WATCH_LEAD

    @property
    def key(self):
        return (self.channel, int(self.start), int(self.end))


@dataclass
class WatchCtx:
    """Starea aplicației de care depinde decizia."""
    rec_on: bool            # se înregistrează acum (manual sau printr-un job)
    cur: object             # canalul de pe ecran (str) sau None
    has_stream: bool        # există un flux pornit
    busy: bool              # tunerul e ocupat cu altceva (scanare)


def watch_plan(job, ctx, now, rec_jobs=()):
    if now >= job.end:
        return "expired"
    if now < job.begin:
        return "wait"
    if ctx.has_stream and ctx.cur == job.channel:
        return "already"
    if any(r.channel == job.channel and r.begin <= now < r.stop for r in rec_jobs):
        return "already"                # înregistrarea programată pe același canal îl pornește ea însăși
    if ctx.rec_on or any(r.channel != job.channel and r.begin <= now < r.stop for r in rec_jobs):
        return "skip_rec"
    if ctx.busy:
        return "skip_busy"
    return "switch"


class WatchSchedule:
    def __init__(self, path=None):
        self.path, self.jobs = path, []
        self.load()

    def find(self, channel, start, end):
        key = (channel, int(start), int(end))
        return next((j for j in self.jobs if j.key == key), None)

    def clash(self, channel, begin, end):
        """Joburile de pe ALT canal a căror fereastră [begin, end) se suprapune cu cea dată."""
        return [j for j in self.jobs if j.channel != channel and j.begin < end and begin < j.end]

    def add(self, channel, title, start, end, now=None):
        """Job nou, sau None dacă emisiunea s-a încheiat. Dacă există deja, îl întoarce pe cel existent."""
        now = time.time() if now is None else now
        if end <= now:
            return None
        job = self.find(channel, start, end)
        if job is None:
            job = WatchJob(channel, title, float(start), float(end))
            self.jobs.append(job)
            self.save()
        return job

    def remove(self, job):
        if job in self.jobs:
            self.jobs.remove(job)
            self.save()

    def save(self):
        if not self.path:
            return
        try:
            self.path.write_text(json.dumps([[j.channel, j.title, j.start, j.end] for j in self.jobs]), encoding="utf-8")
        except OSError:
            pass

    def load(self, now=None):
        now = time.time() if now is None else now
        self.jobs = []
        if not self.path:
            return
        try:
            for ch, title, s, e in json.loads(self.path.read_text(encoding="utf-8")):
                job = WatchJob(str(ch), str(title), float(s), float(e))
                if job.end > now:
                    self.jobs.append(job)
        except (OSError, ValueError, TypeError):
            self.jobs = []


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: player  ·  mpv + dvbv5-zap: redare, script OSC, opțiuni și validare mpv
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE player/osc_script
#   Mini-OSC Lua încorporat în mpv (subtitrare / audio / mute). Se scrie în CONF_DIR la fiecare pornire.
# ──────────────────────────────────────────────────────────────────────────────

OSC_LUA = r'''-- Teleops DVB: mini-OSC cu info mpv, subtitrare, coloană sonoră, difuzor și (cu Timeshift) bara de pauză/derulare.
-- Fișier generat de teleops.py (se rescrie la fiecare pornire).
local L = {sub = "Subtitrare", audio = "Coloană sonoră", off = "Dezactivat"}
local ACC = "FFC040"
local shown, menu, items, timer = false, nil, {}, nil
local last_over, last_hot = false, false
local ov = mp.create_osd_overlay("ass-events")

-- Timeshift: activ doar dacă programul a pornit mpv cu --script-opts-append=teleops-ts=1 (setarea bifată; buffer în RAM sau pe disc).
local TS = mp.get_opt("teleops-ts") == "1" or mp.get_property("options/cache-on-disk", "no") == "yes"
local TS_STEP, TS_SLACK = 10, 4      -- pasul de derulare (s); sub TS_SLACK secunde în urma live-ului suntem „la live”
local ts = {lo = 0, hi = 0, pos = 0, behind = 0, paused = false, flash = 0}
-- Informațiile native mpv (stats.lua, paginile 1-5): rămân pe ecran până la butonul „Exit”
local stats = {on = false, page = 1}

local function I(v) return math.floor(v + 0.5) end
local function esc(s) return (tostring(s):gsub("[{}\\\n]", " ")) end

local function geom()
    local w, h = mp.get_osd_size()
    if not w or not h or w < 50 or h < 50 then return nil end
    return w, h, math.max(0.8, h / 720)
end

local function bar_rects(w, h, k)
    local bw, bh, gap, m = 46 * k, 34 * k, 8 * k, 18 * k
    local x0, y0 = w - m - 4 * bw - 3 * gap, h - m - bh
    local r = {}
    for i, name in ipairs({"info", "sub", "audio", "spk"}) do
        local x = x0 + (i - 1) * (bw + gap)
        r[name] = {x, y0, x + bw, y0 + bh}
    end
    return r
end

local function inside(r, x, y)
    return r ~= nil and x >= r[1] and x <= r[3] and y >= r[2] and y <= r[4]
end

local function menu_layout(w, h, k, bars)
    if not menu then return nil end
    local iw, ih = math.min(380 * k, w - 20 * k), 30 * k
    local maxn = math.max(1, math.floor((bars.sub[2] - 24 * k) / ih) - 1)
    local n = math.min(#items, maxn)
    local right, bottom = bars.spk[3], bars.sub[2] - 8 * k
    local left, top = right - iw, bottom - (n + 1) * ih
    local m = {rect = {left, top, right, bottom}, hdr = {left, top, right, top + ih}, rows = {}}
    for i = 1, n do
        m.rows[i] = {left, top + i * ih, right, top + (i + 1) * ih}
    end
    return m
end

local function ts_layout(w, h, k)
    local bars = bar_rects(w, h, k)
    local bw, bh, gap, m = 34 * k, 34 * k, 6 * k, 18 * k
    local y0 = bars.sub[2]
    local r, x = {}, m
    for _, name in ipairs({"back", "play", "fwd"}) do
        r[name] = {x, y0, x + bw, y0 + bh}
        x = x + bw + gap
    end
    local right = bars.info[1] - 14 * k         -- se oprește înainte de butoanele i / CC / ♪ / difuzor
    r.live = {right - 70 * k, y0, right, y0 + bh}
    r.time = {r.live[1] - gap - 80 * k, y0, r.live[1] - gap, y0 + bh}
    r.track = {x, y0, math.max(x, r.time[1] - gap), y0 + bh}
    return r
end

-- butoanele paginilor de informații mpv (sub eticheta REC, sus-dreapta): 1..5 și Exit
local function st_layout(w, h, k)
    local bw, bh, gap, m = 34 * k, 34 * k, 6 * k, 18 * k
    local ew = 58 * k
    local x = w - m - (5 * bw + 5 * gap + ew)
    local r = {}
    for i = 1, 5 do
        r["p" .. i] = {x, 44 * k, x + bw, 44 * k + bh}
        x = x + bw + gap
    end
    r.exit = {x, 44 * k, x + ew, 44 * k + bh}
    return r
end

-- bara Timeshift se vede: cu bara OSC deschisă (click dreapta), în pauză, în urma live-ului sau 5 s după o comandă
local function ts_visible()
    return TS and (shown or ts.paused or ts.behind > TS_SLACK or mp.get_time() < ts.flash)
end

local function ts_update()
    ts.paused = mp.get_property_bool("pause", false)
    local pos = mp.get_property_number("time-pos")
    local st = mp.get_property_native("demuxer-cache-state")
    if not pos or not st then
        ts.lo, ts.hi, ts.pos, ts.behind = 0, 0, 0, 0
        return
    end
    local ranges = st["seekable-ranges"]
    local r = ranges and ranges[#ranges]
    local lo = (r and r.start) or pos
    local hi = (r and r["end"]) or st["cache-end"] or pos
    if hi < pos then hi = pos end
    if lo > pos then lo = pos end
    ts.lo, ts.hi, ts.pos, ts.behind = lo, hi, pos, hi - pos
end

local function hit(x, y)
    local w, h, k = geom()
    if not w then return nil end
    if shown then
        local bars = bar_rects(w, h, k)
        local m = menu_layout(w, h, k, bars)
        if m then
            for i, r in ipairs(m.rows) do
                if inside(r, x, y) then return "row", i end
            end
            if inside(m.rect, x, y) then return "menu" end
        end
        for name, r in pairs(bars) do
            if inside(r, x, y) then return "btn", name end
        end
    end
    if ts_visible() then
        for name, r in pairs(ts_layout(w, h, k)) do
            if name ~= "time" and inside(r, x, y) then return "ts", name end
        end
    end
    if stats.on then
        for name, r in pairs(st_layout(w, h, k)) do
            if inside(r, x, y) then return "st", name end
        end
    end
    return nil
end

local function rect(x1, y1, x2, y2, color, alpha)
    return string.format("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H%s&\\p1}m 0 0 l %d 0 l %d %d l 0 %d{\\p0}",
        I(x1), I(y1), color, alpha, I(x2 - x1), I(x2 - x1), I(y2 - y1), I(y2 - y1))
end

local function text(x, y, an, size, s, color)
    return string.format("{\\an%d\\pos(%d,%d)\\fs%d\\bord1.2\\shad0\\1c&H%s&\\3c&H000000&}%s",
        an, I(x), I(y), I(size), color, s)
end

local function icon(cx, cy, k, muted)
    local s = I(100 * k)
    local shape = "m 0 6 l 5 6 l 11 0 l 11 18 l 5 12 l 0 12 "
    if muted then
        shape = shape .. "m 14 5 l 15.5 4 l 21.5 13 l 20 14 m 20 4 l 21.5 5 l 15.5 14 l 14 13"
    else
        shape = shape .. "m 14 4 l 16.5 4 l 20 9 l 16.5 14 l 14 14 l 17.5 9"
    end
    return string.format("{\\an5\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\fscx%d\\fscy%d\\p1}%s{\\p0}",
        I(cx), I(cy), muted and "6060FF" or "FFFFFF", s, s, shape)
end

-- icoane Timeshift desenate vectorial (nu depind de fonturi)
local ICON_BACK = "m 9 0 l 0 7 l 9 14 m 18 0 l 9 7 l 18 14"
local ICON_FWD = "m 0 0 l 9 7 l 0 14 m 9 0 l 18 7 l 9 14"
local ICON_PLAY = "m 0 0 l 12 7 l 0 14"
local ICON_PAUSE = "m 0 0 l 4 0 l 4 14 l 0 14 m 8 0 l 12 0 l 12 14 l 8 14"

local function shape(cx, cy, k, color, path)
    local sc = I(100 * k)
    return string.format("{\\an5\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\fscx%d\\fscy%d\\p1}%s{\\p0}",
        I(cx), I(cy), color, sc, sc, path)
end

local function fmt_behind(sec)
    sec = math.max(0, math.floor(sec + 0.5))
    if sec >= 3600 then
        return string.format("-%d:%02d:%02d", math.floor(sec / 3600), math.floor((sec % 3600) / 60), sec % 60)
    end
    return string.format("-%02d:%02d", math.floor(sec / 60), sec % 60)
end

local function ts_draw(ln, w, h, k, mx, my)
    local r = ts_layout(w, h, k)
    local live = ts.behind <= TS_SLACK
    for _, name in ipairs({"back", "play", "fwd", "live"}) do
        local b = r[name]
        local hot = inside(b, mx, my)
        ln[#ln + 1] = rect(b[1], b[2], b[3], b[4], hot and "808080" or "000000", hot and "50" or "70")
        local cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
        if name == "back" then
            ln[#ln + 1] = shape(cx, cy, k, "FFFFFF", ICON_BACK)
        elseif name == "fwd" then
            ln[#ln + 1] = shape(cx, cy, k, "FFFFFF", ICON_FWD)
        elseif name == "play" then
            ln[#ln + 1] = shape(cx, cy, k, "FFFFFF", ts.paused and ICON_PLAY or ICON_PAUSE)
        else
            ln[#ln + 1] = text(cx, cy, 5, 15 * k, live and "● LIVE" or "LIVE", live and "2626DC" or ACC)
        end
    end
    local t, tm = r.track, r.time
    ln[#ln + 1] = rect(t[1], t[2], tm[3], t[4], "000000", "70")                -- fundal pentru bară + timp
    if t[3] - t[1] > 30 * k then
        local mid, th = (t[2] + t[4]) / 2, 8 * k
        local bx0, bx1 = t[1] + 8 * k, t[3] - 8 * k
        local span = ts.hi - ts.lo
        local f = span > 0 and math.max(0, math.min(1, (ts.pos - ts.lo) / span)) or 1
        local px = bx0 + (bx1 - bx0) * f
        ln[#ln + 1] = rect(bx0, mid - th / 2, bx1, mid + th / 2, "808080", "60")
        ln[#ln + 1] = rect(bx0, mid - th / 2, px, mid + th / 2, ACC, "00")
        ln[#ln + 1] = rect(px - 2 * k, mid - 8 * k, px + 2 * k, mid + 8 * k, "FFFFFF", "00")
    end
    ln[#ln + 1] = text((tm[1] + tm[3]) / 2, (tm[2] + tm[4]) / 2, 5, 15 * k,
        fmt_behind(live and 0 or ts.behind), live and "D0D0D0" or ACC)
end

local function st_draw(ln, w, h, k, mx, my)
    for name, r in pairs(st_layout(w, h, k)) do
        local hot = inside(r, mx, my)
        ln[#ln + 1] = rect(r[1], r[2], r[3], r[4], hot and "808080" or "000000", hot and "50" or "70")
        local cur = name == "p" .. stats.page
        ln[#ln + 1] = text((r[1] + r[3]) / 2, (r[2] + r[4]) / 2, 5, 16 * k,
            name == "exit" and "Exit" or name:sub(2), cur and ACC or "FFFFFF")
    end
end

local function build_items(kind)
    local out, any = {}, false
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        if t.type == kind then
            local parts = {}
            if t.lang then parts[#parts + 1] = t.lang:upper() end
            if t.title then parts[#parts + 1] = t.title end
            if t.codec then parts[#parts + 1] = "(" .. t.codec .. ")" end
            local label = t.id .. "  " .. (#parts > 0 and table.concat(parts, " · ") or "?")
            out[#out + 1] = {id = t.id, label = label, sel = t.selected and true or false}
            if t.selected then any = true end
        end
    end
    if kind == "sub" then table.insert(out, 1, {id = "no", label = L.off, sel = not any}) end
    return out
end

local function render()
    local w, h, k = geom()
    local tsv = ts_visible()
    if not w or not (shown or tsv or stats.on) then
        ov:remove()
        return
    end
    ov.res_x, ov.res_y = w, h
    local mx, my = mp.get_mouse_pos()
    local ln = {}
    if shown then
        local bars = bar_rects(w, h, k)
        local sub_on = false
        for _, t in ipairs(mp.get_property_native("track-list") or {}) do
            if t.type == "sub" and t.selected then sub_on = true end
        end
        local muted = mp.get_property_bool("mute", false)
        for _, name in ipairs({"info", "sub", "audio", "spk"}) do
            local r = bars[name]
            local hot = inside(r, mx, my) or menu == name
            ln[#ln + 1] = rect(r[1], r[2], r[3], r[4], hot and "808080" or "000000", hot and "50" or "70")
            local cx, cy = (r[1] + r[3]) / 2, (r[2] + r[4]) / 2
            if name == "info" then
                ln[#ln + 1] = text(cx, cy, 5, 22 * k, "i", stats.on and ACC or "FFFFFF")
            elseif name == "sub" then
                ln[#ln + 1] = text(cx, cy, 5, 17 * k, "CC", sub_on and ACC or "FFFFFF")
            elseif name == "audio" then
                ln[#ln + 1] = text(cx, cy, 5, 22 * k, "♪", "FFFFFF")
            else
                ln[#ln + 1] = icon(cx, cy, k, muted)
            end
        end
        local m = menu_layout(w, h, k, bars)
        if m then
            ln[#ln + 1] = rect(m.rect[1], m.rect[2], m.rect[3], m.rect[4], "000000", "30")
            ln[#ln + 1] = text(m.hdr[1] + 12 * k, (m.hdr[2] + m.hdr[4]) / 2, 4, 15 * k, esc(L[menu]), "B0B0B0")
            for i, r in ipairs(m.rows) do
                local it = items[i]
                if inside(r, mx, my) then ln[#ln + 1] = rect(r[1], r[2], r[3], r[4], "808080", "60") end
                ln[#ln + 1] = text(r[1] + 12 * k, (r[2] + r[4]) / 2, 4, 16 * k,
                    (it.sel and "● " or "   ") .. esc(it.label), it.sel and ACC or "FFFFFF")
            end
        end
    end
    if tsv then ts_draw(ln, w, h, k, mx, my) end
    if stats.on then st_draw(ln, w, h, k, mx, my) end
    ov.data = table.concat(ln, "\n")
    ov:update()
end

-- spune programului când cursorul e pe un buton/meniu (ca să nu mute fereastra la tragere)
local function set_hot(v)
    if v ~= last_hot then
        last_hot = v
        mp.commandv("script-message", "teleops-osc-hot", v and "1" or "0")
    end
end

local function hide()
    menu, shown, last_over = nil, false, false
    set_hot(false)
    render()
end

local function arm()
    if timer then timer:kill() end
    timer = mp.add_timeout(menu and 10 or 5, hide)
end

local function show()
    shown = true
    arm()
    render()
end

-- acțiuni Timeshift: pauză, derulare în buffer (doar în intervalul memorat), salt la live
local function ts_poke()
    ts.flash = mp.get_time() + 5
    ts_update()
    render()
end

local function ts_seek_abs(t)
    ts_update()
    if ts.hi - ts.lo < 1.5 then return end
    t = math.max(ts.lo + 0.5, math.min(ts.hi - 0.5, t))
    mp.commandv("seek", tostring(t), "absolute")
    ts_poke()
end

local function ts_seek_rel(d)
    ts_update()
    ts_seek_abs(ts.pos + d)
end

local function ts_live()
    ts_update()
    if ts.hi - ts.lo >= 1.5 then
        mp.commandv("seek", tostring(math.max(ts.lo + 0.5, ts.hi - 0.5)), "absolute")
    end
    mp.set_property_bool("pause", false)
    ts_poke()
end

local function ts_toggle_pause()
    mp.set_property_bool("pause", not mp.get_property_bool("pause", false))
    ts_poke()
end

local function ts_act(name, x)
    if name == "back" then
        ts_seek_rel(-TS_STEP)
    elseif name == "fwd" then
        ts_seek_rel(TS_STEP)
    elseif name == "play" then
        ts_toggle_pause()
    elseif name == "live" then
        ts_live()
    elseif name == "track" then
        local w, h, k = geom()
        if not w then return end
        local t = ts_layout(w, h, k).track
        local bx0, bx1 = t[1] + 8 * k, t[3] - 8 * k
        if bx1 > bx0 then
            ts_update()
            ts_seek_abs(ts.lo + math.max(0, math.min(1, (x - bx0) / (bx1 - bx0))) * (ts.hi - ts.lo))
        end
    end
end

-- la fiecare 0,5 s: reface bara (poziția se mișcă) și o șterge când nu mai trebuie să se vadă
local ts_drawn = false
local function ts_tick()
    ts_update()
    local vis = ts_visible()
    if vis or ts_drawn then
        render()
        if not vis and not stats.on then
            set_hot(false)
            last_over = false
        end
    end
    ts_drawn = vis
end

local function apply(kind, i)
    local it = items[i]
    if not it then return end
    if kind == "sub" then
        if it.id == "no" then
            mp.set_property("sid", "no")
        else
            mp.set_property("sub-visibility", "yes")
            mp.set_property("sid", tostring(it.id))
        end
    else
        mp.set_property("aid", tostring(it.id))
    end
end

-- mișcarea mouse-ului NU mai arată bara (apare doar la click dreapta); aici doar o ținem vie și urmărim hover-ul
mp.observe_property("mouse-pos", "native", function(_, pos)
    if not pos then return end
    if not shown and not ts_visible() and not stats.on then
        set_hot(false)
        last_over = false
        return
    end
    if not pos.hover then
        set_hot(false)
        return
    end
    if shown then arm() end
    local over = hit(pos.x, pos.y) ~= nil
    set_hot(over)
    if over or last_over then render() end
    last_over = over
end)

-- Informații native mpv (stats.lua). `display-page-N` arată pagina doar câteva secunde (oneshot), deci pentru afișare
-- permanentă: se deschid cu `display-stats-toggle` (rămân până la a doua apăsare) și paginile se schimbă cu tastele
-- paginilor (1-5) pe care stats le ascultă cât sunt afișate. La ieșire revenim la pagina 1, ca deschiderea următoare
-- să înceapă mereu de acolo.
local function stats_open(page)
    if not stats.on then
        mp.commandv("script-binding", "stats/display-stats-toggle")
        stats.on, stats.page = true, 1
    end
    if page ~= stats.page then
        mp.commandv("keypress", tostring(page))
        stats.page = page
    end
    render()
end

local function stats_exit()
    if stats.on then
        if stats.page ~= 1 then mp.commandv("keypress", "1") end
        mp.commandv("script-binding", "stats/display-stats-toggle")
    end
    stats.on, stats.page = false, 1
    set_hot(false)
    last_over = false
    render()
end

local function on_click()
    local x, y = mp.get_mouse_pos()
    local kind, v = hit(x, y)
    if kind == "ts" then
        ts_act(v, x)
        return
    end
    if kind == "st" then
        if v == "exit" then stats_exit() else stats_open(tonumber(v:sub(2))) end
        return
    end
    if not shown then return end
    if kind == "row" then
        apply(menu, v)
        menu = nil
    elseif kind == "btn" then
        if v == "info" then
            menu = nil
            if stats.on then stats_exit() else stats_open(1) end
        elseif v == "spk" then
            mp.commandv("script-message", "toggle-mute")     -- mute-ul îl face programul (aceeași stare ca rotița de volum)
            menu = nil
        elseif menu == v then
            menu = nil
        else
            menu = v
            items = build_items(v)
        end
    elseif kind == "menu" then
        -- click pe antetul/fundalul meniului: nimic
    elseif menu then
        menu = nil
    else
        hide()          -- click în gol cât bara e afișată, fără meniu deschis: o ascundem
        return
    end
    show()
end

local function on_dbl()
    local x, y = mp.get_mouse_pos()
    if hit(x, y) then return end
    mp.commandv("script-message", "toggle-ui")     -- dublu click pe video: ascunde/arată interfața programului
end

mp.add_forced_key_binding("MBTN_LEFT", "teleops-click", on_click)
mp.add_forced_key_binding("MBTN_LEFT_DBL", "teleops-dbl", on_dbl)
mp.add_forced_key_binding("MBTN_RIGHT", "teleops-rclick", function()     -- click dreapta: bara apare/dispare (și nu mai pune pauză)
    if shown then hide() else show() end
end)

local function refresh()
    if not shown then return end
    if menu then items = build_items(menu) end
    render()
end
for _, p in ipairs({"mute", "sid", "aid", "track-list", "osd-dimensions"}) do
    mp.observe_property(p, "native", refresh)
end

mp.register_script_message("teleops-labels", function(a, b, c)
    if a and a ~= "" then L.sub = a end
    if b and b ~= "" then L.audio = b end
    if c and c ~= "" then L.off = c end
end)

-- TV live: fără seek (cu Timeshift, Ctrl+←/→ derulează în buffer). Shift+săgeți și PgUp/PgDn nu mai fac nimic.
-- ←/→ (volum) și ↑/↓ (canal) simple le leagă programul prin IPC (vezi Streamer.KEYS).
-- (Alt+săgeți rămâne pan video, nu e seek.)
local noseek = {"Shift+LEFT", "Shift+RIGHT", "Shift+UP", "Shift+DOWN",
                "Ctrl+UP", "Ctrl+DOWN", "Ctrl+Shift+LEFT", "Ctrl+Shift+RIGHT",
                "PGUP", "PGDWN", "Shift+PGUP", "Shift+PGDWN"}
if not TS then
    noseek[#noseek + 1] = "Ctrl+LEFT"
    noseek[#noseek + 1] = "Ctrl+RIGHT"
end
for _, key in ipairs(noseek) do
    mp.add_forced_key_binding(key, "teleops-noseek-" .. key, function() end)
end

-- Informații despre semnal (stânga jos): rezoluție / scanare / codec video și codec / canale / frecvență audio.
-- Apar când canalul a pornit și se ascund după 15 s; tasta I le arată din nou.
local INFO_SECS = 15
local IL = {video = "Video", audio = "Audio", wait = "se detectează...", noaud = "fără audio"}
local VCODEC = {h264 = "AVC", hevc = "HEVC", mpeg2video = "MPEG-2", mpeg1video = "MPEG-1", mpeg4 = "MPEG-4",
                vc1 = "VC-1", av1 = "AV1", vp9 = "VP9"}
local ACODEC = {mp2 = "MP2", mp3 = "MP3", aac = "AAC", aac_latm = "AAC", ac3 = "AC-3", eac3 = "E-AC-3",
                dts = "DTS", opus = "Opus", flac = "FLAC", vorbis = "Vorbis"}
local CHANS = {[1] = "mono", [2] = "stereo", [3] = "2.1", [4] = "4.0", [5] = "5.0", [6] = "5.1", [7] = "6.1", [8] = "7.1"}
local info_ov = mp.create_osd_overlay("ass-events")
local info_on, info_timer, info_poll, info_started, seen_i = false, nil, nil, false, false

local function selected_track(kind)
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        if t.type == kind and t.selected then return t end
    end
    return nil
end

local function res_class(h)
    if h >= 4000 then return "UHD 8K" end
    if h >= 2000 then return "UHD 4K" end
    if h >= 1400 then return "QHD" end
    if h >= 1000 then return "Full HD" end
    if h >= 700 then return "HD" end
    return "SD"
end

-- „i” dacă semnalul are cadre întrețesute (flag din flux, reținut cât timp rulează sondarea), altfel „p”
local function scan_char(h)
    local il = mp.get_property_native("video-frame-info/interlaced")
    if il ~= nil then
        if il then seen_i = true end
        return seen_i and "i" or "p"
    end
    -- mpv fără video-frame-info: presupunere după formatele obișnuite din broadcast
    return (h >= 1000 and h <= 1100 or h <= 576) and "i" or "p"
end

local function codec_name(map, t)
    local c = t.codec
    if not c then return "?" end
    return map[c] or c:upper()
end

local function info_lines()
    local out = {}
    local vt, at = selected_track("video"), selected_track("audio")
    if vt then
        local vp = mp.get_property_native("video-params")
        local v = IL.wait
        if vp and vp.h then
            v = string.format("%s %d%s / %s", res_class(vp.h), vp.h, scan_char(vp.h), codec_name(VCODEC, vt))
        end
        out[#out + 1] = {IL.video, v}
    end
    if at then
        local ap = mp.get_property_native("audio-params")
        local parts = {codec_name(ACODEC, at)}
        local ch = (ap and ap["channel-count"]) or at["demux-channel-count"]
        local sr = (ap and ap.samplerate) or at["demux-samplerate"]
        if ch then parts[#parts + 1] = CHANS[ch] or (ch .. "ch") end
        if sr then parts[#parts + 1] = string.format("%g kHz", sr / 1000) end
        out[#out + 1] = {IL.audio, table.concat(parts, " / ")}
    else
        out[#out + 1] = {IL.audio, IL.noaud}
    end
    return out
end

local function nchars(s)
    return select(2, s:gsub("[^\128-\191]", ""))
end

local function info_render()
    local w, h, k = geom()
    if not info_on or not w or ts_visible() then
        info_ov:remove()
        return
    end
    local lines = info_lines()
    local fs, pad, m = 17 * k, 10 * k, 18 * k
    local lh = fs * 1.5
    local maxc = 0
    for _, l in ipairs(lines) do
        maxc = math.max(maxc, nchars(l[1] .. ": " .. l[2]))
    end
    local bw, bh = maxc * fs * 0.6 + 2 * pad, #lines * lh + 2 * pad
    local x0, y0 = m, h - m - bh
    local ln = {rect(x0, y0, x0 + bw, y0 + bh, "000000", "70")}
    for i, l in ipairs(lines) do
        ln[#ln + 1] = string.format("{\\an4\\pos(%d,%d)\\fs%d\\bord1.2\\shad0\\3c&H000000&\\1c&HB0B0B0&}%s: {\\1c&HFFFFFF&}%s",
            I(x0 + pad), I(y0 + pad + (i - 0.5) * lh), I(fs), esc(l[1]), esc(l[2]))
    end
    info_ov.res_x, info_ov.res_y = w, h
    info_ov.data = table.concat(ln, "\n")
    info_ov:update()
end

local function info_hide()
    info_on = false
    if info_timer then info_timer:kill() info_timer = nil end
    if info_poll then info_poll:kill() info_poll = nil end
    info_ov:remove()
end

local function info_show()
    info_on = true
    if info_timer then info_timer:kill() end
    if info_poll then info_poll:kill() end
    info_timer = mp.add_timeout(INFO_SECS, info_hide)
    info_poll = mp.add_periodic_timer(0.5, info_render)       -- prinde și flag-ul de întrețesere, care apare după primele cadre
    info_render()
end

-- prima afișare: când sunt cunoscute parametrii video și audio (sau după 6 s, cu ce există)
local function info_try(force)
    if info_started then return end
    local vt, at = selected_track("video"), selected_track("audio")
    if not vt and not at then return end
    local vp, ap = mp.get_property_native("video-params"), mp.get_property_native("audio-params")
    if force or ((not vt or (vp and vp.h)) and (not at or ap)) then
        info_started = true
        info_show()
    end
end

for _, p in ipairs({"video-params", "audio-params", "track-list"}) do
    mp.observe_property(p, "native", function()
        if not info_started then info_try(false) elseif info_on then info_render() end
    end)
end
mp.observe_property("osd-dimensions", "native", function() if info_on then info_render() end end)
mp.add_timeout(6, function() info_try(true) end)

mp.register_script_message("teleops-info-show", info_show)
mp.register_script_message("teleops-info-labels", function(v, a, wait, noaud)
    if v and v ~= "" then IL.video = v end
    if a and a ~= "" then IL.audio = a end
    if wait and wait ~= "" then IL.wait = wait end
    if noaud and noaud ~= "" then IL.noaud = noaud end
end)

-- OSD EPG (stânga sus): canalul, emisiunea curentă cu bară de progres și emisiunea următoare.
-- Python trimite doar datele (teleops-epg); desenul, bara și durata de 15 s sunt aici.
local EL = {now = "ACUM", next = "URMĂTOAREA", rem = "Rămas", loading = "Se încarcă EPG...", na = "Indisponibil"}
local EPG_SECS = 15
local epg = {name = "", ts = true, title = nil, start = 0, stop = 0, ntitle = nil}
local epg_ov = mp.create_osd_overlay("ass-events")
local epg_on, epg_timer = false, nil

-- taie la n caractere UTF-8 (cu „…” la final)
local function ucut(s, n)
    local chars = {}
    for ch in s:gmatch("[\1-\127\194-\244][\128-\191]*") do chars[#chars + 1] = ch end
    if #chars <= n then return s end
    return table.concat(chars, "", 1, math.max(1, n - 1)) .. "…"
end

local function epg_render()
    local w, h, k = geom()
    if not epg_on or not w then
        epg_ov:remove()
        return
    end
    local fs, pad, m = 20 * k, 12 * k, 18 * k
    local lh = fs * 1.5
    local cw_char = fs * 0.58
    local now = os.time()
    local l_now = "▶ " .. EL.now .. ": " .. esc(epg.title or EL.loading)
    local l_next = "⏭ " .. EL.next .. ": " .. esc(epg.ntitle or (epg.ts and EL.loading or EL.na))
    local name = esc(epg.name)
    local rem_txt, prog = "", 0
    if epg.title and epg.stop > epg.start then
        prog = math.max(0, math.min(1, (now - epg.start) / (epg.stop - epg.start)))
        rem_txt = string.format("%s: %d min", EL.rem, math.max(0, math.floor((epg.stop - now) / 60)))
    end
    local cw_max = math.min(w * 0.5, w - 2 * m - 2 * pad)
    local want = math.max(nchars(l_now), nchars(l_next), nchars(name)) * cw_char
    local cw = math.max(18 * fs, math.min(cw_max, want))
    local maxc = math.floor(cw / cw_char)
    local x0, y0 = m, m
    local x, y = x0 + pad, y0 + pad
    local sep = math.max(1, 1.5 * k)
    local bh = pad * 2 + lh * 4 + 8 * k
    local ln = {rect(x0, y0, x0 + cw + 2 * pad, y0 + bh, "000000", "70")}
    local function row(cy, size, body)
        ln[#ln + 1] = string.format("{\\an4\\pos(%d,%d)\\fs%d\\bord1.2\\shad0\\3c&H000000&}%s", I(x), I(cy), I(size), body)
    end
    row(y + lh / 2, fs, "{\\b1\\1c&HFFFFFF&}" .. esc(ucut(name, maxc)))
    y = y + lh
    ln[#ln + 1] = rect(x, y + 2 * k, x + cw, y + 2 * k + sep, "808080", "40")
    y = y + 8 * k
    local lab, body = l_now:match("^(.-: )(.*)$")
    row(y + lh / 2, fs, string.format("{\\1c&H%s&}%s{\\1c&HFFFFFF&}%s", ACC, lab, esc(ucut(body, maxc - nchars(lab)))))
    y = y + lh
    local remw = rem_txt ~= "" and (nchars(rem_txt) * cw_char * 0.85 + 10 * k) or 0
    local barw, barh = cw - remw, 10 * k
    local by = y + (lh - barh) / 2
    ln[#ln + 1] = rect(x, by, x + barw, by + barh, "808080", "60")
    if prog > 0 then ln[#ln + 1] = rect(x, by, x + barw * prog, by + barh, ACC, "00") end
    if rem_txt ~= "" then
        ln[#ln + 1] = string.format("{\\an4\\pos(%d,%d)\\fs%d\\bord1.2\\shad0\\3c&H000000&\\1c&HD0D0D0&}%s",
            I(x + barw + 10 * k), I(y + lh / 2), I(fs * 0.85), esc(rem_txt))
    end
    y = y + lh
    lab, body = l_next:match("^(.-: )(.*)$")
    row(y + lh / 2, fs, string.format("{\\1c&H%s&}%s{\\1c&HFFFFFF&}%s", ACC, lab, esc(ucut(body, maxc - nchars(lab)))))
    epg_ov.res_x, epg_ov.res_y = w, h
    epg_ov.data = table.concat(ln, "\n")
    epg_ov:update()
end

local function epg_hide()
    epg_on = false
    if epg_timer then epg_timer:kill() epg_timer = nil end
    epg_ov:remove()
end

local function epg_show()
    epg_on = true
    if epg_timer then epg_timer:kill() end
    epg_timer = mp.add_timeout(EPG_SECS, epg_hide)
    epg_render()
end

mp.observe_property("osd-dimensions", "native", function() if epg_on then epg_render() end end)
mp.register_script_message("teleops-epg-show", epg_show)
mp.register_script_message("teleops-epg-hide", epg_hide)
mp.register_script_message("teleops-epg", function(name, ts, title, st, en, ntitle)
    epg.name, epg.ts = name or "", ts ~= "0"
    epg.title = (title and title ~= "") and title or nil
    epg.start, epg.stop = tonumber(st) or 0, tonumber(en) or 0
    epg.ntitle = (ntitle and ntitle ~= "") and ntitle or nil
    if epg_on then epg_render() end
end)
mp.register_script_message("teleops-epg-labels", function(now, nxt, rem, loading, na)
    if now and now ~= "" then EL.now = now end
    if nxt and nxt ~= "" then EL.next = nxt end
    if rem and rem ~= "" then EL.rem = rem end
    if loading and loading ~= "" then EL.loading = loading end
    if na and na ~= "" then EL.na = na end
end)

-- „q”, „Q” și Ctrl+C nu mai închid mpv: fereastra video rămâne (programul decide când se oprește redarea)
for _, key in ipairs({"q", "Q", "Ctrl+c"}) do
    mp.add_forced_key_binding(key, "teleops-noquit-" .. key, function() end)
end

-- Banner de canal (↑/↓ pe video): numele canalului ales și o bară care se golește până la comutarea automată.
-- Python trimite doar textul și durata (teleops-banner); desenul și animația sunt aici.
local BN = {text = "", t0 = 0, ms = 3000, wait = false}
local bn_ov = mp.create_osd_overlay("ass-events")
local bn_timer = nil

local function bn_render()
    local w, h, k = geom()
    if not w or BN.text == "" then
        bn_ov:remove()
        return
    end
    local fs, pad = 26 * k, 14 * k
    local cw = fs * 0.6
    local bw = math.min(w - 40 * k, math.max(220 * k, nchars(BN.text) * cw + 2 * pad))
    local bh = fs * 1.5 + 2 * pad + (BN.wait and 10 * k or 0)
    local x0, y0 = (w - bw) / 2, 24 * k
    local ln = {rect(x0, y0, x0 + bw, y0 + bh, "000000", "40")}
    ln[#ln + 1] = text(w / 2, y0 + pad + fs * 0.75, 5, fs, esc(ucut(BN.text, math.floor((bw - 2 * pad) / cw))), "FFFFFF")
    if BN.wait then
        local f = math.max(0, math.min(1, 1 - (mp.get_time() - BN.t0) * 1000 / BN.ms))
        local by = y0 + bh - pad * 0.6 - 4 * k
        ln[#ln + 1] = rect(x0 + pad, by, x0 + bw - pad, by + 4 * k, "808080", "60")
        ln[#ln + 1] = rect(x0 + pad, by, x0 + pad + (bw - 2 * pad) * f, by + 4 * k, ACC, "00")
    end
    bn_ov.res_x, bn_ov.res_y = w, h
    bn_ov.data = table.concat(ln, "\n")
    bn_ov:update()
end

local function bn_hide()
    BN.text = ""
    if bn_timer then bn_timer:kill() bn_timer = nil end
    bn_ov:remove()
end

local function bn_show(txt, ms, wait)
    BN.text, BN.ms, BN.wait, BN.t0 = txt or "", tonumber(ms) or 3000, wait == "1", mp.get_time()
    if BN.text == "" then
        bn_hide()
        return
    end
    if bn_timer then bn_timer:kill() end
    bn_timer = mp.add_periodic_timer(0.1, function()
        if (mp.get_time() - BN.t0) * 1000 >= BN.ms + 150 then bn_hide() else bn_render() end
    end)
    bn_render()
end
mp.register_script_message("teleops-banner", bn_show)
mp.observe_property("osd-dimensions", "native", function() if BN.text ~= "" then bn_render() end end)

if TS then
    -- Timeshift: pauza și derularea sunt permise (buffer mpv); frame-step rămâne blocat
    for _, key in ipairs({"SPACE", "p", "PAUSE", "PLAY", "PLAYPAUSE"}) do
        mp.add_forced_key_binding(key, "teleops-pause-" .. key, ts_toggle_pause)
    end
    mp.add_forced_key_binding(",", "teleops-nostep", function() end)
    mp.add_forced_key_binding("Ctrl+LEFT", "teleops-ts-back", function() ts_seek_rel(-TS_STEP) end, {repeatable = true})
    mp.add_forced_key_binding("Ctrl+RIGHT", "teleops-ts-fwd", function() ts_seek_rel(TS_STEP) end, {repeatable = true})
    mp.add_forced_key_binding("Ctrl+0", "teleops-ts-live", ts_live)
    mp.add_periodic_timer(0.5, ts_tick)
else
    -- Fără Timeshift pauza nu are sens la TV live: o blocăm (SPACE, p, tastele media, frame-step) și o anulăm dacă apare oricum
    for _, key in ipairs({"SPACE", "p", "PAUSE", "PLAY", "PLAYPAUSE", ","}) do
        mp.add_forced_key_binding(key, "teleops-nopause-" .. key, function() end)
    end
    mp.observe_property("pause", "bool", function(_, v)
        if v then mp.set_property_bool("pause", false) end
    end)
end

-- Căutarea „Salt la canal” (J): dacă tastatura a rămas la mpv, toate tastele de text merg la program (teleops-key)
local cap_names = {}
local function capture(on)
    if not on then
        for _, n in ipairs(cap_names) do mp.remove_key_binding(n) end
        cap_names = {}
        return
    end
    if #cap_names > 0 then return end
    local keys = {"SPACE", "BS", "ENTER", "KP_ENTER", "UP", "DOWN", "PGUP", "PGDWN", "ESC", "-", ".",
                  "ă", "â", "î", "ș", "ț", "ş", "ţ", "Ă", "Â", "Î", "Ș", "Ț", "Ş", "Ţ"}
    for c = 48, 57 do keys[#keys + 1] = string.char(c) end
    for c = 65, 90 do keys[#keys + 1] = string.char(c); keys[#keys + 1] = string.char(c + 32) end
    for _, k in ipairs(keys) do
        local name = "teleops-cap-" .. k
        mp.add_forced_key_binding(k, name, function() mp.commandv("script-message", "teleops-key", k) end)
        cap_names[#cap_names + 1] = name
    end
end
mp.register_script_message("teleops-capture", function(v) capture(v == "1") end)
'''


def write_osc_script():
    """Rescrie scriptul pe disc; True dacă a reușit."""
    try:
        OSC_PATH.write_text(OSC_LUA, encoding="utf-8")
        return True
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE player/mpv_options
#   Opțiunile mpv oferite în dialogul „Configurează MPV” și transformarea lor în linii de mpv.conf.
#
#   Strat „player”, fără Tkinter: dialogul (secțiunea ui/mpv_dialog) se construiește din OPTIONS, iar
#   `render_block()` produce liniile scrise în blocul gestionat din mpv.conf (secțiunea config/mpv_conf).
#   Ca să adaugi o opțiune: o declari în OPTIONS, îi tratezi valoarea în `render_block()` și adaugi
#   textele în secțiunea i18n/strings_mpv (cheile `mo_<key>`, opțional `mh_<key>` pentru indiciu).
#
#   Valoarea „implicit” (șirul gol sau 0) înseamnă „nu scrie nimic”: rămâne ce e în mpv.conf/mpv.
# ──────────────────────────────────────────────────────────────────────────────

GROUPS = ("video", "color", "audio", "sub", "stream", "advanced")


@dataclass(frozen=True)
class Opt:
    key: str
    group: str                      # unul din GROUPS
    kind: str                       # "choice" | "slider" | "text" | "multiline"
    choices: tuple = ()             # (valoare, etichetă): "@cheie" = text tradus, None = valoarea însăși
    lo: int = 0                     # slider: limitele, pasul și valoarea „implicită” (cea la care nu se scrie nimic)
    hi: int = 0
    step: int = 1
    default: int = 0
    unit: str = ""
    implicit: bool = False          # slider: la valoarea implicită afișează „implicit” în loc de număr
    allow: str = r"A-Za-z,\-"       # text: caracterele permise (conținut de clasă regex)


_DEF = ("", "@mc_default")
_YN = (("yes", "@mc_yes"), ("no", "@mc_no"))


def _c(*pairs):
    return (_DEF, *pairs)


OPTIONS = (
    # ---- Video
    Opt("profile", "video", "choice", _c(("fast", "@mc_prof_fast"), ("gpu-hq", "@mc_prof_hq"))),
    Opt("hwdec", "video", "choice", _c(
        ("auto-safe", None), ("auto", None), ("auto-copy", None), ("vaapi", None), ("vaapi-copy", None),
        ("nvdec", None), ("nvdec-copy", None), ("vdpau", None), ("vdpau-copy", None), ("no", "@mc_hw_no"))),
    Opt("deint_mode", "video", "choice", _c(
        ("off", "@mc_dm_off"), ("interlaced", "@mc_dm_interlaced"), ("all", "@mc_dm_all"))),
    Opt("deint_method", "video", "choice", (
        ("mpv", "@mc_dmt_mpv"), ("bwdif", "bwdif"), ("yadif", "yadif"))),
    Opt("deint_rate", "video", "choice", (
        ("frame", "@mc_dr_frame"), ("field", "@mc_dr_field"))),
    Opt("deint_parity", "video", "choice", (
        ("auto", "auto"), ("tff", "@mc_par_tff"), ("bff", "@mc_par_bff"))),
    Opt("scale", "video", "choice", _c(
        ("bilinear", "bilinear"), ("spline36", "spline36"), ("ewa_lanczos", "ewa_lanczos"),
        ("ewa_lanczossharp", "ewa_lanczossharp"))),
    Opt("cscale", "video", "choice", _c(
        ("bilinear", "bilinear"), ("spline36", "spline36"), ("ewa_lanczos", "ewa_lanczos"))),
    Opt("dscale", "video", "choice", _c(
        ("bilinear", "bilinear"), ("mitchell", "mitchell"), ("catmull_rom", "catmull_rom"))),
    Opt("smooth", "video", "choice", _c(("off", "@mc_sm_off"), ("on", "@mc_sm_on"))),
    Opt("deband", "video", "choice", _c(*_YN)),
    Opt("aspect", "video", "choice", _c(
        ("4:3", "4:3"), ("16:9", "16:9"), ("16:10", "16:10"), ("2.35:1", "2.35:1"))),
    Opt("panscan", "video", "slider", lo=0, hi=100, step=5, default=0, unit="%"),
    # ---- Culori
    Opt("levels", "color", "choice", _c(
        ("auto", "auto"), ("limited", "limited (16–235)"), ("full", "full (0–255)"))),
    Opt("trc", "color", "choice", _c(
        ("auto", "auto"), ("srgb", "srgb"), ("bt.1886", "bt.1886"), ("gamma2.2", "gamma2.2"))),
    Opt("prim", "color", "choice", _c(
        ("auto", "auto"), ("bt.709", "bt.709"), ("bt.601-625", "bt.601-625 (PAL)"), ("display-p3", "display-p3"))),
    Opt("tone_mapping", "color", "choice", _c(
        ("auto", "auto"), ("bt.2390", "bt.2390"), ("hable", "hable"), ("reinhard", "reinhard"),
        ("mobius", "mobius"), ("clip", "clip"))),
    Opt("hdr_peak", "color", "choice", _c(*_YN)),
    Opt("icc_auto", "color", "choice", _c(*_YN)),
    Opt("brightness", "color", "slider", lo=-100, hi=100),
    Opt("contrast", "color", "slider", lo=-100, hi=100),
    Opt("saturation", "color", "slider", lo=-100, hi=100),
    Opt("gamma", "color", "slider", lo=-100, hi=100),
    Opt("hue", "color", "slider", lo=-100, hi=100),
    # ---- Audio
    Opt("audio_channels", "audio", "choice", _c(
        ("stereo", "stereo"), ("auto-safe", "auto-safe"), ("auto", "auto"), ("5.1", "5.1"))),
    Opt("downmix_norm", "audio", "choice", _c(*_YN)),
    Opt("audio_dyn", "audio", "choice", _c(("dynaudnorm", "@mc_dyn_norm"), ("compressor", "@mc_dyn_comp"))),
    Opt("audio_delay", "audio", "slider", lo=-2000, hi=2000, step=10, default=0, unit="ms"),
    Opt("volume_max", "audio", "slider", lo=100, hi=200, step=5, default=130, unit="%"),
    Opt("alang", "audio", "text"),
    Opt("ao", "audio", "choice", _c(("pipewire", None), ("pulse", None), ("alsa", None))),
    Opt("audio_device", "audio", "text", allow=r"\w./:@\-"),
    Opt("spdif", "audio", "choice", _c(("ac3", None), ("ac3,eac3", None), ("ac3,eac3,dts", None))),
    Opt("audio_samplerate", "audio", "choice", _c(("44100", "44100 Hz"), ("48000", "48000 Hz"), ("96000", "96000 Hz"))),
    # ---- Subtitrări
    Opt("slang", "sub", "text"),
    Opt("sub_size", "sub", "slider", lo=0, hi=120, step=1, default=0, unit="px", implicit=True),
    Opt("sub_color", "sub", "choice", _c(
        ("1.0/1.0/1.0", "@mc_col_white"), ("1.0/1.0/0.0", "@mc_col_yellow"),
        ("0.0/1.0/1.0", "@mc_col_cyan"), ("0.0/1.0/0.0", "@mc_col_green"))),
    Opt("sub_border", "sub", "slider", lo=-1, hi=10, step=1, default=-1, unit="px", implicit=True),
    Opt("sub_bold", "sub", "choice", _c(*_YN)),
    Opt("sub_font", "sub", "text", allow=r"\w .\-"),
    Opt("sub_pos", "sub", "slider", lo=0, hi=100, step=1, default=100, unit="%"),
    Opt("sub_delay", "sub", "slider", lo=-5000, hi=5000, step=50, default=0, unit="ms"),
    # ---- Flux și cache
    Opt("probe", "stream", "choice", _c(
        ("fast", "@mc_pr_fast"), ("balanced", "@mc_pr_bal"), ("full", "@mc_pr_full"))),
    Opt("cache", "stream", "choice", _c(("yes", "@mc_yes"), ("no", "@mc_no"), ("auto", "auto"))),
    Opt("cache_pause", "stream", "choice", _c(*_YN)),
    Opt("readahead", "stream", "slider", lo=0, hi=120, step=1, default=0, unit="s", implicit=True),
    Opt("demuxer_max", "stream", "choice", _c(
        ("8MiB", "8 MiB"), ("32MiB", "32 MiB"), ("128MiB", "128 MiB"), ("512MiB", "512 MiB"))),
    # ---- Avansat
    Opt("framedrop", "advanced", "choice", _c(
        ("vo", None), ("decoder", None), ("decoder+vo", None), ("no", "@mc_no"))),
    Opt("vd_threads", "advanced", "slider", lo=0, hi=16, step=1, default=0, implicit=True),
    Opt("vd_fast", "advanced", "choice", _c(*_YN)),
    Opt("skiploopfilter", "advanced", "choice", _c(("nonref", None), ("all", None))),
    Opt("audio_buffer", "advanced", "slider", lo=0, hi=1000, step=10, default=0, unit="ms", implicit=True),
    Opt("video_latency", "advanced", "choice", _c(*_YN)),
    Opt("cursor_autohide", "advanced", "choice", _c(
        ("1000", "1 s"), ("3000", "3 s"), ("no", "@mc_never"), ("always", "@mc_always"))),
    Opt("stop_screensaver", "advanced", "choice", _c(*_YN)),
    Opt("log_file", "advanced", "choice", _c(("yes", "@mc_yes"))),
    Opt("log_level", "advanced", "choice", _c(("warn", None), ("info", None), ("v", None))),
    Opt("extra", "advanced", "multiline"),
)
BY_KEY = {o.key: o for o in OPTIONS}

# „Analiză flux” la pornirea canalului: (probesize în octeți, analyzeduration în secunde)
PROBE = {"fast": (2_000_000, 2.0), "balanced": (5_000_000, 5.0), "full": (10_000_000, 10.0)}

# Alegeri potrivite pentru recepție TV: decodare hardware cu rezervă, deinterlace automat doar pe cadrele
# marcate interlaced (mpv alege hardware dacă se poate, altfel yadif) și analiză completă a fluxului
# (necesară ca subtitrările DVB și toate pistele audio să fie detectate).
RECOMMENDED = {"hwdec": "auto-safe", "deint_mode": "interlaced", "deint_method": "mpv",
               "deint_rate": "frame", "deint_parity": "auto", "probe": "full"}

_EXTRA_LINE = re.compile(r"^[A-Za-z0-9][\w.\-]*(=[^\n]*)?$")   # `cheie=valoare` sau `cheie`; fără secțiuni [..] și comentarii
MAX_EXTRA_LINES = 40


def _choice_values(opt):
    return {v for v, _ in opt.choices}


def clean_extra(text):
    """Liniile suplimentare valide din câmpul „extra” (fără markere, secțiuni sau caractere de control)."""
    out = []
    for line in str(text or "").splitlines():
        line = "".join(c for c in line if c.isprintable()).strip()
        if line and "TELEOPS-DVB" not in line and _EXTRA_LINE.match(line):
            out.append(line[:200])
    return "\n".join(out[:MAX_EXTRA_LINES])


def clean_mpv_opts(opts):
    """Elimină cheile necunoscute și valorile invalide sau „implicite”. Întoarce un dict nou."""
    out = {}
    for k, v in (opts or {}).items():
        o = BY_KEY.get(k)
        if o is None:
            continue
        if o.kind == "choice":
            if isinstance(v, str) and v and v in _choice_values(o):
                out[k] = v
        elif o.kind == "slider":
            try: n = max(o.lo, min(int(float(v)), o.hi))
            except (TypeError, ValueError): continue
            n = o.lo + round((n - o.lo) / o.step) * o.step
            if n != o.default:
                out[k] = n
        elif o.kind == "multiline":
            s = clean_extra(v)
            if s:
                out[k] = s
        else:   # text: doar caracterele permise; fără newline-uri
            s = re.sub(rf"[^{o.allow}]", "", str(v or "")).strip(", ")[:120]
            if s:
                out[k] = s
    return out


def render_block(opts):
    """Liniile `cheie=valoare` pentru mpv.conf. Lista goală = nu e nimic de scris."""
    o, lines = clean_mpv_opts(opts), []

    def put(k, v):
        lines.append(f"{k}={v}")

    if "profile" in o:                      # primul: un profil resetează opțiunile pe care le setează
        put("profile", o["profile"])
    if "hwdec" in o:
        put("hwdec", o["hwdec"])

    # --- deinterlace
    mode = o.get("deint_mode")
    if mode == "off":
        put("deinterlace", "no")
    elif mode in ("interlaced", "all"):
        method = o.get("deint_method", "mpv")
        if method == "mpv":                 # filtrul automat al mpv: hardware dacă hwdec permite, altfel yadif
            put("deinterlace", "yes")
        else:
            rate = "send_field" if o.get("deint_rate") == "field" else "send_frame"
            parity = o.get("deint_parity", "auto")
            put("deinterlace", "no")        # evită filtrarea dublă dacă mpv.conf are deja deinterlace=yes
            put("vf-append", f"{method}=mode={rate}:parity={parity}:deint={'all' if mode == 'all' else 'interlaced'}")

    # --- scalare și imagine
    for key in ("scale", "cscale", "dscale"):
        if key in o:
            put(key, o[key])
    if o.get("smooth") == "off":
        put("video-sync", "audio")
        put("interpolation", "no")
    elif o.get("smooth") == "on":
        put("video-sync", "display-resample")
        put("interpolation", "yes")
        put("tscale", "oversample")
    if "deband" in o:
        put("deband", o["deband"])
    if "aspect" in o:
        put("video-aspect-override", o["aspect"])
    if "panscan" in o:
        put("panscan", f"{o['panscan'] / 100:g}")

    # --- culori
    for key, mpv_key in (("levels", "video-output-levels"), ("trc", "target-trc"), ("prim", "target-prim"),
                         ("tone_mapping", "tone-mapping"), ("hdr_peak", "hdr-compute-peak"),
                         ("icc_auto", "icc-profile-auto")):
        if key in o:
            put(mpv_key, o[key])
    for key in ("brightness", "contrast", "saturation", "gamma", "hue"):
        if key in o:
            put(key, o[key])

    # --- audio
    for key, mpv_key in (("audio_channels", "audio-channels"), ("downmix_norm", "audio-normalize-downmix")):
        if key in o:
            put(mpv_key, o[key])
    if o.get("audio_dyn") == "dynaudnorm":
        put("af-append", "dynaudnorm")
    elif o.get("audio_dyn") == "compressor":
        put("af-append", "acompressor=threshold=0.1:ratio=4:makeup=2")
    if "audio_delay" in o:
        put("audio-delay", f"{o['audio_delay'] / 1000:g}")
    if "volume_max" in o:
        put("volume-max", o["volume_max"])
    for key, mpv_key in (("alang", "alang"), ("ao", "ao"), ("audio_device", "audio-device"),
                         ("spdif", "audio-spdif"), ("audio_samplerate", "audio-samplerate")):
        if key in o:
            put(mpv_key, o[key])

    # --- subtitrări
    for key, mpv_key in (("slang", "slang"), ("sub_size", "sub-font-size"), ("sub_color", "sub-color"),
                         ("sub_border", "sub-border-size"), ("sub_bold", "sub-bold"), ("sub_font", "sub-font"),
                         ("sub_pos", "sub-pos")):
        if key in o:
            put(mpv_key, o[key])
    if "sub_delay" in o:
        put("sub-delay", f"{o['sub_delay'] / 1000:g}")

    # --- flux și cache
    if "probe" in o:
        size, dur = PROBE[o["probe"]]
        put("demuxer-lavf-probesize", size)
        put("demuxer-lavf-analyzeduration", dur)
    for key, mpv_key in (("cache", "cache"), ("cache_pause", "cache-pause"), ("demuxer_max", "demuxer-max-bytes")):
        if key in o:
            put(mpv_key, o[key])
    if "readahead" in o:
        put("demuxer-readahead-secs", o["readahead"])

    # --- avansat
    for key, mpv_key in (("framedrop", "framedrop"), ("vd_threads", "vd-lavc-threads"), ("vd_fast", "vd-lavc-fast"),
                         ("skiploopfilter", "vd-lavc-skiploopfilter"), ("video_latency", "video-latency-hacks"),
                         ("cursor_autohide", "cursor-autohide"), ("stop_screensaver", "stop-screensaver")):
        if key in o:
            put(mpv_key, o[key])
    if "audio_buffer" in o:
        put("audio-buffer", f"{o['audio_buffer'] / 1000:g}")
    if "log_file" in o:
        put("log-file", CONF_DIR / "mpv.log")
    if "log_level" in o:
        put("msg-level", f"all={o['log_level']}")
    lines.extend(o.get("extra", "").splitlines())
    return lines


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE player/mpv_check
#   Validarea unei configurații mpv înainte s-o salvăm: pornește scurt mpv pe o sursă de test.
#
#   Dacă mpv.conf are o opțiune greșită, mpv refuză să pornească, iar în aplicație asta s-ar vedea doar
#   ca „nu apare imaginea”. Verificăm înainte, cu fișierul candidat, fără ecran și fără sunet (vo=null/ao=null).
# ──────────────────────────────────────────────────────────────────────────────

# o sursă video (filtre vf, scalare, culori...) și una audio (filtre af): fiecare își pornește propriul lanț
_SOURCES = ("av://lavfi:color=c=black:s=64x64:r=25:d=0.4", "av://lavfi:sine=frequency=440:duration=0.4")


def validate_mpv_conf(mpv_cmd, conf_text, timeout=10):
    """Verifică `conf_text` (de regulă doar blocul generat de noi, ca greșelile din restul mpv.conf să nu conteze).
    (True, "") dacă mpv acceptă configurația; (False, mesaj) dacă nu; (None, motiv) dacă nu s-a putut verifica."""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONF_DIR / "mpv.conf.check"
    try:
        tmp.write_text(conf_text, encoding="utf-8")
        for source in _SOURCES:
            cmd = [*mpv_cmd, "--no-config", f"--include={tmp}",
                   # după include, ca să anuleze ce ar împiedica ieșirea (ex. keep-open=yes din mpv.conf)
                   "--vo=null", "--ao=null", "--keep-open=no", "--idle=no", "--pause=no", "--input-terminal=no",
                   "--msg-level=all=error", source]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                                   stdin=subprocess.DEVNULL, env=get_clean_env())
            except subprocess.TimeoutExpired:
                return None, "timeout"
            except OSError as e:
                return None, str(e)
            err = (r.stderr + r.stdout).strip()
            if r.returncode != 0 or err:
                return False, err[-600:] or f"mpv: cod {r.returncode}"
        return True, ""
    finally:
        tmp.unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE player/streamer
#   Redarea unui canal: dvbv5-zap -> (filtru TS) -> mpv încorporat în fereastra Tk, cu control prin IPC.
# ──────────────────────────────────────────────────────────────────────────────

IPC_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "app/io.mpv.Mpv"
GPU_CONTEXT = os.environ.get("TELEOPS_GPU_CONTEXT", "x11egl")   # mpv încorporat cere X11 (XWayland sub Wayland)
TIMESHIFT_DIR = Path.home() / ".cache" / "TeleopsDVB" / "timeshift"     # bufferul Timeshift de pe disc (îl șterge mpv la ieșire)
# mpv din Flatpak nu vede ~/.cache: în sandbox are doar propriul director de cache (același drum pe gazdă și în sandbox),
# altfel nu poate crea fișierul bufferului și cade în tăcere pe memorie (în info mpv: „Disk Cache: (disabled)”)
TIMESHIFT_DIR_FLATPAK = Path.home() / ".var" / "app" / "io.mpv.Mpv" / "cache" / "TeleopsDVB" / "timeshift"


def timeshift_dir(mpv_cmd):
    """Directorul bufferului de pe disc, vizibil de mpv-ul lansat cu `mpv_cmd`."""
    return TIMESHIFT_DIR_FLATPAK if mpv_cmd and Path(str(mpv_cmd[0])).name == "flatpak" else TIMESHIFT_DIR
TIMESHIFT_SIZES = (512, 1024, 2048, 4096)
TIMESHIFT_RAM_MAX = 1024                    # MB: limita bufferului în RAM         # MB: alegerile din setări (se aplică la --demuxer-max-bytes și --demuxer-max-back-bytes)
FEED_CHUNKS = 512                           # Timeshift: câte bucăți de 64 KiB (~32 MiB) așteaptă la mpv în pauză lungă


_FP_WRITE_CACHE = {}
_MPV_OPTS, _MPV_OPTS_LOCK = {}, threading.Lock()


def mpv_options(mpv_cmd):
    """Numele opțiunilor cunoscute de mpv-ul lansat cu `mpv_cmd` (din `--list-options`), ținute minte; None dacă nu se poate afla.
    Contează pentru bufferul Timeshift pe disc: `--demuxer-cache-dir` există abia din mpv 0.37 (înainte: `--cache-dir`),
    iar o opțiune necunoscută face mpv-ul să nu pornească deloc."""
    key = tuple(mpv_cmd)
    with _MPV_OPTS_LOCK:
        if key not in _MPV_OPTS:
            try:
                out = subprocess.run([*mpv_cmd, "--no-config", "--list-options"], capture_output=True, text=True, timeout=20,
                                     env=get_clean_env(), stdin=subprocess.DEVNULL).stdout
                _MPV_OPTS[key] = set(re.findall(r"^\s*--([a-z0-9-]+)", out, re.M)) or None
            except (OSError, subprocess.SubprocessError):
                _MPV_OPTS[key] = None
        return _MPV_OPTS[key]


def _xdg_dir(name):
    try:
        out = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True, timeout=3, env=get_clean_env()).stdout.strip()
        if out:
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / name.capitalize()


def flatpak_can_write(path):
    """True dacă mpv din Flatpak poate scrie în `path`: după permisiunile aplicației (`filesystems=`) și override-urile
    utilizatorului. Verificare aproximativă (host, home, xdg-*, căi); la îndoială, False."""
    path = Path(path)
    key = str(path)
    if key in _FP_WRITE_CACHE:
        return _FP_WRITE_CACHE[key]
    entries = []
    for cmd in (["flatpak", "info", "--show-permissions", "io.mpv.Mpv"], ["flatpak", "override", "--user", "--show", "io.mpv.Mpv"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, env=get_clean_env()).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.splitlines():
            if line.startswith("filesystems="):
                entries += [e for e in line.split("=", 1)[1].split(";") if e]
    xdg = {"xdg-videos": "VIDEOS", "xdg-documents": "DOCUMENTS", "xdg-download": "DOWNLOAD", "xdg-music": "MUSIC",
           "xdg-pictures": "PICTURES", "xdg-desktop": "DESKTOP"}
    ok = False
    for e in entries:
        neg = e.startswith("!")
        name, _, mode = e.lstrip("!").partition(":")
        if name == "host":
            base = Path("/")
        elif name == "home":
            base = Path.home()
        elif name in xdg:
            base = _xdg_dir(xdg[name])
        elif name.startswith("~/"):
            base = Path.home() / name[2:]
        elif name.startswith("/"):
            base = Path(name)
        else:
            continue
        if base != path and base not in path.parents:
            continue
        ok = False if neg else mode not in ("ro",)
    _FP_WRITE_CACHE[key] = ok
    return ok


def pick_timeshift_dir(mpv_cmd, wanted):
    """(director, a_căzut_pe_cache). `wanted` = dosarul ales (înregistrări/timeshift); dacă mpv nu poate scrie acolo
    (Flatpak fără acces, drepturi), bufferul merge în cache-ul programului."""
    fallback = timeshift_dir(mpv_cmd)
    flat = Path(str(mpv_cmd[0])).name == "flatpak" if mpv_cmd else False
    if wanted and not (flat and not flatpak_can_write(wanted)):
        try:
            Path(wanted).mkdir(parents=True, exist_ok=True)
            if os.access(wanted, os.W_OK):
                return Path(wanted), False
        except OSError:
            pass
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback, bool(wanted)


def clean_timeshift_dir(extra=None):
    """Șterge resturile bufferului (rămase dacă mpv a fost oprit brusc). Apelat la pornire și la ieșire: o singură instanță rulează.
    În dosarul înregistrărilor (`extra`) șterge doar fișierele de cache ale mpv (mpv-*)."""
    for d, only_mpv in ((TIMESHIFT_DIR, False), (TIMESHIFT_DIR_FLATPAK, False), (extra, True)):
        if d is None:
            continue
        try:
            for f in Path(d).iterdir():
                if f.is_file() and (not only_mpv or f.name.startswith("mpv-")):
                    f.unlink(missing_ok=True)
        except OSError:
            pass


class Streamer:
    OBSERVED = ("volume-max", "volume", "mute", "vo-configured", "audio-params")
    # mesaj -> tastele mpv care îl trimit (cât timp mpv are focusul, Tk nu primește tastele; „i” simplu rămâne nativ mpv)
    KEYS = {"show-info-osd": ("i", "I"), "toggle-ui": (".", "MBTN_LEFT_DBL"), "toggle-fs": ("f", "F", "F11"),
            "toggle-rec": ("Ctrl+r", "Ctrl+R"), "show-epg": ("Ctrl+i", "Ctrl+I"),
            "vol-up": ("WHEEL_UP", "RIGHT"), "vol-down": ("WHEEL_DOWN", "LEFT"), "quit-app": ("Ctrl+X", "Ctrl+Shift+x", "Ctrl+Shift+X"),
            "prev-channel": ("BS",), "jump-channel": ("j", "J"), "toggle-mute": ("m", "M"),
            "toggle-info": ("Ctrl+h", "Ctrl+H"),
            "ch-up": ("UP",), "ch-down": ("DOWN",), "ch-enter": ("ENTER", "KP_ENTER"), "ch-cancel": ("ESC",)}

    def __init__(self, mpv_cmd, adapter, channel, sid, props, on_prop, get_lang_func=None, wid=None, on_msg=None, tone=(0, 0), fast=False, timeshift=0, ts_disk=True, ts_dir=None):
        self.props, self.on_prop, self.conn = dict(props), on_prop, None
        self.timeshift = int(timeshift or 0)        # MB de buffer Timeshift (0 = oprit)
        self.ts_fallback = False                    # bufferul pe disc a trebuit mutat în cache-ul programului
        self.ts_nodisk = False                      # mpv-ul instalat nu știe cache pe disc: Timeshift a trecut pe RAM
        self._feed = queue.Queue(FEED_CHUNKS) if self.timeshift else None
        self.tone = tuple(tone)
        self.on_msg = on_msg or (lambda *_: None)
        self.osc_hot = False        # cursorul e pe un buton/meniu al mini-OSC-ului din mpv
        self.rec, self.lock = None, threading.Lock()
        self.t0, self.got_data = time.time(), False
        self.channel_name = channel
        self.get_lang = get_lang_func or (lambda: "Română")
        self.ts = TSFilter(sid) if sid and zap_all_pids() else None
        a, f = re.findall(r"\d+", adapter)
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        self.sock_name = f"teleops-{os.getpid()}-{os.urandom(4).hex()}.sock"     # unic: cel vechi se închide în fundal
        self.sock = str(IPC_DIR / self.sock_name)

        zap_cmd = ["dvbv5-zap", "-c", str(CHANNELS), "-a", a, "-f", f, "-r", "-P" if self.ts else "-p", "-o", "-", channel]
        
        # Tunerul pornește imediat, fără așteptări aici: verificarea lui (și reîncercarea) se face în `_boot`,
        # în timp ce mpv se inițializează în paralel.
        self._life, self._stopped, self._booting = threading.Lock(), False, True
        self.zap = subprocess.Popen(zap_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=get_clean_env())

        mpv = [*mpv_cmd, "--no-terminal", f"--include={MPV_CONF}", f"--input-ipc-server={self.sock}",
               "--no-input-default-bindings", "--input-conf=/dev/null",      # fără taste implicite mpv (consolă, o, i...): doar cele ale programului
               "--sid=auto", "--sub-visibility=yes", f"--volume={props['volume']}",
               f"--mute={'yes' if props['mute'] else 'no'}", f"--title=TV - {channel.strip()}"]
        if fast:    # pornire rapidă: flux MPEG-TS cunoscut (fără ghicirea formatului), analiză scurtă; calitatea redării rămâne cea din mpv.conf
            mpv += ["--ytdl=no", "--demuxer=lavf", "--demuxer-lavf-format=mpegts",
                    "--demuxer-lavf-probesize=1500000", "--demuxer-lavf-analyzeduration=1"]
        if self.timeshift:      # pauză / derulare la TV live: buffer mpv (RAM sau disc), atât înainte, cât și în urma redării
            opts = mpv_options(mpv_cmd) if ts_disk else None          # None = nu știm: presupunem un mpv recent
            if ts_disk and opts is not None and "cache-on-disk" not in opts:
                ts_disk, self.ts_nodisk = False, True                 # mpv vechi, fără cache pe disc: RAM, cu limita RAM
            if not ts_disk:
                self.timeshift = min(self.timeshift, TIMESHIFT_RAM_MAX)
            size = f"{self.timeshift}MiB"
            mpv += ["--cache=yes", f"--demuxer-max-bytes={size}", f"--demuxer-max-back-bytes={size}",
                    "--script-opts-append=teleops-ts=1"]         # spune scriptului Lua să afișeze bara Timeshift
            if ts_disk:
                ts_path, self.ts_fallback = pick_timeshift_dir(mpv_cmd, ts_dir)
                old_name = opts is not None and "demuxer-cache-dir" not in opts and "cache-dir" in opts    # mpv < 0.37
                mpv += ["--cache-on-disk=yes", f"--{'cache-dir' if old_name else 'demuxer-cache-dir'}={ts_path}"]
            else:
                mpv.append("--cache-on-disk=no")
        env = get_clean_env()
        if wid:   # încorporat în fereastra Tk: --wid există doar pe X11 (XWayland), deci interzicem backend-ul Wayland
            mpv += [f"--wid={wid}", f"--gpu-context={GPU_CONTEXT}", "--window-dragging=no", "--osc=no", "--osd-bar=no", f"--script={OSC_PATH}"]
            env.pop("WAYLAND_DISPLAY", None)
        self.mpv = subprocess.Popen(mpv + ["-"], stdin=subprocess.PIPE, env=env)
        targets = [lambda: self._boot(zap_cmd), self.ipc]
        if self._feed is not None:
            targets.append(self._feed_mpv)
        for target in targets:
            threading.Thread(target=target, daemon=True).start()

    def _boot(self, zap_cmd):
        """Verifică pornirea tunerului (cel mult 2 reîncercări, ca înainte), apoi trece fluxul către mpv."""
        try:
            for attempt in range(3):
                deadline = time.time() + 0.3
                while time.time() < deadline and self.zap.poll() is None and not self._stopped:
                    time.sleep(0.02)
                if self._stopped or self.zap.poll() is None or attempt == 2:
                    break
                try:
                    self.zap.terminate()
                except OSError:
                    pass
                time.sleep(0.5)
                with self._life:
                    if self._stopped:
                        return
                    self.zap = subprocess.Popen(zap_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=get_clean_env())
        finally:
            self._booting = False
        if not self._stopped:
            self.pump()

    def alive(self):
        if self._booting:           # cât se verifică tunerul, un eșec scurt nu înseamnă oprire (reîncercarea e în curs)
            return self.mpv.poll() is None
        return self.zap.poll() is None and self.mpv.poll() is None

    def pump(self):
        src = self.zap.stdout.fileno()
        try:
            while data := os.read(src, 1 << 16):
                self.got_data = True
                if self.ts: data = self.ts.feed(data)
                if data and self._feed is None:
                    self.mpv.stdin.write(data)
                    self.mpv.stdin.flush()
                    with self.lock:
                        if self.rec: self.rec.write(data)
                elif data:      # Timeshift: înregistrarea nu așteaptă niciodată după mpv (în pauză lungă mpv nu mai citește din pipe)
                    with self.lock:
                        if self.rec: self.rec.write(data)
                    try:
                        self._feed.put_nowait(data)
                    except queue.Full:
                        pass
        except (OSError, ValueError):
            pass

    def _feed_mpv(self):
        """Timeshift: scrie în mpv ce a pus `pump` în coadă. Dacă mpv nu mai citește (pauză peste buffer), doar acest fir așteaptă."""
        try:
            while not self._stopped:
                try:
                    data = self._feed.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.mpv.stdin.write(data)
                self.mpv.stdin.flush()
        except (OSError, ValueError):
            pass

    def t(self, key):
        return tr(self.get_lang(), key)

    def ipc(self):
        for _ in range(500):
            if not self.alive(): return
            c = socket.socket(socket.AF_UNIX)
            try:
                c.connect(str(self.sock))
                break
            except OSError:
                c.close()
                time.sleep(0.03)
        else:
            return
        self.conn = c
        for k, v in self.props.items():
            self.cmd("set_property", k, v)
        if any(self.tone):
            self.set_tone(*self.tone)
        for i, k in enumerate(self.OBSERVED, 1):
            self.cmd("observe_property", i, k)
        
        self.send_labels()
        for msg, keys in self.KEYS.items():
            for key in keys:
                self.cmd("keybind", key, f"script-message {msg}")

        def delayed_osd():
            # Așteaptă încărcarea EPG (EIT) înainte de afișare: minim 3 s, apoi verifică la 0,5 s
            # până când emisiunea curentă ȘI cea următoare sunt cunoscute. Dacă nu apar în 12 s,
            # afișează ce există și reîmprospătează OSD-ul când datele ajung (maxim 60 s).
            t0 = time.time()
            time.sleep(3.0 if self.ts else 0.5)
            self.send_labels()      # scriptul Lua poate fi încărcat după conectarea IPC
            shown = False
            while self.alive() and time.time() - t0 < 60:
                ok = self.epg_complete()
                if ok or (not shown and time.time() - t0 >= 12):
                    self.show_tv_osd()
                    shown = True
                    if ok:
                        break
                time.sleep(0.5)
        threading.Thread(target=delayed_osd, daemon=True).start()

        try:
            with c:
                for line in c.makefile(encoding="utf-8", errors="replace"):
                    try: e = json.loads(line)
                    except ValueError: continue
                    
                    ev, args = e.get("event"), e.get("args") or []
                    if ev == "client-message" and args:
                        if args[0] == "show-info-osd":
                            self.show_channel_info()
                        elif args[0] == "teleops-osc-hot": self.osc_hot = args[1:2] == ["1"]
                        elif args[0] == "teleops-key" and len(args) > 1: self.on_msg("key:" + str(args[1]))
                        elif args[0] in self.KEYS: self.on_msg(args[0])
                    elif ev == "property-change" and e.get("data") is not None:
                        self.on_prop(e["name"], e["data"])
        except OSError:
            pass

    def _now_next(self, now):
        """(emisiune curentă, următoarea) din EPG; None dacă încă nu sunt cunoscute."""
        if not self.ts:
            return None, None
        events = self.ts.events()
        cur = max((e for e in events if e[0] <= now < e[1]), key=lambda e: e[0], default=None)
        after = cur[1] if cur else now
        nxt = min((e for e in events if e[0] >= after - 60 and e is not cur), key=lambda e: e[0], default=None)
        return cur, nxt

    def epg_complete(self):
        """True când nu e nimic de așteptat (fără EPG) sau când emisiunea curentă și cea
        următoare (consecutivă, cu max 2 min diferență) sunt deja încărcate."""
        if not self.ts:
            return True
        cur, nxt = self._now_next(time.time())
        return bool(cur and nxt and nxt[0] - cur[1] <= 120)

    def show_tv_osd(self):
        """Trimite datele EPG către scriptul Lua, care desenează panoul (15 s, cu bară de progres)."""
        cur, nxt = self._now_next(time.time())
        self.cmd("script-message", "teleops-epg", self.channel_name.strip(), "1" if self.ts else "0",
                 cur[2] if cur else "", str(int(cur[0])) if cur else "0", str(int(cur[1])) if cur else "0",
                 nxt[2] if nxt else "")
        self.cmd("script-message", "teleops-epg-show")

    def show_channel_info(self):
        """„Informații canal”: panoul EPG și panoul cu semnalul video/audio, câte 15 s."""
        self.show_tv_osd()
        self.cmd("script-message", "teleops-info-show")

    def show_banner(self, text, ms=3000, wait=True):
        """Banner mic cu numele canalului (↑/↓ pe video). `wait`: bară care se golește până la comutarea automată."""
        self.cmd("script-message", "teleops-epg-hide")
        self.cmd("script-message", "teleops-banner", text, str(ms), "1" if wait else "0")

    def hide_banner(self):
        self.cmd("script-message", "teleops-banner", "", "0", "0")

    def toast(self, text, ms):
        """Mesaj scurt de text (volum, mute, notificări). Ascunde panoul EPG, ca să nu se suprapună."""
        self.cmd("script-message", "teleops-epg-hide")
        self.cmd("show-text", text, ms)

    def cmd(self, *args):
        if self.conn:
            try: self.conn.sendall((json.dumps({"command": args}) + "\n").encode())
            except OSError: pass

    def set_prop(self, name, value):
        self.props[name] = value
        self.cmd("set_property", name, value)

    def capture_keys(self, on):
        """Cât timp e deschisă căutarea J: tastele care ajung la mpv sunt trimise programului (vezi „teleops-capture”)."""
        self.cmd("script-message", "teleops-capture", "1" if on else "0")

    def set_tone(self, bass, treble):
        """Joase / înalte (dB) printr-un filtru audio cu etichetă; la 0/0 filtrul se scoate (fără procesare)."""
        self.tone = (bass, treble)
        self.cmd("af", "remove", "@tone")
        if bass or treble:
            self.cmd("af", "add", f"@tone:lavfi=[bass=g={bass}:f=110,treble=g={treble}:f=3300]")

    def send_labels(self):
        self.cmd("script-message", "teleops-labels", self.t("osc_sub"), self.t("osc_audio"), self.t("osc_off"))
        self.cmd("script-message", "teleops-info-labels", self.t("info_video"), self.t("info_audio"),
                 self.t("info_wait"), self.t("info_noaud"))
        self.cmd("script-message", "teleops-epg-labels", self.t("now").upper(), self.t("next").upper(),
                 self.t("osd_rem"), self.t("osd_loading"), self.t("osd_na"))

    def set_rec_osd(self, text):
        """Indicator discret și permanent de înregistrare, ca osd-overlay separat (nu se suprapune cu EPG/show-text)."""
        if text is None:
            self.cmd("osd-overlay", 4242, "none", "")
        else:
            ass = "{\\an9\\pos(1262,14)\\fs20\\bord1.5\\shad0\\1c&H2626DC&\\3c&H000000&\\alpha&H30&}" + text
            self.cmd("osd-overlay", 4242, "ass-events", ass, 1280, 720)

    def start_rec(self, path):
        with self.lock: self.rec = open(path, "wb")

    def stop_rec(self):
        with self.lock:
            if self.rec: self.rec.close(); self.rec = None

    @staticmethod
    def _reap(p):
        try:
            p.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def stop(self, background=False):
        """Oprește fluxul. Ambele procese primesc semnalul odată; se așteaptă doar tunerul (trebuie eliberat pentru
        canalul următor). Cu `background=True` mpv se curăță în fundal, ca schimbarea canalului să nu aștepte."""
        with self._life:
            self._stopped = True
        self.on_prop = self.on_msg = lambda *_: None
        self.stop_rec()
        for p in (self.zap, self.mpv):
            try:
                p.terminate()
            except OSError:
                pass
        self._reap(self.zap)

        def rest():
            self._reap(self.mpv)
            subprocess.run(["pkill", "-f", self.sock_name], stderr=subprocess.DEVNULL, env=get_clean_env())
            Path(self.sock).unlink(missing_ok=True)
        if background:
            threading.Thread(target=rest, daemon=True).start()
        else:
            rest()


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: ui  ·  Interfața Tkinter (singurul strat care folosește tkinter)
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/constants
#   Constante ale interfeței.
# ──────────────────────────────────────────────────────────────────────────────

VOL_MAX = 130           # volume-max implicit în mpv
VOL_WHEEL_STEP = 5      # procente de volum la fiecare „clic” al rotiței de mouse de pe video
# Paletă Dark / Slate Hi-Fi (din darkmode.py), asortată cu rotițele retro, grila de difuzor și LED-urile portocalii.
# Tema luminoasă este aspectul original: nu are culori proprii aici, folosește implicitele Tk/ttk.
BG_SLATE = "#2b2d30"       # fundal principal (panou, listă, câmpuri)
BG_PANEL = "#33363a"       # suprafețe secundare (butoane, câmpuri de introducere, tab-uri)
BG_DARK = "#202225"        # fundal închis (chenare, zonă video, antete)
BORDER_SLATE = "#46494e"   # contururi discrete și separatoare
TXT_LIGHT = "#e6e6e6"      # text principal
TXT_MUTED = "#9ea3ab"      # text secundar / subtitluri
ACCENT_LED = "#e8902c"     # portocaliu LED retro (selecție, accente, progres)
ACCENT_HOVER = "#42464c"   # hover pe controale
ON_ACCENT = "#18191b"      # text pe fundal portocaliu
THEME_MODES = ("light", "dark", "auto")
DARK = False               # tema activă (o schimbă `set_dark`)
TXT_DARK = "#000000"       # culoare text implicită (în tema întunecată devine TXT_LIGHT)


def set_dark(flag):
    """Comută paleta: restul codului citește `DARK` / `TXT_DARK` în momentul în care desenează."""
    global DARK, TXT_DARK
    DARK = bool(flag)
    TXT_DARK = TXT_LIGHT if DARK else "#000000"


def themed(light, dark):
    """Valoarea pentru tema activă."""
    return dark if DARK else light


TONE_MAX = 10           # joase / înalte: ±10 dB
LIST_MIN_H = 150        # înălțimea minimă (px) a listei de canale la strângerea ferestrei
CFG_W, CFG_GAP = 36, 5     # lățimea butonului ⚙ și spațiul dintre el și butonul EPG
PANEL_W = 320           # lățimea fixă a panoului cu comenzi
TUNER_W = PANEL_W       # lățimea fixă a ferestrei „Tuner TV” (aceeași cu a panoului: butoane de aceeași mărime)
CH_PICK_MS = 3000       # ↑/↓ pe video: după câte ms fără altă tastă pornește canalul ales (Enter îl pornește imediat)
INFO_W = PANEL_W - 28   # lățimea utilă în vederea „informații” (panoul are padding 14 pe fiecare parte)
POSTER_H = 420          # înălțimea MAXIMĂ a zonei de poster; un poster mai scurt ocupă doar cât are el (zona se strânge după el).
                        # Nu depinde de mărimea ferestrei: posterul nu se scalează la redimensionare.
POSTER_PAD = 10         # distanța posterului față de marginea de sus a zonei
LOGO_H = 96             # înălțimea FIXĂ a zonei de logo (lipit jos, deasupra barei de separare)
VIDEO_MIN_W = 480       # lățimea minimă a zonei video

HOTKEYS = (("hk_play", "hk_play_k"), ("hk_fav", "hk_fav_k"), ("hk_search", "hk_search_k"),      # lista de canale
           ("hk_jump", "hk_jump_k"), ("hk_prev", "hk_prev_k"), ("hk_info", "hk_info_k"),
           ("hk_epg", "hk_epg_k"), ("hk_epgwin", "hk_epgwin_k"), ("hk_rec", "hk_rec_k"),                                      # canalul curent
           ("hk_osc", "hk_osc_k"), ("hk_vol", "hk_vol_k"), ("hk_knob", "hk_knob_k"), ("hk_mute", "hk_mute_k"), ("hk_fs", "hk_fs_k"), ("hk_ui", "hk_ui_k"),   # video
           ("hk_chan", "hk_chan_k"), ("hk_volkeys", "hk_volkeys_k"),                                                   # video: canal / volum cu tastele
           ("hk_ts_pause", "hk_ts_pause_k"), ("hk_ts_seek", "hk_ts_seek_k"), ("hk_ts_live", "hk_ts_live_k"),
           ("hk_ts_bar", "hk_ts_bar_k"), ("hk_stats", "hk_stats_k"),                                                                               # video: Timeshift
           ("hk_quit", "hk_quit_k"))                                                            # program


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/geometry
#   Geometria redimensionării unei ferestre fără bordură (funcții pure, fără Tk, ușor de testat).
# ──────────────────────────────────────────────────────────────────────────────

EDGE = 6            # grosimea (px) a zonei invizibile de apucare de pe laturi
EDGE_CORNER = 14    # lungimea (px) a zonelor din colțuri

CURSORS = {"n": "sb_v_double_arrow", "s": "sb_v_double_arrow", "w": "sb_h_double_arrow", "e": "sb_h_double_arrow",
           "nw": "top_left_corner", "ne": "top_right_corner", "sw": "bottom_left_corner", "se": "bottom_right_corner"}


def edge_at(x, y, rect, edge=EDGE, corner=EDGE_CORNER):
    """Marginea ("n", "se", ...) la care se află punctul (x, y), sau None. rect = (x, y, lățime, înălțime) pe ecran."""
    rx, ry, w, h = rect
    if not (rx <= x < rx + w and ry <= y < ry + h):
        return None
    dl, dr, dt, db = x - rx, rx + w - 1 - x, y - ry, ry + h - 1 - y
    on_h_side, on_v_side = min(dt, db) < edge, min(dl, dr) < edge      # în banda de sus/jos, respectiv stânga/dreapta
    reach_x = corner if on_h_side else edge      # lângă o latură orizontală, zona de colț se întinde pe lățime
    reach_y = corner if on_v_side else edge
    horiz = "w" if dl < reach_x else "e" if dr < reach_x else ""
    vert = "n" if dt < reach_y else "s" if db < reach_y else ""
    return (vert + horiz) or None


def resize_geometry(edge, start, dx, dy, min_size):
    """Geometria nouă (x, y, w, h) după tragerea marginii `edge` cu (dx, dy). start = (x, y, w, h).
    Marginea opusă rămâne pe loc; fereastra nu scade sub min_size."""
    x, y, w, h = start
    min_w, min_h = min_size
    nw, nh, nx, ny = w, h, x, y
    if "e" in edge:
        nw = max(min_w, w + dx)
    if "s" in edge:
        nh = max(min_h, h + dy)
    if "w" in edge:
        nw = max(min_w, w - dx)
        nx = x + w - nw
    if "n" in edge:
        nh = max(min_h, h - dy)
        ny = y + h - nh
    return nx, ny, nw, nh


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/widgets
#   Widgeturi Tk reutilizabile: lista de canale și tooltip.
# ──────────────────────────────────────────────────────────────────────────────

class ChannelList(tk.Text):
    """Listă de canale (API asemănător cu Listbox). Folosește Text ca titlurile să poată fi
    centrate pe lățimea ferestrei și subliniate exact cât textul."""

    def __init__(self, master, **kw):
        probe = tk.Listbox(master)
        self._light_sel = (probe.cget("selectbackground"), probe.cget("selectforeground"))
        probe.destroy()
        kw.setdefault("width", 1)
        kw.setdefault("height", 1)
        super().__init__(master, wrap="none", cursor="arrow", insertwidth=0, padx=2, pady=0,
                         borderwidth=0, takefocus=True, **kw)
        self.selectable = []
        self.tag_configure("title", justify="center", underline=True)
        self._paint_tags()
        self.tag_raise("cur")
        # fără bindingurile implicite ale lui Text (editare, selecție cu mouse-ul)
        self.bindtags((str(self), str(self.winfo_toplevel()), "all"))
        self.bind("<Button-1>", self._click)
        self.bind("<Up>", lambda e: self._step(-1))
        self.bind("<Down>", lambda e: self._step(1))
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", self._wheel)
        self.bind("<Button-5>", self._wheel)

    def _paint_tags(self):
        sel_bg, sel_fg = themed(self._light_sel, (ACCENT_LED, ON_ACCENT))
        self.tag_configure("title", foreground=ACCENT_LED if DARK else "")
        self.tag_configure("locked", foreground=themed("#dc2626", "#f87171"))     # canale codate: roșu
        self.tag_configure("cur", background=sel_bg, foreground=sel_fg)

    def retheme(self, bg):
        """Schimbarea temei: fundalul listei (cel al panoului), culoarea textului și etichetele."""
        self.configure(bg=bg, fg=TXT_DARK)
        self._paint_tags()

    def clear(self):
        self.delete("1.0", "end")
        self.selectable = []

    def add(self, text, title=False, selectable=False, locked=False):
        self.insert("end", text, "title" if title else ("locked" if locked else ()))
        self.insert("end", "\n")
        self.selectable.append(selectable)

    def selection_clear(self, *_):
        self.tag_remove("cur", "1.0", "end")

    def selection_set(self, i):
        self.tag_add("cur", f"{i + 1}.0", f"{i + 2}.0")

    def curselection(self):
        r = self.tag_ranges("cur")
        return (int(str(r[0]).split(".")[0]) - 1,) if r else ()

    def nearest(self, y):
        i = int(self.index(f"@0,{y}").split(".")[0]) - 1
        return max(-1, min(i, len(self.selectable) - 1))

    def _click(self, e):
        self.focus_set()
        i = self.nearest(e.y)
        if 0 <= i < len(self.selectable) and self.selectable[i]:
            self.selection_clear()
            self.selection_set(i)

    def _step(self, d):
        cur = self.curselection()
        i = (cur[0] if cur else -1) + d
        while 0 <= i < len(self.selectable) and not self.selectable[i]:
            i += d
        if 0 <= i < len(self.selectable):
            self.selection_clear()
            self.selection_set(i)
            self.see(f"{i + 1}.0")
        return "break"

    def _wheel(self, e):
        if e.num == 4:
            self.yview_scroll(-3, "units")
        elif e.num == 5:
            self.yview_scroll(3, "units")
        else:
            self.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"


class Tip:
    def __init__(self, w, text, wrap=0):
        self.w, self.text, self.wrap, self.tw = w, text, wrap, None
        w.bind("<Enter>", self.show)
        w.bind("<Leave>", self.hide)

    def show(self, _=None):
        if self.tw: return
        self.tw = tk.Toplevel(self.w)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{self.w.winfo_rootx()}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        tk.Label(self.tw, text=self.text, background=themed("#ffffe0", BG_DARK), foreground=themed("#000000", TXT_LIGHT),
                 relief="solid", borderwidth=1, padx=themed(1, 6), pady=themed(1, 4),
                 wraplength=self.wrap, justify="left").pack()

    def hide(self, _=None):
        if self.tw: self.tw.destroy(); self.tw = None


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/window_chrome
#   Comportamentul ferestrei: mutare prin tragere, fără bordură/titlebar și redimensionare fără margini.
#
#   Mutat din fereastra principală ca s-o păstreze mică. Nu știe nimic despre canale sau redare: primește
#   prin callback-uri doar ce îi trebuie (streamul curent, starea de ecran complet).
# ──────────────────────────────────────────────────────────────────────────────

class WindowChrome:
    def __init__(self, root, video, x11, *, get_stream, is_fullscreen):
        self.root, self.video, self.x11 = root, video, x11
        self.get_stream, self.is_fullscreen = get_stream, is_fullscreen
        self.borderless = False
        self._mdrag, self._btn_prev = None, False
        self._resize, self._cursor = None, ""
        root.bind("<ButtonPress-1>", self._on_press, add="+")     # zonele Tk: prindem marginea înaintea mutării

    # ---- poziția și mutarea ferestrei
    def win_pos(self):
        m = re.match(r"\d+x\d+([+-]+\d+)([+-]+\d+)", self.root.geometry())
        if not m:
            return self.root.winfo_x(), self.root.winfo_y()
        return int(m.group(1).replace("+-", "-")), int(m.group(2).replace("+-", "-"))

    def _drag_to(self, p, x, y):
        """p = (x0, y0, win_x, win_y, mutat): mută fereastra după cursor după pragul de 4 px; întoarce p actualizat."""
        x0, y0, wx, wy, moved = p
        dx, dy = x - x0, y - y0
        if moved or abs(dx) + abs(dy) >= 4:
            moved = True
            self.root.geometry(f"+{wx + dx}+{wy + dy}")
        return x0, y0, wx, wy, moved

    def bind_drag(self, w, click=None):
        """Tragerea cu butonul stâng pe widget mută fereastra; un click fără mișcare cheamă `click`."""
        st = {}

        def motion(e):
            if st.get("p") and not self.is_fullscreen() and not self._resize:
                st["p"] = self._drag_to(st["p"], e.x_root, e.y_root)

        def release(e):
            p = st.pop("p", None)
            if p and not p[4] and click:
                click()
        w.bind("<ButtonPress-1>", lambda e: st.update(p=(e.x_root, e.y_root, *self.win_pos(), False)), add="+")
        w.bind("<B1-Motion>", motion, add="+")
        w.bind("<ButtonRelease-1>", release, add="+")

    def bind_dead_zones(self, w, exclude=()):
        """Face trasabile toate zonele „moarte” (cadre, etichete); controalele și `exclude` rămân neatinse."""
        if type(w) in (tk.Frame, ttk.Frame, ttk.Label) and w not in exclude:
            self.bind_drag(w)
        for c in w.winfo_children():
            self.bind_dead_zones(c, exclude)

    def start_mpv_poll(self):
        """Urmărim cursorul cu XQueryPointer (mpv e fereastră X11 copil și își ține evenimentele mouse-ului):
        mutăm fereastra când se trage în zona video și redimensionăm când se trage de o margine invizibilă."""
        self._mpv_drag_poll()

    def _rect(self):
        return self.root.winfo_rootx(), self.root.winfo_rooty(), self.root.winfo_width(), self.root.winfo_height()

    def _begin_resize(self, edge, x, y):
        wx, wy = self.win_pos()
        self._resize = (edge, x, y, wx, wy, self.root.winfo_width(), self.root.winfo_height())

    def _on_press(self, e):
        if self.borderless and not self.is_fullscreen() and not self._resize:
            edge = edge_at(e.x_root, e.y_root, self._rect())
            if edge:
                self._begin_resize(edge, e.x_root, e.y_root)

    def _set_cursor(self, edge):
        cur = CURSORS.get(edge or "", "")
        if cur != self._cursor:
            self._cursor = cur
            try: self.root.configure(cursor=cur)
            except tk.TclError: pass

    def _resize_to(self, x, y):
        edge, x0, y0, wx, wy, w, h = self._resize
        try: min_size = self.root.minsize() or (1, 1)
        except (tk.TclError, ValueError): min_size = (1, 1)
        nx, ny, nw, nh = resize_geometry(edge, (wx, wy, w, h), x - x0, y - y0, min_size)
        self.root.geometry(f"{nw}x{nh}+{nx}+{ny}")

    def _mpv_drag_poll(self):
        self.root.after(12 if (self._mdrag or self._resize) else 40, self._mpv_drag_poll)
        stream = self.get_stream()
        if not self.x11 or self.is_fullscreen():
            self._mdrag = self._resize = self._btn_prev = None
            self._set_cursor(None)
            return
        try:
            x, y, mask = self.x11.pointer()
        except Exception:
            return
        down = bool(mask & X11.BUTTON1)
        if self.borderless:                  # redimensionare: margini invizibile, fără widgeturi desenate
            if self._resize:
                if down:
                    self._resize_to(x, y)
                else:
                    self._resize = None
                self._btn_prev = down
                return
            edge = edge_at(x, y, self._rect())
            if not down:
                self._set_cursor(edge)       # forma cursorului se schimbă doar peste zonele Tk (nu peste imaginea mpv)
            elif not self._btn_prev and edge:
                self._begin_resize(edge, x, y)
                self._btn_prev = down
                return
        if not stream:
            self._mdrag, self._btn_prev = None, down
            return
        v = self.video
        if down and not self._btn_prev:      # apăsare nouă (nu un drag început în altă parte)
            if (v.winfo_rootx() <= x < v.winfo_rootx() + v.winfo_width() and v.winfo_rooty() <= y < v.winfo_rooty() + v.winfo_height()
                    and not stream.osc_hot):   # nu trage de butoanele mpv
                self._mdrag = (x, y, *self.win_pos(), False)
        elif down and self._mdrag:
            self._mdrag = self._drag_to(self._mdrag, x, y)
        elif not down:
            self._mdrag = None
        self._btn_prev = down

    # ---- fără bordură + redimensionare
    def set_borderless(self, on):
        """Scoate/pune bordura ferestrei. False dacă nu se poate (fără X11)."""
        if not self.x11:
            return False
        self.root.update_idletasks()
        self.x11.set_borderless(self.root.winfo_id(), on)
        self.borderless = bool(on)
        if not on:
            self._resize = None
            self._set_cursor(None)
        return True


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/epg_window
#   Fereastra cu programul TV (EPG) al canalului curent.
# ──────────────────────────────────────────────────────────────────────────────

def hm(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M")


class EpgWindow(tk.Toplevel):
    """`host` = fereastra principală; folosim doar: root, t(), lang, cur, stream, bg_grey, f_norm, f_bold, epg_events(),
    is_scheduled(start, end), schedule_toggle(start, end, titlu) (+ last_dropped la „added_over”),
    is_watch(start, end), watch_toggle(start, end, titlu) (+ last_conflict la „conflict”),
    my_schedules(), cancel_schedule(kind, job), clear_schedules() (fila „Programările mele”)."""

    def __init__(self, host):
        super().__init__(host.root)
        self.title(host.t("epg_btn"))
        self.transient(host.root)               # ca „Despre” și „Tuner TV”: centrată pe fereastra programului, deasupra ei
        self.geometry("640x630")
        self.minsize(600, 590)

        st = ttk.Style()
        st.configure("Epg.Treeview", background=host.bg_grey, fieldbackground=host.bg_grey,
                     foreground=TXT_DARK, font=host.f_norm)
        if DARK:
            st.configure("Epg.Treeview.Heading", background=BG_PANEL, foreground=ACCENT_LED, font=host.f_bold)
            st.map("Epg.Treeview", background=[("selected", ACCENT_LED)], foreground=[("selected", ON_ACCENT)])
        else:
            st.configure("Epg.Treeview.Heading", font=host.f_bold)
            st.map("Epg.Treeview", background=[("selected", "#4a6984")], foreground=[("selected", "#ffffff")])
        self.configure(bg=host.bg_grey)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        mf = ttk.Frame(nb, padding=10)          # fila 1: programul canalului curent
        my = ttk.Frame(nb, padding=10)          # fila 2: toate programările mele
        nb.add(mf, text=host.t("epg_tab_prog"))
        nb.add(my, text=host.t("epg_tab_my"))

        t_frame = ttk.Frame(mf)
        t_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("date", "time", "title")
        tree = ttk.Treeview(t_frame, columns=columns, show="headings", selectmode="browse", style="Epg.Treeview")
        
        
        tree.heading("date", text=host.t("epg_date"))
        tree.heading("time", text=host.t("epg_time"))
        tree.heading("title", text=host.t("epg_title"))

        tree.column("date", width=100, minwidth=80, anchor="w")
        tree.column("time", width=110, minwidth=90, anchor="w")
        tree.column("title", width=380, minwidth=200, anchor="w")

        sb = ttk.Scrollbar(t_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)

        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = ttk.Frame(mf)
        btn_row.pack(fill="x", pady=(0, 4))
        rec_btn = ttk.Button(btn_row, text=host.t("epg_rec_btn"))
        rec_btn.pack(side="left")
        Tip(rec_btn, host.t("epg_rec_tip"), wrap=320)
        watch_btn = ttk.Button(btn_row, text=host.t("epg_watch_btn"))
        watch_btn.pack(side="left", padx=(8, 0))
        Tip(watch_btn, host.t("epg_watch_tip").format(lead=WATCH_LEAD // 60), wrap=320)
        status = ttk.Label(mf, text="", wraplength=600, justify="left")      # mesajele, pe rând separat: nu se înghesuie lângă butoane
        status.pack(fill="x", pady=(0, 8))

        d_frame = ttk.LabelFrame(mf, text=host.t("epg_desc"), padding=8)
        d_frame.pack(fill="both", expand=False)

        desc_txt = tk.Text(d_frame, wrap="word", font=host.f_norm, height=6,
                           bg=host.bg_grey, fg=TXT_DARK, relief="flat", highlightthickness=0, state="disabled")
        d_sb = ttk.Scrollbar(d_frame, orient="vertical", command=desc_txt.yview)
        desc_txt.configure(yscrollcommand=d_sb.set)

        desc_txt.pack(side="left", fill="both", expand=True)
        d_sb.pack(side="right", fill="y")

        ev_map = {}         # id rând -> (început, sfârșit, titlu, descriere)

        def on_select(event):
            selected = tree.selection()
            if selected:
                item_id = selected[0]
                desc = ev_map[item_id][3] if item_id in ev_map else ""
                desc_txt.configure(state="normal")
                desc_txt.delete("1.0", "end")
                desc_txt.insert("end", desc if desc else host.t("epg_nodesc"))
                desc_txt.configure(state="disabled")
            update_btn()

        def update_btn():
            """Butoanele programează sau anulează, după emisiunea selectată."""
            sel = tree.selection()
            if not sel or sel[0] not in ev_map:
                rec_btn.configure(text=host.t("epg_rec_btn"))
                watch_btn.configure(text=host.t("epg_watch_btn"))
                rec_btn.state(["disabled"])
                watch_btn.state(["disabled"])
                return
            s, e = ev_map[sel[0]][:2]
            rec_btn.configure(text=host.t("epg_rec_cancel" if host.is_scheduled(s, e) else "epg_rec_btn"))
            watch_btn.configure(text=host.t("epg_watch_cancel" if host.is_watch(s, e) else "epg_watch_btn"))
            rec_btn.state(["!disabled"])
            watch_btn.state(["!disabled"])

        def toggle_rec():
            sel = tree.selection()
            if not sel or sel[0] not in ev_map:
                return
            s, e, name, _ = ev_map[sel[0]]
            result = host.schedule_toggle(s, e, name)
            added = host.t("epg_rec_added").format(start=hm(s), end=hm(e), margin=PRE // 60)
            dropped = ", ".join(f"„{w.title}” ({w.channel.strip()})" for w in host.last_dropped)
            status.configure(text={
                "added": added,
                "added_over": added + " " + host.t("rec_watch_dropped").format(items=dropped),
                "removed": host.t("epg_rec_removed"),
                "past": host.t("epg_rec_past")}[result])
            render()

        def toggle_watch():
            sel = tree.selection()
            if not sel or sel[0] not in ev_map:
                return
            s, e, name, _ = ev_map[sel[0]]
            result = host.watch_toggle(s, e, name)
            other = host.last_conflict
            status.configure(text={
                "added": lambda: host.t("epg_watch_added").format(start=hm(s), lead=WATCH_LEAD // 60),
                "removed": lambda: host.t("epg_watch_removed"),
                "past": lambda: host.t("epg_rec_past"),
                "running": lambda: host.t("epg_watch_running"),
                "conflict": lambda: host.t("epg_watch_clash").format(title=other.title, channel=other.channel.strip())}[result]())
            render()

        rec_btn.configure(command=toggle_rec)
        watch_btn.configure(command=toggle_watch)
        tree.bind("<<TreeviewSelect>>", on_select)

        days_dict = {
            "Română": ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"],
            "English": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "Italiano": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        }

        # ── fila „Programările mele”: toate înregistrările și vizionările programate (care n-au pornit încă), la un loc
        my_frame = ttk.Frame(my)
        my_frame.pack(fill="both", expand=True, pady=(0, 10))
        my_tree = ttk.Treeview(my_frame, columns=("type", "channel", "date", "time", "title"), show="headings",
                               selectmode="browse", style="Epg.Treeview")
        for col, key, width in (("type", "my_col_type", 105), ("channel", "my_col_channel", 105), ("date", "epg_date", 75),
                                ("time", "epg_time", 95), ("title", "epg_title", 190)):
            my_tree.heading(col, text=host.t(key))
            my_tree.column(col, width=width, minwidth=60, anchor="w")
        my_sb = ttk.Scrollbar(my_frame, orient="vertical", command=my_tree.yview)
        my_tree.configure(yscrollcommand=my_sb.set)
        my_tree.pack(side="left", fill="both", expand=True)
        my_sb.pack(side="right", fill="y")
        my_row = ttk.Frame(my)
        my_row.pack(fill="x", pady=(0, 4))
        del_btn = ttk.Button(my_row, text=host.t("my_delete"))
        del_btn.pack(side="left")
        clear_btn = ttk.Button(my_row, text=host.t("my_clear"))
        clear_btn.pack(side="left", padx=(8, 0))
        my_hint = ttk.Label(my, text="", wraplength=600, justify="left")        # „nicio programare”
        my_hint.pack(fill="x", pady=(0, 4))
        my_status = ttk.Label(my, text="", wraplength=600, justify="left")      # rezultatul ultimei ștergeri
        my_status.pack(fill="x")
        my_map = {}                 # id rând -> (tip, job)

        def my_buttons():
            sel = my_tree.selection()
            del_btn.state(["!disabled"] if sel and sel[0] in my_map else ["disabled"])
            clear_btn.state(["!disabled"] if my_map else ["disabled"])

        def delete_one():
            sel = my_tree.selection()
            if not sel or sel[0] not in my_map:
                return
            kind, job = my_map[sel[0]]
            host.cancel_schedule(kind, job)
            my_status.configure(text=host.t("my_deleted"))
            render()

        def clear_all():
            if not my_map:
                return
            if not messagebox.askyesno(host.t("epg_tab_my"), host.t("my_clear_confirm"), icon="warning", default="no", parent=self):
                return
            host.clear_schedules()
            my_status.configure(text=host.t("my_cleared"))
            render()

        del_btn.configure(command=delete_one)
        clear_btn.configure(command=clear_all)
        my_tree.bind("<<TreeviewSelect>>", lambda e: my_buttons())
        my_tree.bind("<Delete>", lambda e: delete_one())

        def render_my():
            sel = my_tree.selection()
            sel_key = (my_map[sel[0]][0], my_map[sel[0]][1].key) if sel and sel[0] in my_map else None
            for item in my_tree.get_children():
                my_tree.delete(item)
            my_map.clear()
            for kind, job in host.my_schedules():
                dt = datetime.fromtimestamp(job.start)
                day_name = days_dict.get(host.lang, days_dict["Română"])[dt.weekday()]
                iid = my_tree.insert("", "end", values=(host.t("my_rec" if kind == "rec" else "my_watch"), job.channel.strip(),
                                                        f"{day_name} {dt.day:02d}.{dt.month:02d}",
                                                        f"{hm(job.start)}–{hm(job.end)}", job.title))
                my_map[iid] = (kind, job)
            kids = my_tree.get_children()
            if kids:
                keep = next((k for k in kids if sel_key == (my_map[k][0], my_map[k][1].key)), None)
                if keep:
                    my_tree.selection_set(keep)
            my_hint.configure(text="" if kids else host.t("my_empty"))
            my_buttons()

        def render():
            if not self.winfo_exists():
                return
            render_my()
            current_sel = tree.selection()
            sel_key = ev_map[current_sel[0]][:2] if current_sel and current_sel[0] in ev_map else None

            for item in tree.get_children():
                tree.delete(item)
            ev_map.clear()

            self.title(f"{host.t('epg_btn')} - {host.cur or ''}")
            evs = host.epg_events()
            for s, e, name, desc in evs:
                dt = datetime.fromtimestamp(s)
                day_name = days_dict.get(host.lang, days_dict["Română"])[dt.weekday()]
                date_str = f"{day_name} {dt.day:02d}.{dt.month:02d}"
                time_str = f"{hm(s)}–{hm(e)}"
                mark = ("⏺ " if host.is_scheduled(s, e) else "") + ("📺 " if host.is_watch(s, e) else "")
                item_id = tree.insert("", "end", values=(date_str, time_str, mark + name))
                ev_map[item_id] = (s, e, name, desc)

            children = tree.get_children()
            if children:
                if sel_key:
                    match_item = next((child for child in children if ev_map[child][:2] == sel_key), children[0])
                    tree.selection_set(match_item)
                    tree.see(match_item)
                else:
                    tree.selection_set(children[0])
                    tree.see(children[0])
            else:
                desc_txt.configure(state="normal")
                desc_txt.delete("1.0", "end")
                wait_text = host.t("epg_wait" if host.stream else "epg_none")
                desc_txt.insert("end", wait_text)
                desc_txt.configure(state="disabled")

            update_btn()

        def refresh():
            if not self.winfo_exists():
                return
            render()
            self.after(3000, refresh)

        if not host.stream and host.my_schedules():          # fără redare, programul canalului e gol: începem cu programările
            nb.select(my)
        refresh()

        # poziția: la sfârșit, după ce toate widgeturile există, ca la „Despre” (altfel unele manageri de ferestre o ignoră)
        r = host.root
        r.update_idletasks()
        self.update_idletasks()
        x = r.winfo_rootx() + max(0, (r.winfo_width() - 640) // 2)
        y = r.winfo_rooty() + max(0, (r.winfo_height() - 630) // 2)
        y = max(0, min(y, self.winfo_screenheight() - 630 - 40))
        self.geometry(f"640x630+{x}+{y}")


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/mpv_dialog
#   Dialogul „Configurează MPV”: opțiuni alese din liste (potrivite pentru TV), plus acces la mpv.conf.
#
#   Se construiește singur din `player.mpv_options.OPTIONS`. La salvare: generează blocul, verifică
#   configurația cu mpv, o scrie în mpv.conf (blocul gestionat, restul fișierului rămâne neatins) și
#   anunță fereastra principală prin `on_saved(opts)`.
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_OF_CHOICE = {o.key: o.choices[0][0] for o in OPTIONS if o.kind == "choice"}
SLIDER_LEN = 260


class MpvDialog(tk.Toplevel):
    def __init__(self, parent, *, lang, opts, mpv_cmd, on_saved):
        super().__init__(parent)
        self.lang, self.mpv_cmd, self.on_saved = lang, mpv_cmd, on_saved
        self.vars, self.widgets, self._label_to_val, self._val_to_label = {}, {}, {}, {}
        self._busy = False
        self.title(self.t("mo_title"))
        self.transient(parent)
        self.resizable(False, False)

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)
        tabs = {}
        for g in GROUPS:
            tabs[g] = ttk.Frame(nb, padding=12)
            tabs[g].columnconfigure(1, weight=1)
            nb.add(tabs[g], text=self.t(f"mo_tab_{g}"))
        rows = dict.fromkeys(GROUPS, 0)
        for o in OPTIONS:
            self._add_row(tabs[o.group], rows[o.group], o)
            rows[o.group] += 1

        ttk.Label(outer, text=self.t("mo_note"), wraplength=640, justify="left", font="TkSmallCaptionFont",
                  ).pack(fill="x", pady=(10, 6))
        bar = ttk.Frame(outer)
        bar.pack(fill="x")
        for key, cmd in (("mo_open_conf", self._open_conf), ("mo_recommended", self._recommended), ("mo_reset", self._reset)):
            ttk.Button(bar, text=self.t(key), command=cmd).pack(side="left", padx=(0, 6))
        self.save_btn = ttk.Button(bar, text=self.t("mo_save"), command=self._save)
        self.save_btn.pack(side="right")
        ttk.Button(bar, text=self.t("mo_cancel"), command=self.destroy).pack(side="right", padx=6)

        self._load(opts)
        self._sync()
        self.bind("<Escape>", lambda e: self.destroy())
        self._center(parent)
        self.grab_set()
        self.focus_set()

    def t(self, key):
        return tr(self.lang, key)

    def _label(self, text):
        """Etichetă afișată pentru o alegere: „@cheie” = tradusă, altfel textul însuși."""
        return self.t(text[1:]) if text.startswith("@") else text

    # ---- construirea rândurilor
    def _add_row(self, tab, r, o):
        lbl = ttk.Label(tab, text=self.t(f"mo_{o.key}"))
        lbl.grid(row=r, column=0, sticky="nw" if o.kind == "multiline" else "w", pady=4, padx=(0, 12))
        var = self.vars[o.key] = tk.StringVar()
        if o.kind == "choice":
            labels = [self._label(l if l else v) for v, l in o.choices]
            self._label_to_val[o.key] = dict(zip(labels, (v for v, _ in o.choices)))
            self._val_to_label[o.key] = {v: lb for lb, v in self._label_to_val[o.key].items()}
            w = ttk.Combobox(tab, textvariable=var, values=labels, state="readonly", width=44)
            w.bind("<<ComboboxSelected>>", lambda e: self._sync())
        elif o.kind == "slider":
            w = self._make_slider(tab, o, var)
        elif o.kind == "multiline":
            w = tk.Text(tab, width=46, height=6, wrap="none", undo=True)
            if DARK:
                w.configure(bg=BG_DARK, fg=TXT_LIGHT, insertbackground=ACCENT_LED, selectbackground=ACCENT_LED,
                            selectforeground=ON_ACCENT, highlightthickness=1, highlightbackground=BORDER_SLATE, relief="flat")
        else:
            w = ttk.Entry(tab, textvariable=var, width=46)
        w.grid(row=r, column=1, sticky="w", pady=4)
        self.widgets[o.key] = w
        hint = f"mh_{o.key}"
        if hint in T:
            info = ttk.Label(tab, text="ⓘ", cursor="question_arrow")
            info.grid(row=r, column=2, sticky="nw" if o.kind == "multiline" else "w", padx=(8, 0), pady=4)
            tip = self.t(hint)
            for widget in (lbl, info):
                Tip(widget, tip, wrap=380)

    def _make_slider(self, tab, o, var):
        """Slider cu valoarea afișată alături și buton de revenire la valoarea implicită."""
        fr = ttk.Frame(tab)
        scale = ttk.Scale(fr, from_=o.lo, to=o.hi, orient="horizontal", length=SLIDER_LEN,
                          command=lambda v: self._slider_moved(o, var, v))
        scale.pack(side="left")
        value = ttk.Label(fr, width=12, anchor="e")
        value.pack(side="left", padx=(8, 4))
        reset = ttk.Button(fr, text="↺", width=3, command=lambda: var.set(str(o.default)))
        reset.pack(side="left")
        Tip(reset, self.t("mo_reset_one"))

        def sync(*_):
            if self._busy:
                return
            self._busy = True
            try:
                n = self._slider_value(o, var.get())
                value.configure(text=self._fmt(o, n))
                scale.set(n)
            finally:
                self._busy = False
        var.trace_add("write", sync)
        return fr

    @staticmethod
    def _snap(o, v):
        n = max(o.lo, min(round(float(v)), o.hi))
        return o.lo + round((n - o.lo) / o.step) * o.step

    def _slider_value(self, o, raw):
        try: return self._snap(o, raw)
        except (TypeError, ValueError): return o.default

    def _slider_moved(self, o, var, v):
        if self._busy:
            return
        n = self._snap(o, v)
        if var.get() != str(n):
            var.set(str(n))

    def _fmt(self, o, n):
        if o.implicit and n == o.default:
            return self.t("mc_default_short")
        return f"{n} {o.unit}".strip()

    # ---- valori <-> widgeturi
    def _set(self, key, value):
        o = BY_KEY[key]
        if o.kind == "choice":
            self.vars[key].set(self._val_to_label[key].get(value, self._val_to_label[key][DEFAULT_OF_CHOICE[key]]))
        elif o.kind == "multiline":
            w = self.widgets[key]
            w.delete("1.0", "end")
            w.insert("1.0", str(value))
        else:
            self.vars[key].set(str(value))

    def _load(self, opts):
        opts = clean_mpv_opts(opts)
        for o in OPTIONS:
            default = DEFAULT_OF_CHOICE.get(o.key, o.default if o.kind == "slider" else "")
            self._set(o.key, opts.get(o.key, default))

    def _collect(self):
        out = {}
        for o in OPTIONS:
            if o.kind == "choice":
                out[o.key] = self._label_to_val[o.key].get(self.vars[o.key].get(), "")
            elif o.kind == "multiline":
                out[o.key] = self.widgets[o.key].get("1.0", "end")
            else:
                out[o.key] = self.vars[o.key].get()
        return clean_mpv_opts(out)

    def _choice(self, key):
        return self._label_to_val[key].get(self.vars[key].get(), "")

    def _sync(self):
        """Metoda, rata și ordinea câmpurilor au sens doar când deinterlace e pornit (și doar pentru bwdif/yadif)."""
        on = self._choice("deint_mode") in ("interlaced", "all")
        soft = on and self._choice("deint_method") != "mpv"
        self.widgets["deint_method"].configure(state="readonly" if on else "disabled")
        for k in ("deint_rate", "deint_parity"):
            self.widgets[k].configure(state="readonly" if soft else "disabled")

    # ---- butoane
    def _recommended(self):
        for k, v in RECOMMENDED.items():
            self._set(k, v)
        self._sync()

    def _reset(self):
        self._load({})
        self._sync()

    def _open_conf(self):
        ensure_mpv_conf()
        if not open_in_editor(MPV_CONF):
            messagebox.showwarning(self.t("mo_title"), self.t("mo_no_editor").format(path=MPV_CONF), parent=self)

    def _save(self):
        opts = self._collect()
        block = render_block(opts)
        new_text = compose_mpv_conf(read_mpv_conf(), block)
        if block:       # verificăm doar ce scriem noi; eventualele greșeli din restul fișierului nu ne privesc
            self.config(cursor="watch")
            self.save_btn.state(["disabled"])
            self.update_idletasks()
            ok, msg = validate_mpv_conf(self.mpv_cmd, "\n".join(block) + "\n")   # doar blocul nostru
            self.config(cursor="")
            self.save_btn.state(["!disabled"])
            if ok is not True:
                ask = self.t("mo_invalid" if ok is False else "mo_unchecked").format(err=msg)
                if not messagebox.askyesno(self.t("mo_title"), ask, parent=self, icon="warning"):
                    return
        try:
            write_mpv_conf(new_text)
        except OSError as e:
            messagebox.showerror(self.t("mo_write_err"), str(e), parent=self)
            return
        self.on_saved(opts)
        self.destroy()

    def _center(self, parent):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 3)
        self.geometry(f"+{x}+{y}")


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/about_window
#   Fereastra „Despre”: versiune, descriere, dezvoltator și comenzi rapide (dimensiune fixă, fără scroll).
# ──────────────────────────────────────────────────────────────────────────────

def make_info_icon(size=14, color=(30, 120, 210)):
    """Iconiță „info”: un „i” alb pe fundal de buline albastră, desenat cu anti-aliasing (PNG RGBA, fără PIL)."""
    ss, c = 4, size / 2
    rows = []
    for y in range(size):
        row = bytearray([0])                                     # filtru PNG: none
        for x in range(size):
            a = w = 0
            for sy in range(ss):
                for sx in range(ss):
                    px, py = (x + (sx + .5) / ss) / size * 20, (y + (sy + .5) / ss) / size * 20
                    if (px - 10) ** 2 + (py - 10) ** 2 <= 9.4 ** 2:
                        a += 1
                        if (px - 10) ** 2 + (py - 5.6) ** 2 <= 1.5 ** 2 or (8.7 <= px <= 11.3 and 8.3 <= py <= 15.4):
                            w += 1
            n = ss * ss
            if a:
                row += bytes(round((w * 255 + (a - w) * ch) / a) for ch in color)
                row.append(round(255 * a / n))
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


class AboutDialog(tk.Toplevel):
    """`host` = fereastra principală; folosim: root, t(), about_btn, bg_grey. Două taburi: „Despre program” și
    „Comenzi rapide”. Dimensiunea o dă conținutul; nu se redimensionează."""

    def __init__(self, host):
        super().__init__(host.root)
        self.title(host.t("about_btn"))
        self.transient(host.root)
        self.resizable(False, False)
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)

        # --- Tab 1: Despre program (conținutul e centrat pe verticală în casetă)
        t1 = ttk.Frame(nb, padding=(16, 8))
        nb.add(t1, text=host.t("about_tab_prog"))
        t1.columnconfigure(0, weight=1)
        t1.rowconfigure(0, weight=1)
        t1.rowconfigure(2, weight=1)
        mid = ttk.Frame(t1)
        mid.grid(row=1, column=0)
        pf, ps = tkfont.Font(family="DejaVu Sans", size=-36, weight="bold"), 3.0       # aceeași plăcuță ca pe difuzor, de 3 ori mai mare
        pw, ph = int(pf.measure(SpeakerGrille.TEXT) + 34 * ps) + 12, int(24 * ps) + 16
        plate = tk.Canvas(mid, width=pw, height=ph, bg=host.bg_grey, highlightthickness=0)
        draw_plate(plate, pw / 2, ph / 2, pf, SpeakerGrille.TEXT, ps)
        plate.pack(pady=(0, 10))
        ttk.Label(mid, text=host.t("about_version").format(v=VERSION), style="Hk.TLabel", anchor="center").pack(pady=(0, 10))
        for key in ("about_desc", "about_dev"):
            ttk.Label(mid, text=host.t(key), style="Hk.TLabel", wraplength=430, justify="center",
                      anchor="center").pack(pady=(0, 6))
        ttk.Separator(mid, orient="horizontal").pack(fill="x", pady=(6, 8))
        ttk.Label(mid, text=host.t("about_services"), style="HkB.TLabel", anchor="w").pack(fill="x", pady=(0, 4))
        ttk.Label(mid, text=host.t("about_services_list"), style="Hk.TLabel", wraplength=430, justify="left",
                  anchor="w").pack(fill="x")

        # --- Tab 2: Comenzi rapide (același format ca înainte)
        t2 = ttk.Frame(nb, padding=(12, 10))
        nb.add(t2, text=host.t("about_tab_keys"))
        # Două jumătăți egale, fără separator vizibil: descrierile se aliniază spre centru,
        # iar combinațiile de taste pornesc din centru spre dreapta.
        t2.columnconfigure(0, weight=1, uniform="hotkeys")
        t2.columnconfigure(1, weight=1, uniform="hotkeys")
        for r, (d, k) in enumerate(HOTKEYS):
            ttk.Label(t2, text=host.t(d), style="Hk.TLabel", wraplength=260, justify="right", anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 12), pady=2)
            ttk.Label(t2, text=host.t(k), style="HkB.TLabel", wraplength=240, justify="left", anchor="w").grid(
                row=r, column=1, sticky="w", padx=(12, 0), pady=2)

        # Buton cu aceeași lățime și înălțime ca „Despre” din panou, centrat.
        try:
            bw, bh = host.about_btn.winfo_width(), host.about_btn.winfo_reqheight()
        except tk.TclError:
            bw = bh = 0
        if bw < 40:
            bw = PANEL_W - 28
        box = ttk.Frame(outer, width=bw, height=max(bh, 24))
        box.pack(pady=(10, 0))
        box.pack_propagate(False)
        ttk.Button(box, text=host.t("about_close"), command=self.destroy).pack(fill="both", expand=True)
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        p = host.root
        x = p.winfo_rootx() + max(0, (p.winfo_width() - w) // 2)
        y = p.winfo_rooty() + max(0, (p.winfo_height() - h) // 2)
        y = max(0, min(y, self.winfo_screenheight() - h - 40))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(w, h)
        self.maxsize(w, h)

    @staticmethod
    def _embossed(parent, text, bg):
        """Titlu în relief (letterpress): strat alb jos-dreapta, umbră discretă, apoi fața textului; font cu serife."""
        f = tkfont.Font(family="DejaVu Serif", size=-38, weight="bold")
        w, h = f.measure(text) + 12, f.metrics("linespace") + 10
        cv = tk.Canvas(parent, width=w, height=h, bg=bg, highlightthickness=0)
        cx, cy = w // 2 - 1, h // 2 - 1
        layers = ((2, 2, "#141517"), (1, 1, "#18191c"), (-1, -1, "#4c5057"), (0, 0, "#d8dadf")) if DARK else \
                 ((2, 2, "#ffffff"), (1, 1, "#ffffff"), (-1, -1, "#9a9a9a"), (0, 0, "#4f4f4f"))
        for dx, dy, col in layers:
            cv.create_text(cx + dx, cy + dy, text=text, font=f, fill=col)
        return cv


def fold(s):
    """Text fără diacritice și majuscule (căutarea găsește «Pro TV» și cu «pro tv», «Știri» cu «stiri»)."""
    return "".join(c for c in unicodedata.normalize("NFD", s.casefold()) if not unicodedata.combining(c))





# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/tuner_window
#   Fereastra „Tuner TV”: alegerea tunerului, scanările de canale (cablu / antenă) și detectarea canalelor codate.
#
#   Fereastră cu dimensiuni fixe (lățimea panoului principal, ca butoanele să fie la fel de late), creată o singură dată
#   și doar ascunsă / arătată: widgeturile ei (adapter, butoanele de scanare, bara de progres) rămân ale ferestrei
#   principale, care le folosește ca înainte. Zona barei de progres e rezervată, deci fereastra nu se mărește la scanare.
# ──────────────────────────────────────────────────────────────────────────────

class TunerWindow(tk.Toplevel):
    """`host` = fereastra principală; folosim: root, t(), tr, bg_grey, f_norm, detect_tuners(), update_scan_buttons(),
    start_scan(mod), cancel_scan(), start_ca_detect()."""

    def __init__(self, host):
        super().__init__(host.root)
        self.host = host
        self.withdraw()
        self.title(host.t("tuner_title"))
        self.configure(bg=host.bg_grey)
        self.resizable(False, False)
        self.transient(host.root)
        self.protocol("WM_DELETE_WINDOW", self.hide)
        self.bind("<Escape>", lambda e: self.hide())

        mf = ttk.Frame(self, padding=14)
        mf.pack(fill="both", expand=True)
        self.close_btn = self._btn(mf, "tuner_close", self.hide, side="bottom")      # primul împachetat: rămâne jos

        lrow = ttk.Frame(mf)
        lrow.pack(fill="x", pady=5)
        refresh = ttk.Button(lrow, text="↻", width=2, command=host.detect_tuners)
        refresh.pack(side="left", padx=(0, 6))
        self.refresh_tip = Tip(refresh, "")
        tl = ttk.Label(lrow)
        tl.pack(side="left")
        host.tr.append((tl, "tuner_label"))
        self.adapter = ttk.Combobox(mf, state="readonly", font=host.f_norm)
        self.adapter.bind("<<ComboboxSelected>>", lambda e: host.update_scan_buttons())
        self.adapter.pack(fill="x", pady=5)

        self.scan_c_btn = self._btn(mf, "scan_c", lambda: host.start_scan("dvbc"))
        self.scan_t_btn = self._btn(mf, "scan_t", lambda: host.start_scan("dvbt"))
        self.ca_btn = self._btn(mf, "ca_btn", host.start_ca_detect)

        self.scan_zone = ttk.Frame(mf)        # aici apar bara de progres și „Anulează scanarea”
        self.scan_zone.pack(fill="x")
        self.progress_bar = ttk.Progressbar(self.scan_zone, mode="indeterminate")
        self.cancel_btn = ttk.Button(self.scan_zone, text=host.t("scan_cancel"), command=host.cancel_scan)
        host.tr.append((self.cancel_btn, "scan_cancel"))

        self.fit()

    def fit(self):
        """Înălțime fixă: cât încape tot, cu bara de progres și „Anulează” afișate. Se recalculează la fiecare afișare,
        pentru că tema (butoane mai înalte în dark) și fonturile schimbă dimensiunile."""
        self.scan_zone.pack_propagate(True)
        self.scan_zone.configure(height=1)
        self.progress_bar.pack_forget()
        self.cancel_btn.pack_forget()
        self.progress_bar.configure(length=10)
        self.update_idletasks()
        zone = (self.progress_bar.winfo_reqheight() + 10) + (self.cancel_btn.winfo_reqheight() + 10) + 6
        self.scan_zone.configure(height=zone)
        self.scan_zone.pack_propagate(False)
        self.update_idletasks()
        self.height = self.winfo_reqheight() + 16

    def _btn(self, parent, key, cmd, side="top"):
        w = ttk.Button(parent, text=self.host.t(key), command=cmd)
        w.pack(side=side, fill="x", pady=5)
        self.host.tr.append((w, key))
        return w

    def show(self):
        scanning = self.progress_bar.winfo_ismapped()
        self.fit()
        if scanning:
            self.progress_bar.pack(fill="x", pady=5)
            self.cancel_btn.pack(fill="x", pady=(0, 5))
        r = self.host.root
        r.update_idletasks()
        x = r.winfo_rootx() + max(0, (r.winfo_width() - TUNER_W) // 2)
        y = r.winfo_rooty() + 60
        self.geometry(f"{TUNER_W}x{self.height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_set()

    def hide(self):
        self.withdraw()

    def is_open(self):
        return self.winfo_exists() and self.state() != "withdrawn"


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE media  ·  Logo-uri de posturi, postere de filme (cu link IMDb), grila de difuzor retro
# ──────────────────────────────────────────────────────────────────────────────
CACHE_DIR = CONF_DIR / "cache"
LOGO_TTL = 30 * 86400      # logo-urile (și indexul de canale) se reactualizează la 30 de zile
IPTV_CHANNELS = "https://iptv-org.github.io/api/channels.json"      # baza de date deschisă iptv-org (canale + țară)
IPTV_LOGOS = "https://iptv-org.github.io/api/logos.json"
CC3 = {"ROU": "RO", "MDA": "MD", "ITA": "IT", "GBR": "GB", "DEU": "DE", "FRA": "FR", "ESP": "ES", "PRT": "PT", "HUN": "HU",
       "BGR": "BG", "SRB": "RS", "HRV": "HR", "SVN": "SI", "SVK": "SK", "CZE": "CZ", "POL": "PL", "AUT": "AT", "CHE": "CH",
       "BEL": "BE", "NLD": "NL", "DNK": "DK", "SWE": "SE", "NOR": "NO", "FIN": "FI", "GRC": "GR", "TUR": "TR", "UKR": "UA",
       "IRL": "IE", "LUX": "LU", "ALB": "AL", "MKD": "MK", "BIH": "BA", "MNE": "ME", "LTU": "LT", "LVA": "LV", "EST": "EE",
       "CYP": "CY", "MLT": "MT", "ISL": "IS", "USA": "US", "CAN": "CA", "AUS": "AU", "BRA": "BR"}
COUNTRY_NAMES = {"RO": "România", "MD": "Moldova", "IT": "Italia", "GB": "United Kingdom", "DE": "Deutschland", "FR": "France",
                 "ES": "España", "PT": "Portugal", "HU": "Magyarország", "BG": "България", "RS": "Srbija", "HR": "Hrvatska",
                 "SI": "Slovenija", "SK": "Slovensko", "CZ": "Česko", "PL": "Polska", "AT": "Österreich", "CH": "Schweiz",
                 "BE": "België", "NL": "Nederland", "DK": "Danmark", "SE": "Sverige", "NO": "Norge", "FI": "Suomi",
                 "GR": "Ελλάδα", "TR": "Türkiye", "UA": "Україна", "IE": "Ireland", "US": "United States", "CA": "Canada",
                 "AU": "Australia", "BR": "Brasil"}
TMDB_LANG = {"RO": "ro-RO", "MD": "ro-RO", "IT": "it-IT", "GB": "en-GB", "DE": "de-DE", "FR": "fr-FR", "ES": "es-ES",
             "PT": "pt-PT", "HU": "hu-HU", "BG": "bg-BG", "RS": "sr-RS", "HR": "hr-HR", "SI": "sl-SI", "SK": "sk-SK",
             "CZ": "cs-CZ", "PL": "pl-PL", "AT": "de-AT", "CH": "de-CH", "BE": "nl-BE", "NL": "nl-NL", "DK": "da-DK",
             "SE": "sv-SE", "NO": "nb-NO", "FI": "fi-FI", "GR": "el-GR", "TR": "tr-TR", "UA": "uk-UA", "IE": "en-IE",
             "US": "en-US", "CA": "en-CA", "AU": "en-AU", "BR": "pt-BR"}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
NEWS = re.compile(r"\b(stiri(le|lor)?|stire(a)?|news|notizie|telegiornale|tg\s?\d?|rainews\d*|"
                  r"observator|focus|telejurnal(ul)?|jurnal(ul)?|ultima ora|breaking)\b")        # emisiuni de știri: în loc de poster se desenează un afiș (după titlu)


def mlog(msg, *args):
    """Jurnal pentru logo/poster, doar pentru depanare: se scrie în ~/.config/TeleopsDVB/media.log numai dacă
    programul e pornit cu variabila TELEOPS_DEBUG=1. Altfel nu scrie nimic pe disc."""
    if not os.environ.get("TELEOPS_DEBUG"):
        return
    lg = logging.getLogger("teleops.media")
    if not lg.handlers:
        lg.setLevel(logging.INFO)
        lg.propagate = False
        try:
            from logging.handlers import RotatingFileHandler
            h = RotatingFileHandler(CONF_DIR / "media.log", maxBytes=200_000, backupCount=1, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            lg.addHandler(h)
        except OSError:
            lg.addHandler(logging.NullHandler())
    lg.info(msg, *args)


_SSL_CTX = []


def _ssl_context():
    """Contextul SSL: întâi certificatele sistemului (în aplicațiile împachetate, Python nu le găsește singur), apoi certifi."""
    if not _SSL_CTX:
        import ssl
        ctx = None
        for cafile in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
                       "/etc/ssl/cert.pem", "/etc/ssl/ca-bundle.pem"):
            if cafile and Path(cafile).exists():
                try:
                    ctx = ssl.create_default_context(cafile=cafile)
                    break
                except (OSError, ssl.SSLError):
                    pass
        if ctx is None:
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except (ImportError, OSError):
                ctx = ssl.create_default_context()
        _SSL_CTX.append(ctx)
    return _SSL_CTX[0]


def http_get(url, timeout=12, limit=80_000_000, headers=None):
    """Descarcă un URL; face fallback SSL la erori de certificat și întoarce None la alte erori."""
    import ssl
    req = urllib.request.Request(url, headers={"User-Agent": f"Mozilla/5.0 TeleopsDVB/{VERSION}", "Accept-Encoding": "gzip",
                                               "Accept": "*/*", **(headers or {})})
    for ctx in (_ssl_context(), ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                data = r.read(limit)
                return gzip.decompress(data) if r.headers.get("Content-Encoding") == "gzip" else data
        except ssl.SSLCertVerificationError as e:
            mlog("SSL fallback pentru %s: %s", url, e)
            continue
        except Exception as e:
            mlog("GET eșuat %s: %s", url, e)
            return None
    return None


def norm_name(s):
    s = re.sub(r"[^a-z0-9+ ]+", " ", fold(s))
    s = re.sub(r"\b(hd|fhd|uhd|4k|sd|hevc|h265|h264|dvb|mpeg4|mpeg2)\b", " ", s)
    return " ".join(t for t in s.split() if t != "+")


def name_variants(s):
    n = norm_name(s)
    v = {n, n.replace(" ", "")}
    for suf in (" ro", " md", " romania", " moldova", " tv", " channel", " international"):
        if n.endswith(suf):
            base = n[:-len(suf)].strip()
            if base:
                v |= {base, base.replace(" ", "")}
                v.add(base + " romania")
                v.add(base + " tv")
    if n and not n.endswith(" tv"):
        v.add(n + " tv")
        v.add((n + " tv").replace(" ", ""))
    return {x for x in v if x}


def image_to_png(data, max_w, max_h):
    """Orice imagine (JPEG, PNG, WEBP...) -> PNG încadrat în max_w x max_h. Încearcă PIL, apoi ffmpeg, apoi mpv (convertor);
    la urmă, un PNG/GIF se folosește ca atare (Tk îl micșorează). None dacă nu se poate."""
    if not data:
        return None
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        im = im.convert("RGBA")
        im.thumbnail((max_w, max_h), getattr(Image, "Resampling", Image).LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG")
        mlog("imagine convertită cu PIL (%d octeți)", len(data))
        return out.getvalue()
    except ImportError:
        pass
    except Exception as e:
        mlog("PIL a eșuat: %s", e)
    scale = f"scale=w='min(iw,{max_w})':h='min(ih,{max_h})':force_original_aspect_ratio=decrease"
    ff = shutil.which("ffmpeg")
    if ff:
        try:
            r = subprocess.run([ff, "-v", "error", "-i", "pipe:0", "-vf", scale, "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"],
                               input=data, capture_output=True, timeout=25, env=get_clean_env())
            if r.returncode == 0 and r.stdout.startswith(PNG_MAGIC):
                mlog("imagine convertită cu ffmpeg (%d octeți)", len(data))
                return r.stdout
            mlog("ffmpeg a eșuat: %s", r.stderr[-200:])
        except (OSError, subprocess.SubprocessError) as e:
            mlog("ffmpeg a eșuat: %s", e)
    mpv = shutil.which("mpv")
    if mpv:
        import tempfile
        try:
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / "in.img").write_bytes(data)
                r = subprocess.run([mpv, "--no-config", "--no-terminal", "--really-quiet", "--ao=null", "--vo=image", "--vo-image-format=png",
                                    f"--vo-image-outdir={td}", "--frames=1", f"--vf=lavfi=[{scale}]", str(Path(td) / "in.img")],
                                   capture_output=True, timeout=25, env=get_clean_env())
                out = next(iter(sorted(Path(td).glob("*.png"))), None)
                if out:
                    mlog("imagine convertită cu mpv (%d octeți)", len(data))
                    return out.read_bytes()
                mlog("mpv nu a produs imaginea: %s", r.stderr[-200:])
        except (OSError, subprocess.SubprocessError) as e:
            mlog("mpv a eșuat: %s", e)
    if data[:8] == PNG_MAGIC or data[:3] == b"GIF":
        mlog("imagine folosită ca atare (fără convertor)")
        return data
    mlog("imagine neconvertibilă (nici PIL, nici ffmpeg, nici mpv); primii octeți: %r", data[:8])
    return None


def fit_photo(img, w, h):
    """Micșorează un PhotoImage întreg (subsample) până încape în w x h."""
    f = max(-(-img.width() // max(w, 1)), -(-img.height() // max(h, 1)), 1)
    return img.subsample(f) if f > 1 else img


def clean_title(t):
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t or "")
    t = re.sub(
        r"^(film(ul)?( artistic| serial| de actiune| de acțiune)?|serial(ul)?|premier[aă]|reluare|telenovel[aă]|super ?film|în direct|in direct|live)\s*[:\-–]\s*",
        "", t, flags=re.I
    )
    t = re.sub(
        r"\bS\d{1,2}\b.*$|\bsezon(ul)?\s*\d+.*$|\bep(izod(ul)?)?\.?\s*\d+.*$|[-–:]\s*partea\s*[0-9ivx]+.*$",
        "", t, flags=re.I
    )
    t = re.sub(r"\b(premier[aă]|reluare|dublat|subtitrat|16:9|4:3)\b", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[„”“\"']", "", t)).strip(" -–:.,")


def _title_queries(q):
    """Generează variante ordonate de căutare (titlu complet, apoi titlul principal fără subtitlu)."""
    out = []
    for cand in (q, re.split(r"\s*[:\-–]\s*", q, maxsplit=1)[0].strip()):
        if len(cand) >= 3 and cand not in out:
            out.append(cand)
    return out


class MediaLookup:
    """Logo-urile (iptv-org, după țară) și posterele (IMDb / Apple / TVmaze / opțional TMDB) se caută în fire separate
    și se țin în ~/.config/TeleopsDVB/cache, ca fiecare lucru să se descarce o singură dată."""

    @staticmethod
    def cleanup_cache():
        """La pornire: logo-urile mai vechi de 30 de zile se șterg (se descarcă din nou la nevoie), intrările vechi din
        posters.json la fel, iar fișierele de jurnal rămase de la versiuni vechi dispar. O singură dată se șterg și
        imaginile vechi din cache (înainte aici se salvau și posterele)."""
        now = time.time()
        try:
            marker = CACHE_DIR / ".v2"
            purge_all = CACHE_DIR.is_dir() and not marker.exists()
            if CACHE_DIR.is_dir():
                for f in CACHE_DIR.glob("img_*.bin"):
                    try:
                        if purge_all or now - f.stat().st_mtime > LOGO_TTL:
                            f.unlink()
                    except OSError:
                        pass
                if purge_all:
                    marker.write_text("2")
        except OSError:
            pass
        if not os.environ.get("TELEOPS_DEBUG"):
            for name in ("media.log", "media.log.1"):
                try:
                    (CONF_DIR / name).unlink(missing_ok=True)
                except OSError:
                    pass

    def __init__(self, tmdb_key=""):
        self.cleanup_cache()
        self.lock, self.tmdb_key = threading.Lock(), (tmdb_key or "").strip()
        self.logos, self.logos_fail, self.glob = {}, {}, None
        self._logo_miss = {}
        self._logo_site = {}                     # (nume normalizat, țară) -> site-ul canalului, găsit odată cu logo-ul
        self.posters = {}
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self.posters = json.loads((CACHE_DIR / "posters.json").read_text(encoding="utf-8"))
            self.posters = {k: v for k, v in self.posters.items()
                            if isinstance(v, dict) and time.time() - v.get("ts", 0) < LOGO_TTL}
        except (OSError, ValueError, AttributeError):
            self.posters = {}

    # ---- imagini
    def fetch_image(self, url, keep=True):
        """Descarcă o imagine. `keep=True` (logo-uri): se ține pe disc 30 de zile; `keep=False` (postere): doar în memorie,
        deci nu rămâne nimic pe disc după ce se termină filmul."""
        f = CACHE_DIR / ("img_" + hashlib.sha1(url.encode()).hexdigest()[:16] + ".bin")
        if keep:
            try:
                if f.exists() and time.time() - f.stat().st_mtime < LOGO_TTL:
                    return f.read_bytes()
            except OSError:
                pass
        data = http_get(url, 15, 15_000_000)
        if data and len(data) > 200:
            if keep:
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                except OSError:
                    pass
            return data
        return None

    # ---- logo
    def _rebuild_logo_indexes(self, cc):
        raw = http_get(IPTV_CHANNELS, 90)
        if not raw:
            self.logos_fail[cc] = time.time()
            return None
        try:
            chans = json.loads(raw)
            lraw = http_get(IPTV_LOGOS, 90)
            by = {}
            for l in (json.loads(lraw) if lraw else []):
                by.setdefault(l.get("channel"), []).append(l)
        except ValueError:
            self.logos_fail[cc] = time.time()
            return None
        items, glob = [], {}
        for c in chans:
            if c.get("closed"):
                continue
            cand = [l for l in by.get(c.get("id"), [])
                    if str(l.get("format", "")).upper() in ("PNG", "JPEG", "JPG", "GIF") and l.get("url")]
            cand.sort(key=lambda l: (str(l.get("format")).upper() == "PNG",
                                     (l.get("width") or 0) * (l.get("height") or 0)
                                     if (l.get("width") or 0) * (l.get("height") or 0) <= 1_000_000 else 0))
            url = cand[-1]["url"] if cand else c.get("logo")
            if not url:
                continue
            names = [c.get("name", "")] + list(c.get("alt_names") or [])
            if c.get("country") == cc:
                items.append({"n": names, "u": url, "w": c.get("website") or ""})
            for n in names:
                for v in name_variants(n):
                    glob.setdefault(v, []).append([c.get("country") or "", url, c.get("website") or ""])
        try:
            (CACHE_DIR / f"logos_{cc}.json").write_text(
                json.dumps({"v": 4, "ts": time.time(), "items": items}), encoding="utf-8"
            )
            (CACHE_DIR / "logos_all.json").write_text(
                json.dumps({"v": 4, "ts": time.time(), "g": glob}), encoding="utf-8"
            )
        except OSError:
            pass
        self.glob = glob
        mlog("index logo %s construit: %d canale în țară, %d variante globale", cc, len(items), len(glob))
        for it in items:
            it["v"] = set().union(*(name_variants(n) for n in it["n"]))
        self.logos[cc] = items
        return items

    def _logo_items(self, cc):
        with self.lock:
            if cc in self.logos:
                return self.logos[cc]
            if time.time() - self.logos_fail.get(cc, 0) < 120:
                return None
            f = CACHE_DIR / f"logos_{cc}.json"
            gfile = CACHE_DIR / "logos_all.json"
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                if time.time() - d.get("ts", 0) < 30 * 86400 and d.get("v") == 4 and gfile.exists():
                    items = d["items"]
                    for it in items:
                        it["v"] = set().union(*(name_variants(n) for n in it["n"]))
                    self.logos[cc] = items
                    return items
            except (OSError, ValueError, KeyError, TypeError):
                pass
            return self._rebuild_logo_indexes(cc)

    def _global(self):
        if self.glob is None:
            try:
                d = json.loads((CACHE_DIR / "logos_all.json").read_text(encoding="utf-8"))
                self.glob = d["g"] if d.get("v") == 4 else {}
            except (OSError, ValueError, KeyError, TypeError):
                self.glob = {}
        return self.glob

    def logo_bytes(self, channel, cc):
        mkey = (norm_name(channel), cc)
        if time.time() - self._logo_miss.get(mkey, 0) < 300:
            return None
        items = self._logo_items(cc)
        if items is None:
            items = []
            mlog("index local %s indisponibil; încerc indexul global pentru '%s'", cc, channel)
        q = name_variants(channel)
        hit = next((it for it in items if q & it["v"]), None)
        if not hit and items:
            qn, best = norm_name(channel), 0.0
            for it in items:
                for n in it["n"]:
                    r = difflib.SequenceMatcher(None, qn, norm_name(n)).ratio()
                    if r > best:
                        best, hit = r, it
            if best < 0.85:
                hit = None
        if hit:
            mlog("logo '%s' (%s): găsit în țară -> %s", channel, cc, hit["u"])
            self._logo_site[mkey] = hit.get("w") or ""
            img = self.fetch_image(hit["u"])
            if img:
                return img
        g = self._global()
        for v in sorted(q, key=len, reverse=True):
            c = g.get(v)
            if c:
                best = (next((e for e in c if e[0] == cc), None)
                        or next((e for e in c if e[0] == "RO"), None)
                        or c[0])
                url = best[1]
                self._logo_site[mkey] = best[2] if len(best) > 2 else ""
                mlog("logo '%s' (%s): găsit în indexul global -> %s", channel, cc, url)
                img = self.fetch_image(url)
                if img:
                    return img
        self._logo_miss[mkey] = time.time()
        mlog("logo '%s' (%s): negăsit (variante: %s)", channel, cc, sorted(q))
        return None

    def logo_site(self, channel, cc):
        """Site-ul canalului (din iptv-org), găsit la ultima căutare de logo; \"\" dacă nu e cunoscut."""
        return self._logo_site.get((norm_name(channel), cc), "")

    # ---- poster
    def _imdb(self, q, year, genre):
        qf = fold(q)
        first = qf[:1] if qf[:1].isalnum() and qf[:1].isascii() else "x"
        qq = urllib.parse.quote(qf)
        raw = (http_get(f"https://v3.sg.imdbws.com/suggestion/titles/{first}/{qq}.json", 10)
               or http_get(f"https://v2.sg.media-imdb.com/suggestion/{first}/{qq}.json", 10))
        if not raw:
            return None
        try:
            res = [d for d in json.loads(raw).get("d", []) if str(d.get("id", "")).startswith("tt")
                   and d.get("qid") in ("movie", "tvMovie", "tvSeries", "tvMiniSeries", "video")]
        except (ValueError, AttributeError, TypeError):
            return None
        qn = norm_name(q)
        mlog("IMDb '%s': %s", q, [(d.get("l"), d.get("y"), d.get("qid")) for d in res[:4]])
        for i, d in enumerate(res):
            r = difflib.SequenceMatcher(None, qn, norm_name(d.get("l", ""))).ratio()
            dy = d.get("y")
            # Titlul din EPG e adesea cel tradus (ex. «Triplu X» = «xXx»): IMDb îl găsește după titlurile alternative,
            # dar în răspuns apare titlul original, deci la filme primul rezultat se acceptă și fără asemănare de nume.
            year_ok = not (year and dy) or abs(dy - year) <= 1
            movie_top = (genre == 1 and i < 3 and d.get("qid") in ("movie", "tvMovie") and year_ok
                         and (i == 0 or (year and dy == year)))
            if r >= 0.76 or (year and dy == year and r >= 0.48) or (genre == 1 and i == 0 and r >= 0.45) or movie_top:
                img = (d.get("i") or {}).get("imageUrl")
                if img:
                    img = re.sub(r"\._V1_.*(\.\w+)$", r"._V1_UY540_\1", img)
                    return {"imdb": f"https://www.imdb.com/title/{d['id']}/", "img": img, "source": "IMDb"}
        return None

    def _imdb_find(self, q, year, genre):
        """Căutarea de pe site-ul IMDb (aceeași ca în browser, găsește și titlurile traduse)."""
        raw = http_get("https://www.imdb.com/find/?s=tt&q=" + urllib.parse.quote(q), 12,
                       headers={"Accept": "text/html", "Accept-Language": "ro,en;q=0.8"})
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', (raw or b"").decode("utf-8", "ignore"), re.S)
        if not m:
            mlog("IMDb find '%s': fără date (pagina blocată sau schimbată)", q)
            return None
        try:
            res = json.loads(m.group(1))["props"]["pageProps"]["titleResults"]["results"]
        except (ValueError, KeyError, TypeError):
            return None
        for i, it in enumerate(res[:3]):
            it = it.get("listItem") or it
            tid = it.get("id") or it.get("titleId") or ""
            img = ((it.get("titlePosterImageModel") or it.get("primaryImage") or {}).get("url") or "")
            ry = it.get("titleReleaseText") or it.get("releaseYear") or ""
            try:
                dy = int(re.search(r"\d{4}", str(ry)).group(0))
            except (AttributeError, ValueError):
                dy = None
            mlog("IMDb find '%s': #%d %s %s %s", q, i, tid, it.get("titleNameText") or it.get("titleText"), ry)
            if tid.startswith("tt") and img and (not (year and dy) or abs(dy - year) <= 1):
                img = re.sub(r"\._V1_.*(\.\w+)$", r"._V1_UY540_\1", img)
                return {"imdb": f"https://www.imdb.com/title/{tid}/", "img": img, "source": "IMDb-find"}
        return None

    def _apple(self, q, year, genre, cc="RO"):
        """Caută postere în catalogul Apple/iTunes Search API (întâi magazinul țării alese, apoi US dacă nu găsește)."""
        targets = [("movie", "movie")] if genre == 1 else [("tvShow", "tvSeason"), ("movie", "movie")]
        qn = norm_name(q)
        for media, entity in targets:
            for store in dict.fromkeys((cc.lower(), "us")):
                params = urllib.parse.urlencode({"term": q, "media": media, "entity": entity, "country": store, "limit": 25})
                raw = http_get("https://itunes.apple.com/search?" + params, 10)
                if not raw:
                    continue
                try:
                    res = json.loads(raw).get("results", [])
                except (ValueError, AttributeError, TypeError):
                    continue
                mlog("Apple-%s (%s) '%s': %s", store.upper(), media, q, [r.get("trackName") or r.get("collectionName") for r in res[:3]])
                for i, r in enumerate(res):
                    name = r.get("trackName") or r.get("collectionName") or ""
                    sim = difflib.SequenceMatcher(None, qn, norm_name(name)).ratio()
                    ry = int((r.get("releaseDate") or "0")[:4] or 0)
                    if sim >= 0.75 or (year and ry == year and sim >= 0.48) or (i == 0 and sim >= 0.55):
                        img = r.get("artworkUrl600") or r.get("artworkUrl100")
                        if img:
                            img = re.sub(r"\d+x\d+bb", "600x900bb", img)
                            return {"imdb": None, "img": img, "source": f"Apple-{store.upper()}"}
        return None

    def _tvmaze(self, q, year):
        """Caută afișe de seriale/emisiuni în TVmaze (API public, fără cheie)."""
        raw = http_get("https://api.tvmaze.com/search/shows?q=" + urllib.parse.quote(q), 10)
        if not raw:
            return None
        try:
            res = json.loads(raw)
        except (ValueError, TypeError):
            return None
        qn = norm_name(q)
        for i, item in enumerate(res):
            show = item.get("show") or {}
            name = show.get("name") or ""
            sim = difflib.SequenceMatcher(None, qn, norm_name(name)).ratio()
            premiered = int((show.get("premiered") or "0")[:4] or 0)
            if sim >= 0.75 or (year and premiered == year and sim >= 0.48) or (i == 0 and sim >= 0.52):
                img = show.get("image") or {}
                url = img.get("original") or img.get("medium")
                if url:
                    return {"imdb": show.get("url"), "img": url, "source": "TVmaze"}
        return None

    def _tmdb(self, q, year, genre, cc="RO"):
        k = urllib.parse.quote(self.tmdb_key)
        raw = http_get(
            f"https://api.themoviedb.org/3/search/multi?api_key={k}&language={TMDB_LANG.get(cc, 'en-US')}&include_adult=false&query={urllib.parse.quote(q)}",
            10
        )
        if not raw:
            return None
        try:
            res = [r for r in json.loads(raw).get("results", []) if r.get("media_type") in ("movie", "tv")]
        except (ValueError, AttributeError, TypeError):
            return None
        qn = norm_name(q)
        for i, r in enumerate(res):
            titles = [r.get("title"), r.get("name"), r.get("original_title"), r.get("original_name")]
            sim = max((difflib.SequenceMatcher(None, qn, norm_name(t)).ratio() for t in titles if t), default=0)
            ry = int((r.get("release_date") or r.get("first_air_date") or "0")[:4] or 0)
            if sim >= 0.72 or (year and ry == year and sim >= 0.48) or (genre == 1 and i == 0 and sim >= 0.45):
                ext = http_get(f"https://api.themoviedb.org/3/{r['media_type']}/{r['id']}/external_ids?api_key={k}", 10)
                try:
                    imdb = json.loads(ext).get("imdb_id")
                except (ValueError, AttributeError, TypeError):
                    imdb = None
                return {
                    "imdb": f"https://www.imdb.com/title/{imdb}/" if imdb else None,
                    "img": ("https://image.tmdb.org/t/p/w500" + r["poster_path"]) if r.get("poster_path") else None,
                    "source": "TMDB"
                }
        return None

    def poster(self, title, text, genre, cc="RO"):
        """(octeți imagine | None, link IMDb | None). Caută titlul curățat și variantele sale; `cc` = țara prioritară."""
        q = clean_title(title)
        if len(q) < 3:
            return None, None
        m = re.search(r"\b(19[2-9]\d|20[0-3]\d)\b", title + " " + (text or "")[:300])
        year = int(m.group(1)) if m else None
        key = norm_name(q) + "|" + str(year or "") + "|" + cc
        hit = self.posters.get(key)
        if not hit or (not hit.get("img") and time.time() - hit.get("ts", 0) > 90):
            found = None
            for cand_q in _title_queries(q):
                if self.tmdb_key:
                    found = self._tmdb(cand_q, year, genre, cc)
                if not (found and found.get("img")):
                    found = self._apple(cand_q, year, genre, cc)
                if not (found and found.get("img")):
                    found = self._imdb(cand_q, year, genre)
                if not (found and found.get("img")):
                    found = self._tvmaze(cand_q, year)
                if not (found and found.get("img")):
                    found = self._imdb_find(cand_q, year, genre)
                if found and found.get("img"):
                    break
            hit = found or {}
            hit["ts"] = time.time()
            self.posters[key] = hit
            try:
                (CACHE_DIR / "posters.json").write_text(json.dumps(self.posters), encoding="utf-8")
            except OSError:
                pass
        link = hit.get("imdb") or (
            "https://www.imdb.com/find/?s=tt&q=" + urllib.parse.quote(q)
            if hit is not None else None
        )
        img_bytes = self.fetch_image(hit["img"], keep=False) if hit.get("img") else None
        if hit.get("img") and not img_bytes:
            hit["img"] = None
            hit["ts"] = 0
            try:
                (CACHE_DIR / "posters.json").write_text(json.dumps(self.posters), encoding="utf-8")
            except OSError:
                pass
        mlog("poster '%s' (an %s, gen %s): sursa=%s imdb=%s imagine=%s ok=%s",
             q, year, genre, hit.get("source", "-"), hit.get("imdb"), hit.get("img"), bool(img_bytes))
        return img_bytes, link


def _smooth(t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * (3 - 2 * t)


def _over(buf, i, rgb, a):
    """Compune un pixel (alfa neprecalculat) peste cel din `buf`."""
    if a <= 0:
        return
    a = 1.0 if a > 1 else a
    j = i * 4
    da = buf[j + 3] / 255.0
    k = da * (1 - a)
    oa = a + k
    for n in range(3):
        buf[j + n] = max(0, min(255, int((rgb[n] * a + buf[j + n] * k) / oa + 0.5)))
    buf[j + 3] = int(oa * 255 + 0.5)


def _png_b64(size, rgba, height=None):
    height = height or size
    rows = b"".join(b"\0" + bytes(rgba[y * size * 4:(y + 1) * size * 4]) for y in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


_KNOB_BASE = {}
KNOB_AMBER, KNOB_RED, KNOB_UNLIT, KNOB_CREAM = (232, 144, 44), (224, 68, 42), (104, 104, 104), (244, 233, 201)


def _knob_base(S):
    """Partea fixă a rotiței (umbră, mărgine zimțată cromată, capac negru de bachelită) + pixelii celor 11 gradații.
    Anti-aliasing analitic (acoperire pe pixel), fără PIL; se calculează o singură dată și o folosesc toate rotițele."""
    if S in _KNOB_BASE:
        return _KNOB_BASE[S]
    c, r_edge, r_face = S / 2, 23.0, 19.4
    buf = bytearray(S * S * 4)
    for y in range(S):
        dy = y + 0.5 - c
        for x in range(S):
            dx, i = x + 0.5 - c, y * S + x
            _over(buf, i, (0, 0, 0), 0.36 * _smooth((r_edge + 3.5 - math.hypot(dx - 1.6, dy - 2.4)) / 5.0))   # umbra
            r = math.hypot(dx, dy)
            if r > r_edge + 1.2:
                continue
            phi = math.atan2(dy, dx)
            edge = r_edge + 0.55 * math.cos(32 * phi)                  # marginea zimțată (32 de dinți)
            cov = edge - r + 0.5
            if cov <= 0:
                continue
            light = 0.5 + 0.5 * math.cos(phi + 2.356)                   # lumină din stânga-sus
            lum = 100 + 105 * light + 12 * math.cos(32 * phi)
            skirt = (lum, lum * 0.97, lum * 0.88)                       # crom ușor cald
            fl = 32 + 40 * max(0.0, 1 - math.hypot(dx + 7.5, dy + 8.5) / 27.0)
            bev = 1 - 0.65 * _smooth((r - (r_face - 1.8)) / 1.8)        # muchie teșită, mai închisă
            face = (fl * 1.0 * bev, fl * 0.94 * bev, fl * 0.88 * bev)
            w = min(1.0, max(0.0, r_face - r + 0.5))
            col = [skirt[n] * (1 - w) + face[n] * w for n in range(3)]
            ol = 0.5 * _smooth((r - (edge - 1.2)) / 1.2)                # contur subțire, închis
            col = [col[n] * (1 - ol) + (45, 42, 40)[n] * ol for n in range(3)]
            _over(buf, i, col, cov)
    ticks = []
    for k in range(11):                                                 # gradațiile din jur, pe 270°
        ang = math.radians(225 - 27 * k)
        ux, uy = math.cos(ang), -math.sin(ang)
        r0, r1, wd = (26.2, 31.8, 2.5) if k % 5 == 0 else (27.6, 31.2, 1.8)
        x0, y0, x1, y1 = c + ux * r0, c + uy * r0, c + ux * r1, c + uy * r1
        vx, vy = x1 - x0, y1 - y0
        l2, pix = vx * vx + vy * vy, []
        for y in range(max(0, int(min(y0, y1) - 3)), min(S, int(max(y0, y1) + 4))):
            for x in range(max(0, int(min(x0, x1) - 3)), min(S, int(max(x0, x1) + 4))):
                px, py = x + 0.5, y + 0.5
                t = max(0.0, min(1.0, ((px - x0) * vx + (py - y0) * vy) / l2))
                cv = wd / 2 + 0.5 - math.hypot(px - x0 - t * vx, py - y0 - t * vy)
                if cv > 0:
                    pix.append((y * S + x, cv))
        ticks.append(pix)
    _KNOB_BASE[S] = (buf, ticks)
    return _KNOB_BASE[S]


class Knob(tk.Canvas):
    """Rotiță de reglaj în stil retro (capac negru, margine cromată zimțată, gradații care se aprind ca la un amplificator
    vechi). Se trage sus/jos sau se rotește cu rotița mouse-ului; dublu click = valoarea implicită. Gradațiile se aprind
    de la `origin` spre valoare (minim la volum, mijloc la joase/înalte); peste `warn_above` devin roșii."""
    S = 68

    def __init__(self, master, *, lo, hi, value, origin, step, wheel_step, default, fmt, command, bg, font, warn_above=None):
        super().__init__(master, width=self.S, height=self.S, bg=bg, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.value, self.origin = lo, hi, value, origin
        self.step, self.wheel_step, self.default = step, wheel_step, default
        self.fmt, self.command, self.warn_above = fmt, command, warn_above
        self._drag, self._cache = None, {}
        self._tf = tkfont.Font(font=font)
        self._tf.configure(size=-10)
        self._item = self.create_image(self.S / 2, self.S / 2)
        self._txt = self.create_text(self.S / 2, self.S / 2, font=self._tf, fill="#f4e9c9")
        self.bind("<ButtonPress-1>", lambda e: setattr(self, "_drag", (e.y, self.value)))
        self.bind("<B1-Motion>", self._moved)
        self.bind("<Double-Button-1>", lambda e: self._apply(self.default))
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(ev, self._wheel)
        self.draw()

    def _frac(self, v):
        return (v - self.lo) / ((self.hi - self.lo) or 1)

    def _image(self):
        key = (self.value, self.hi)
        img = self._cache.get(key)
        if img is None:
            base, ticks = _knob_base(self.S)
            buf, fv, fo = bytearray(base), self._frac(self.value), self._frac(self.origin)
            warn = self._frac(self.warn_above) if self.warn_above is not None else 9
            for k, pix in enumerate(ticks):
                kf = k / 10
                lit = fv != fo and min(fo, fv) - 1e-9 <= kf <= max(fo, fv) + 1e-9
                col = (KNOB_RED if kf > warn + 1e-9 else KNOB_AMBER) if lit else KNOB_UNLIT
                for i, cv in pix:
                    _over(buf, i, col, cv)
            a, c = math.radians(225 - 270 * fv), self.S / 2
            cx, cy = c + 16.4 * math.cos(a), c - 16.4 * math.sin(a)           # punctul-indicator crem
            for rad, color, op in ((2.9, (14, 12, 11), 0.65), (2.0, KNOB_CREAM, 1.0)):
                for y in range(int(cy - 5), int(cy + 6)):
                    for x in range(int(cx - 5), int(cx + 6)):
                        _over(buf, y * self.S + x, color, op * (rad + 0.5 - math.hypot(x + 0.5 - cx, y + 0.5 - cy)))
            img = tk.PhotoImage(master=self, data=_png_b64(self.S, buf))
            if len(self._cache) > 200:
                self._cache.clear()
            self._cache[key] = img
        return img

    def draw(self):
        self.itemconfigure(self._item, image=self._image())
        hot = self.warn_above is not None and self.value > self.warn_above
        self.itemconfigure(self._txt, text=self.fmt(self.value), fill="#ff8a6e" if hot else "#f4e9c9")

    def set(self, v):
        """Doar afișează valoarea (nu cheamă `command`)."""
        v = max(self.lo, min(self.hi, v))
        if v != self.value:
            self.value = v
            self.draw()

    def set_range(self, hi):
        self.hi = hi
        self.value = min(self.value, hi)
        self.draw()

    def _apply(self, v):
        v = int(round(max(self.lo, min(self.hi, v)) / self.step) * self.step)
        v = max(self.lo, min(self.hi, v))
        if v != self.value:
            self.value = v
            self.draw()
            self.command(v)

    def _moved(self, e):
        if self._drag:
            y0, v0 = self._drag
            self._apply(v0 + (y0 - e.y) * (self.hi - self.lo) / 120)       # 120 px de tras = tot intervalul

    def _wheel(self, e):
        up = e.num == 4 or (e.num != 5 and e.delta > 0)
        self._apply(self.value + (self.wheel_step if up else -self.wheel_step))
        return "break"


_SPK_CACHE = {}


def _speaker_png(D):
    """Difuzor retro desenat pixel cu pixel (fără PIL): inel argintiu mat cu 4 șuruburi + grilaj negru perforat
    (găuri în rețea hexagonală) cu două nervuri circulare, ca la grilajele de boxe auto. Lumina vine din stânga-sus.
    Se calculează o singură dată pentru fiecare diametru D și se ține în cache."""
    if D in _SPK_CACHE:
        return _SPK_CACHE[D]
    c = D / 2.0
    Ro = c - 3.0                                   # raza inelului exterior (restul = loc pentru umbră)
    Rg = Ro * 0.80                                 # raza grilajului
    ring_rs = (0.26 * Rg, 0.66 * Rg)               # cele două nervuri circulare fără perforații
    ring_w = max(1.3, Rg * 0.035)
    buf = bytearray(D * D * 4)
    for y in range(D):
        dy = y + 0.5 - c
        for x in range(D):
            dx, i = x + 0.5 - c, y * D + x
            r = math.hypot(dx, dy)
            if r > Ro + 5:
                continue
            _over(buf, i, (0, 0, 0), 0.35 * _smooth((Ro + 3.0 - math.hypot(dx - 1.2, dy - 2.0)) / 4.0))     # umbra
            cov = Ro - r + 0.5
            if cov <= 0:
                continue
            cov = min(1.0, cov)
            ux, uy = (dx / r, dy / r) if r > 1e-6 else (0.0, 0.0)
            light = -(ux + uy) * 0.7071                                  # +1 spre stânga-sus, -1 spre dreapta-jos
            if r >= Rg:                                                  # inelul argintiu
                t = (r - Rg) / (Ro - Rg)
                if t > 0.86:
                    lum = 182 + 52 * light                               # teșitura exterioară
                elif t < 0.14:
                    lum = 150 - 55 * light                               # buza interioară (privește spre centru)
                else:
                    lum = 188 + 10 * light                               # fața plată, mată
                lum *= 1 - 0.35 * _smooth((r - (Ro - 1.0)) / 1.0)         # contur exterior mai închis
                col = (lum, lum, lum + 4)
            else:                                                        # grilajul
                lum = 20 + 8 * light * (r / Rg)
                if r > Rg - 1.4:
                    lum = 8                                              # umbra de sub buză
                for rr in ring_rs:
                    d = abs(r - rr)
                    if d < ring_w:
                        lum = 30 + 22 * (1 - d / ring_w) + 10 * light * (1 if r > rr else -1)
                col = (lum, lum, lum + 2)
            _over(buf, i, [max(0, min(255, v)) for v in col], cov)
    pitch = max(2.8, Rg / 26.0)                                          # perforațiile, în rețea hexagonală
    hr, rowsp = max(0.85, pitch * 0.30), pitch * 0.866
    n = int(Rg / rowsp) + 2
    for j in range(-n, n + 1):
        cy = c + j * rowsp
        for k in range(-n, n + 1):
            cx = c + k * pitch + (pitch / 2 if j % 2 else 0)
            r = math.hypot(cx - c, cy - c)
            if r > Rg * 0.965 - hr or any(abs(r - rr) < ring_w + hr * 0.6 for rr in ring_rs):
                continue
            for py in range(int(cy - hr - 1), int(cy + hr + 2)):
                for px in range(int(cx - hr - 1), int(cx + hr + 2)):
                    if not (0 <= px < D and 0 <= py < D):
                        continue
                    cv = hr + 0.5 - math.hypot(px + 0.5 - cx, py + 0.5 - cy)
                    if cv > 0:
                        v = 100 + 28 * ((px + 0.5 - cx) + (py + 0.5 - cy)) * 0.7071 / hr    # jos-dreapta mai luminos
                        v = max(60, min(135, v))
                        _over(buf, py * D + px, (v, v, v + 3), min(1.0, cv) * 0.85)
    rs = (Rg + Ro) / 2                                                   # 4 șuruburi pe inel, la 45°
    for ang in (45, 135, 225, 315):
        sx, sy = c + rs * math.cos(math.radians(ang)), c + rs * math.sin(math.radians(ang))
        for py in range(int(sy - 5), int(sy + 6)):
            for px in range(int(sx - 5), int(sx + 6)):
                if not (0 <= px < D and 0 <= py < D):
                    continue
                d = math.hypot(px + 0.5 - sx, py + 0.5 - sy)
                _over(buf, py * D + px, (128, 128, 132), min(1.0, 3.4 + 0.5 - d))       # teșitura găurii
                _over(buf, py * D + px, (36, 36, 38), min(1.0, 2.1 + 0.5 - d))          # gaura
                if d < 2.6:
                    _over(buf, py * D + px, (170, 170, 174), 0.5 * _smooth((px + 0.5 - sx + py + 0.5 - sy) / 3.0))
    _SPK_CACHE[D] = _png_b64(D, buf)
    return _SPK_CACHE[D]


def draw_plate(cv, cx, cy, font, text, s=1.0):
    """Plăcuța metalică argintie „Teleops DVB” (față cu degrade, muchii luminate, două nituri, text gravat), centrată în (cx, cy).
    `s` = scara: 1 pe difuzor, mai mare în fereastra „Despre” (`font` trebuie să fie deja scalat)."""
    pw, ph = font.measure(text) + 34 * s, 24 * s
    x0, y0 = cx - pw / 2, cy - ph / 2
    cv.create_rectangle(x0 + 2 * s, y0 + 3 * s, x0 + pw + 2 * s, y0 + ph + 3 * s, fill="#050506", outline="")   # umbra
    n = max(2, int(ph))
    for i in range(n):                                                                       # față argintie cu degrade vertical
        cv.create_line(x0, y0 + i * ph / n, x0 + pw, y0 + i * ph / n, fill=SpeakerGrille._grey(218 - 52 * i / (n - 1)),
                       width=max(1, int(round(ph / n)) + (1 if s > 1 else 0)))
    cv.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill="", outline="#2e2f32")                # contur închis
    cv.create_line(x0 + 1, y0 + 1, x0 + pw - 1, y0 + 1, fill="#f4f5f7")                      # muchie luminată sus
    cv.create_line(x0 + 1, y0 + 1, x0 + 1, y0 + ph - 1, fill="#e6e7ea")                      # și în stânga
    cv.create_line(x0 + 1, y0 + ph - 1, x0 + pw - 1, y0 + ph - 1, fill="#76777b")            # umbră jos
    cv.create_line(x0 + pw - 1, y0 + 1, x0 + pw - 1, y0 + ph - 1, fill="#86878b")            # și în dreapta
    for sx in (x0 + 8 * s, x0 + pw - 8 * s):                                                 # două nituri
        cv.create_oval(sx - 3 * s, cy - 3 * s, sx + 3 * s, cy + 3 * s, fill="#8d8e92", outline="#3a3b3e")
        cv.create_oval(sx - 1.8 * s, cy - 1.8 * s, sx + 1.8 * s, cy + 1.8 * s, fill="#242426", outline="")
        cv.create_line(sx - 2 * s, cy + 3.6 * s, sx + 2 * s, cy + 3.6 * s, fill="#f0f1f3")
    off = max(1, round(s))
    cv.create_text(cx + off, cy + off, text=text, font=font, fill="#f2f3f5")                 # text gravat
    cv.create_text(cx, cy, text=text, font=font, fill="#2c2d31")


class SpeakerGrille(tk.Canvas):
    """Difuzorul retro cu grilaj, cu emblema „Teleops DVB” pusă pe mijlocul lui, ca o plăcuță metalică argintie (aceleași
    nuanțe ca inelul difuzorului) prinsă cu două nituri. Are MĂRIME FIXĂ (nu se redimensionează niciodată), centrat doar
    pe orizontală și lipit sus (sub bara de separare). Canvasul cere exact cât ocupă difuzorul, așa că
    `Main.fit_min_height` nu lasă fereastra să se micșoreze până să-l taie. Imaginea se generează abia la prima afișare."""
    TEXT = "Teleops DVB"
    SIZE, PLATE_H, MARGIN = 200, 24, 10
    TOTAL_H = SIZE + 2 * MARGIN                      # înălțimea fixă a difuzorului (emblema e peste el, nu adaugă înălțime)

    def __init__(self, master, bg):
        super().__init__(master, bg=bg, highlightthickness=0,
                         height=self.TOTAL_H)     # înălțimea cerută = minimul
        self._img = None
        self._tf = tkfont.Font(family="DejaVu Sans", size=-12, weight="bold")
        self.bind("<Configure>", lambda e: self._draw(e.width, e.height))

    @staticmethod
    def _grey(v):
        v = max(0, min(255, int(v)))
        return f"#{v:02x}{v:02x}{min(255, v + 3):02x}"

    def _draw(self, w, h):
        if self._img is None:
            self._img = tk.PhotoImage(master=self, data=_speaker_png(self.SIZE))
        self.delete("all")
        top = self.MARGIN                                                                        # difuzor lipit sus, nu centrat
        self.create_image(w / 2, top, image=self._img, anchor="n")
        cx, cy = w / 2, top + self.SIZE / 2                                                      # emblema, pe mijlocul difuzorului
        draw_plate(self, cx, cy, self._tf, self.TEXT)


class JumpDialog(tk.Frame):
    """Salt rapid la canal (tasta J): căsuță așezată peste fereastra principală, în mijloc (în ecran complet = mijlocul ecranului).
    E un cadru în aceeași fereastră, nu o fereastră separată: focusul nu depinde de managerul de ferestre.
    Lista se filtrează la fiecare literă; ↑/↓ aleg, Enter redă, Esc închide. `host` = Main."""
    ROWS, W = 8, 400

    def __init__(self, host, items):
        super().__init__(host.root, bg=themed("#555555", ACCENT_LED), padx=2, pady=2)
        self.host, self.items, self.shown, self._closed = host, items, [], False
        bg = host.bg_grey
        body = tk.Frame(self, bg=bg, padx=10, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=host.t("jump_title"), font=host.f_bold, bg=bg, fg=themed(TXT_DARK, ACCENT_LED), anchor="w").pack(fill="x")
        big = tkfont.Font(font=host.f_norm)
        big.configure(size=-17)
        self.var = tk.StringVar()
        if DARK:
            self.entry = tk.Entry(body, textvariable=self.var, font=big, bg=BG_DARK, fg=TXT_LIGHT,
                                  insertbackground=ACCENT_LED, selectbackground=ACCENT_LED, selectforeground=ON_ACCENT,
                                  highlightthickness=1, highlightbackground=BORDER_SLATE, relief="flat")
        else:
            self.entry = tk.Entry(body, textvariable=self.var, font=big, bg="#ffffff", fg=TXT_DARK,
                                  insertbackground=TXT_DARK, relief="solid", bd=1)
        self.entry.pack(fill="x", pady=(6, 6), ipady=3)
        self.lb = tk.Listbox(body, height=self.ROWS, width=self.W // 8, font=host.f_norm, bg=bg, fg=TXT_DARK,
                             activestyle="none", exportselection=False, highlightthickness=0, relief="flat",
                             selectmode="browse", takefocus=0)
        self.lb.pack(fill="both", expand=True)
        self.status = tk.Label(body, font=host.f_hk, bg=bg, anchor="w")
        self.status.pack(fill="x", pady=(6, 0))

        self.var.trace_add("write", lambda *a: self.refresh())
        self.entry.bind("<Up>", lambda e: self.move(-1))
        self.entry.bind("<Down>", lambda e: self.move(1))
        self.entry.bind("<Prior>", lambda e: self.move(-self.ROWS))
        self.entry.bind("<Next>", lambda e: self.move(self.ROWS))
        for k in ("<Return>", "<KP_Enter>"):
            self.entry.bind(k, lambda e: self.choose())
        self.entry.bind("<Escape>", lambda e: self.close() or "break")
        self.lb.bind("<Button-1>", self._click)
        self.lb.bind("<Double-Button-1>", lambda e: self.choose())
        self.refresh()

        self.place(relx=0.5, rely=0.5, anchor="center")
        self.lift()
        self.update_idletasks()
        self.focus_entry()
        self._tries = 0
        self.after(40, self._watch)

    def focus_entry(self):
        try:
            self.lift()
            self.entry.focus_force()
            self.entry.icursor("end")
        except tk.TclError:
            pass

    def _watch(self):
        """Dacă mpv ține încă focusul tastaturii, îl cerem înapoi de câteva ori (tastele oricum nu se pierd: vezi feed_key)."""
        if self._closed or not self.winfo_exists():
            return
        self._tries += 1
        try:
            ok = self.focus_get() is self.entry
        except KeyError:
            ok = False
        if not ok:
            self.focus_entry()
        if self._tries < 40:
            self.after(60, self._watch)

    def feed_key(self, k):
        """Tasta a ajuns la mpv (nu la căsuță): o aplicăm aici, ca și cum ar fi fost tastată în câmp."""
        e = self.entry
        if len(k) == 1:
            e.insert("insert", k)
        elif k == "SPACE":
            e.insert("insert", " ")
        elif k == "BS":
            i = e.index("insert")
            if i:
                e.delete(i - 1)
        elif k in ("ENTER", "KP_ENTER"):
            self.choose()
        elif k == "ESC":
            self.close()
        elif k in ("UP", "DOWN"):
            self.move(-1 if k == "UP" else 1)
        elif k in ("PGUP", "PGDWN"):
            self.move(-self.ROWS if k == "PGUP" else self.ROWS)

    def refresh(self):
        q = fold(self.var.get()).split()
        full = " ".join(q)

        def rank(it):
            n = fold(it[0])
            return 0 if n.startswith(full) else 1 if any(w.startswith(full) for w in n.split()) else 2
        hits = [it for it in self.items if all(t in fold(it[0]) for t in q)]
        hits.sort(key=rank) if q else None
        self.shown = [n for n, _ in hits]
        self.lb.delete(0, "end")
        for _, label in hits:
            self.lb.insert("end", label)
        if hits:
            self.lb.selection_set(0)
            self.lb.activate(0)
            self.status.configure(text="↑ ↓     Enter     Esc", fg=themed("#666666", TXT_MUTED))
        else:
            self.status.configure(text=self.host.t("jump_none"), fg=themed("#dc2626", "#f87171"))

    def move(self, d):
        if self.shown:
            cur = self.lb.curselection()
            i = max(0, min(len(self.shown) - 1, (cur[0] if cur else 0) + d))
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(i)
            self.lb.activate(i)
            self.lb.see(i)
        return "break"

    def _click(self, e):
        i = self.lb.nearest(e.y)
        if 0 <= i < len(self.shown):
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(i)
        self.entry.focus_set()
        return "break"

    def choose(self):
        cur = self.lb.curselection()
        name = self.shown[cur[0]] if cur and cur[0] < len(self.shown) else None
        self.close()
        if name is not None:
            self.host.root.after(20, lambda: self.host.try_tune(name))
        return "break"

    def close(self):
        if self._closed:
            return
        self._closed = True
        host = self.host
        host.jump_win = None
        if host.stream:
            host.stream.capture_keys(False)
        self.destroy()
        host.root.focus_set()


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/main_window
#   Fereastra principală: panou cu comenzi + zonă video (mpv încorporat), listă de canale, scanare, înregistrare.
# ──────────────────────────────────────────────────────────────────────────────

class Main:
    def __init__(self, root, mpv_cmd):
        self.root, self.settings, self.mpv_cmd = root, load_settings(), mpv_cmd
        self.mpv_opts, self.mpv_dialog = clean_mpv_opts(self.settings.get("mpv_opts", {})), None
        self.schedule, self.rec_job = RecordingSchedule(SCHEDULE), None      # înregistrări programate din EPG
        self.watch, self.last_conflict, self.last_dropped = WatchSchedule(WATCH), None, []   # „Vreau să vizionez” + ultimul conflict / vizionări anulate
        self.lang = self.settings.get("lang") if self.settings.get("lang") in LANGS else LANGS[0]
        self.last_channel = self.settings.get("last_channel", "")
        self.favorites = set(self.settings.get("favorites", []))
        self._radio_names = set()
        self.events = queue.Queue()
        self.stream, self.tv_channels, self.radio_channels, self.cur, self.scan_proc = None, [], [], None, None
        self.scan_active, self.scan_cancelled = False, False
        self.rec_on, self._ph_active, self.epg_win = False, False, None
        self._pick, self._pick_job = None, None         # canalul ales cu ↑/↓ de pe video și comutarea lui programată
        self.rec_t0, self.muted = 0, bool(self.settings.get("muted", False))
        self.volume = max(0, min(int(self.settings.get("volume", 100)), VOL_MAX))
        self.adapter_items, self.tr = [], []
        self._autoplay_done = False
        self.info_mode, self._info_key, self._logo_tok, self._poster_tok = False, None, 0, 0
        self._logo_img = self._poster_img = None
        self._logo_link = None                   # pagina deschisă la click pe logo
        self._poster_raw = self._poster_link = None
        self._poster_title = ""
        self._news = False
        self._poster_last_attempt = 0.0
        self._poster_last_size = (0, 0)
        self.media = MediaLookup(self.settings.get("tmdb_key", ""))
        self.country_auto = str(self.settings.get("country_auto", "")).upper()
        self.prev_channel, self.jump_win, self._tone_job = self.settings.get("prev_channel", ""), None, None
        self.bass, self.treble = (self._tone_setting(k) for k in ("bass", "treble"))
        self.rec_dir = Path(self.settings.get("rec_dir") or REC_DIR)
        self.x11 = X11.create()
        self._stop_t, self._rec_osd_txt = 0.0, ""
        self.loading, self.load_name = False, ""

        self.list_items_meta = []
        self.locked, self.warmed, self.warm_busy, self._retry = set(), set(), False, 0

        if ICON_PATH.exists():
            try:
                self._icon = tk.PhotoImage(file=str(ICON_PATH))
                root.iconphoto(True, self._icon)
            except tk.TclError:
                pass

        self.video_side = self.settings.get("video_side") if self.settings.get("video_side") in ("left", "right") else "right"
        self.ui_visible, self.fullscreen, self._pre_fs_geom = True, False, ""
        gw, h, pos = 1100, 840, ""
        if m := re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", self.settings.get("geometry", "")):
            gw, h, pos = int(m.group(1)), int(m.group(2)), m.group(3) + m.group(4)
            if gw < PANEL_W + VIDEO_MIN_W:      # geometrie veche (fereastra avea doar panoul)
                gw = 1100
        root.geometry(f"{gw}x{h}{pos}")
        root.minsize(PANEL_W + VIDEO_MIN_W, 400)
        self._min_h = 0
        root.resizable(True, True)

        for fmt, letters, fn in (("<Key-{}>", "iI", self.on_key_i),                 # informații canal (EPG + semnal)
                                 ("<Control-Key-{}>", "rR", self.toggle_rec),       # pornește/oprește înregistrarea
                                 ("<Control-Key-{}>", "iI", lambda e: self.show_epg()),   # fereastra Program TV (EPG)
                                 ("<Control-Shift-Key-{}>", "xX", lambda e: self.on_close()),
                                 ("<Key-{}>", "fF", self.on_key_f)):                # ecran complet
            for ch in letters:
                root.bind(fmt.format(ch), fn)
        root.bind("<period>", self.on_key_dot)
        for ch in "jJ":
            root.bind(f"<Key-{ch}>", self.open_jump)           # salt rapid la canal
        for ch in "mM":
            root.bind(f"<Key-{ch}>", self.on_key_m)            # mute / unmute
        root.bind("<Button-1>", self._click_away, add="+")
        for ch in "hH":
            root.bind(f"<Control-{ch}>", self.on_key_info)      # ascunde lista / arată logo + poster + difuzor     # click în afara căutării J o închide
        root.bind("<BackSpace>", self.on_key_back)             # canalul anterior
        root.bind("<F11>", self.toggle_fullscreen)

        base = tkfont.nametofont("TkDefaultFont")

        def font(size, weight):
            f = base.copy()
            f.configure(size=size, weight=weight)
            return f
        self.f_norm, self.f_bold, f_brand = font(-13, "normal"), font(-13, "bold"), font(-18, "bold")
        self.f_load, self.f_hk, self.f_hkb = font(-22, "bold"), font(-11, "normal"), font(-11, "bold")
        
        st = self.st = ttk.Style()
        self.f_brand = f_brand
        self._themed, self._combos, self._dark_seen = [], [], False
        st.theme_use("default")
        self.light_bg = st.lookup("TFrame", "background") or root.cget("bg")       # fundalul gri original (tema luminoasă)
        self._root_light_bg = root.cget("bg")
        probe = tk.Listbox(root)
        self.light_lb = tuple(probe.cget(k) for k in ("background", "foreground", "selectbackground", "selectforeground"))
        probe.destroy()
        mode = self.settings.get("theme", "light")
        self.theme_mode = mode if mode in THEME_MODES else "light"
        set_dark(False)         # se construiește cu aspectul original; tema aleasă se aplică la sfârșit (apply_theme)
        self._style_ttk()
        bg_grey = self.bg_grey


        # Panou cu comenzi (lățime fixă) + zonă video (mpv încorporat prin --wid). Ordinea de împachetare
        # o stabilește layout(): panoul primește partea opusă playerului, video-ul ocupă restul.
        self.panel = tk.Frame(root, width=PANEL_W)
        self.panel.pack_propagate(False)
        self._tkpaint(root, {"bg": self._root_light_bg}, {"bg": BG_SLATE})
        self._tkpaint(self.panel, {}, {"bg": BG_SLATE})
        self.video = tk.Frame(root, bg=self.bg_grey, width=640, height=360)
        self._tkpaint(self.video, {"bg": bg_grey}, {"bg": BG_DARK})
        self.video.pack(side="left", fill="both", expand=True)
        self.chrome = WindowChrome(root, self.video, self.x11, get_stream=lambda: self.stream,
                                   is_fullscreen=lambda: self.fullscreen)
        self.video.bind("<Button-1>", lambda e: self.video.focus_set())
        self.video.bind("<Double-Button-1>", self.toggle_ui)   # când nu rulează mpv (altfel îl prinde mpv)
        # mesaj în mijlocul zonei video cât mpv nu are încă imagine (e acoperit automat de fereastra mpv)
        self.video_lbl = tk.Label(self.video, bg=self.bg_grey, fg="#555555", font=self.f_load, justify="center")
        self._tkpaint(self.video_lbl, {"bg": bg_grey, "fg": "#555555"}, {"bg": BG_DARK, "fg": TXT_MUTED})
        self.video_lbl.bind("<Button-1>", lambda e: self.video.focus_set())
        self.video_lbl.bind("<Double-Button-1>", self.toggle_ui)
        main = ttk.Frame(self.panel, padding=14)
        main.pack(fill="both", expand=True)
        self.main = main

        # Zona de jos se împachetează prima (side="bottom"): la micșorarea ferestrei pe verticală
        # se strânge doar lista de canale, iar butoanele de sus și de jos rămân mereu vizibile.
        bottom = ttk.Frame(main)
        bottom.pack(side="bottom", fill="x")

        top = ttk.Frame(main)
        top.pack(fill="x", pady=5)
        top.columnconfigure(0, weight=1)
        self.brand = ttk.Label(top, text=TITLE, style="Brand.TLabel", anchor="center")
        self.chrome.bind_drag(self.brand, click=self.on_brand_click)   # tragere = mută fereastra; click = vedere „informații”
        self.brand.configure(cursor="hand2")
        self.brand.grid(row=0, column=0, sticky="ew")
        self.rec_lbl = ttk.Label(main, style="Rec.TLabel", anchor="center")
        self.top = top

        self.tuner_container = tc = ttk.Frame(main)
        tc.pack(fill="x")
        ttk.Separator(tc, orient="horizontal").pack(fill="x", pady=(0, 5))      # desparte setările de titlu
        lg_row = ttk.Frame(tc)         # eticheta și selectorul de limbă pe același rând
        lg_row.pack(fill="x", pady=5)
        lg_lbl = ttk.Label(lg_row)
        lg_lbl.pack(side="left", padx=(0, 8))
        self.tr.append((lg_lbl, "lang_label"))
        self.lang_box = ttk.Combobox(lg_row, values=LANGS, state="readonly", font=self.f_norm)
        self.lang_box.set(self.lang)
        self.lang_box.bind("<<ComboboxSelected>>", self.on_lang)
        self.lang_box.pack(side="left", fill="x", expand=True)

        self.tuner_btn = self._btn(tc, "tuner_btn", self.show_tuner)      # sub selectorul de limbă
        # Alegerea tunerului, scanările și detectarea canalelor codate sunt în fereastra „Tuner TV”; widgeturile
        # ei rămân folosite de restul programului sub aceleași nume.
        self.tuner_win = tw = TunerWindow(self)
        self.refresh_tip, self.adapter = tw.refresh_tip, tw.adapter
        self.scan_c_btn, self.scan_t_btn, self.ca_btn = tw.scan_c_btn, tw.scan_t_btn, tw.ca_btn
        self.progress_bar, self.cancel_btn = tw.progress_bar, tw.cancel_btn
        self._combos.append(self.adapter)
        self.chlist_btn = None   # creat mai jos, în zona de jos, deasupra butonului „Despre”
        self._btn(tc, "cfg_mpv", self.open_mpv_config)
        self._btn(tc, "side_btn", self.swap_side)
        self.rec_tip = Tip(self._btn(tc, "rec_dir", self.choose_rec_dir), str(self.rec_dir))
        self.reset_tip = Tip(self._btn(tc, "reset_btn", self.reset_program), "", wrap=320)
        self.borderless_var = tk.BooleanVar(value=bool(self.settings.get("borderless", False)))
        cb = ttk.Checkbutton(tc, variable=self.borderless_var, command=self.apply_borderless)
        cb.pack(fill="x", pady=(5, 0))
        self.tr.append((cb, "borderless"))
        self.autoplay_var = tk.BooleanVar(value=bool(self.settings.get("autoplay_last", False)))
        cb2 = ttk.Checkbutton(tc, variable=self.autoplay_var)
        cb2.pack(fill="x", pady=(5, 0))
        self.tr.append((cb2, "autoplay_last"))
        self.fast_var = tk.BooleanVar(value=bool(self.settings.get("fast_switch", True)))
        cb3 = ttk.Checkbutton(tc, variable=self.fast_var)
        cb3.pack(fill="x", pady=(5, 0))
        self.tr.append((cb3, "fast_switch"))
        self.fast_tip = Tip(cb3, "", wrap=300)
        self.ts_var = tk.BooleanVar(value=bool(self.settings.get("timeshift", False)))
        cb5 = ttk.Checkbutton(tc, variable=self.ts_var, command=self.on_timeshift)
        cb5.pack(fill="x", pady=(5, 0))
        self.tr.append((cb5, "ts_enable"))
        self.ts_tip = Tip(cb5, "", wrap=320)
        self.ts_mode = "ram" if self.settings.get("timeshift_mode") == "ram" else "disk"
        tmr = ttk.Frame(tc)
        tmr.pack(fill="x", pady=(5, 0))
        tml = ttk.Label(tmr)
        tml.pack(side="left", padx=(0, 8))
        self.tr.append((tml, "ts_mode_label"))
        self.ts_mode_box = ttk.Combobox(tmr, state="readonly", font=self.f_norm)
        self.ts_mode_box.pack(side="left", fill="x", expand=True)
        self.ts_mode_box.bind("<<ComboboxSelected>>", self.on_ts_mode)
        self._combos.append(self.ts_mode_box)
        tsr = ttk.Frame(tc)
        tsr.pack(fill="x", pady=(5, 0))
        tsl = ttk.Label(tsr)
        tsl.pack(side="left", padx=(0, 8))
        self.tr.append((tsl, "ts_size_label"))
        self.ts_box = ttk.Combobox(tsr, state="readonly", font=self.f_norm)
        try:
            saved_mb = int(self.settings.get("timeshift_mb", TIMESHIFT_SIZES[0]))
        except (ValueError, TypeError):
            saved_mb = TIMESHIFT_SIZES[0]
        self._fill_ts_sizes(saved_mb)
        self.ts_box.pack(side="left", fill="x", expand=True)
        self.ts_box.bind("<<ComboboxSelected>>", self.on_timeshift)
        self._combos.append(self.ts_box)
        self._sync_ts_box()
        self.show_media_var = tk.BooleanVar(value=bool(self.settings.get("show_media", True)))
        cb4 = ttk.Checkbutton(tc, variable=self.show_media_var, command=self.on_toggle_media)
        cb4.pack(fill="x", pady=(5, 0))
        self.tr.append((cb4, "show_media"))
        cr = ttk.Frame(tc)
        cr.pack(fill="x", pady=(5, 0))
        cl = ttk.Label(cr)
        cl.pack(side="left", padx=(0, 8))
        self.tr.append((cl, "country_label"))
        self.country_box = ttk.Combobox(cr, state="readonly", font=self.f_norm)
        self.country_box.pack(side="left", fill="x", expand=True)
        self.country_box.bind("<<ComboboxSelected>>", self.on_country)
        self.country_tip = Tip(self.country_box, "", wrap=300)
        thr = ttk.Frame(tc)
        thr.pack(fill="x", pady=(5, 0))
        thl = ttk.Label(thr)
        thl.pack(side="left", padx=(0, 8))
        self.tr.append((thl, "theme_label"))
        self.theme_box = ttk.Combobox(thr, state="readonly", font=self.f_norm)
        self.theme_box.pack(side="left", fill="x", expand=True)
        self.theme_box.bind("<<ComboboxSelected>>", self.on_theme)
        self._combos += [self.lang_box, self.country_box, self.theme_box]

        self.epg_lbl = box = ttk.Frame(main)
        box.pack(fill="x", pady=5)
        self.epg_k = [ttk.Label(box, style="EpgB.TLabel") for _ in range(2)]
        self.epg_v = [ttk.Label(box, style="Epg.TLabel", wraplength=215, justify="left") for _ in range(2)]
        self.epg_msg = ttk.Label(box, style="Epg.TLabel", wraplength=290, justify="left")
        self._epg_shown = None
        self.search_var = tk.StringVar()
        
        # Am înlocuit ttk.Entry cu tk.Entry și am adugat fundalul gri (bg=bg_grey)
        self.search = tk.Entry(bottom, textvariable=self.search_var, font=self.f_norm,
                               bg=bg_grey, fg=TXT_DARK, insertbackground=TXT_DARK,
                               relief="solid", bd=1)
        self._tkpaint(self.search, {"bg": bg_grey, "fg": "#000000", "insertbackground": "#000000", "relief": "solid", "bd": 1},
                      {"bg": BG_DARK, "fg": TXT_LIGHT, "insertbackground": ACCENT_LED, "selectbackground": ACCENT_LED,
                       "selectforeground": ON_ACCENT, "highlightthickness": 1, "highlightbackground": BORDER_SLATE,
                       "highlightcolor": ACCENT_LED, "relief": "flat"})
        
        self.search.bind("<FocusIn>", self._ph_hide)
        self.search.bind("<FocusOut>", self._ph_show)
        self.search_var.trace_add("write", lambda *a: self.fill_channels())

        self.main_sep = ttk.Separator(main, orient="horizontal")
        self.main_sep.pack(fill="x", pady=(5, 0))

        lf = ttk.Frame(main)
        lf.pack(fill="both", expand=True, pady=5)
        self.list_frame = lf
        sb = ttk.Scrollbar(lf, orient="vertical")
        
        self.chlist = ChannelList(lf, font=self.f_norm, bg=bg_grey, fg=TXT_DARK,
                                  yscrollcommand=sb.set, highlightthickness=0, relief="flat")
        sb.config(command=self.chlist.yview)
        sb.pack(side="right", fill="y")
        self.chlist.pack(side="left", fill="both", expand=True)
        
        self.chlist.bind("<Double-Button-1>", self.on_list_double)
        self.chlist.bind("<Control-Button-1>", self.on_ctrl_click)
        self.chlist.bind("<Control-1>", self.on_ctrl_click)
        
        for key in ("<Return>", "<KP_Enter>"):
            self.chlist.bind(key, self.on_list_enter)
        self.chlist.bind("<Button-3>", self.toggle_search)

        # Vedere „informații” (Ctrl+H sau click pe titlu): logo-ul postului și posterul filmului (sau difuzorul implicit).
        inf = self.info_frame = tk.Frame(main, bg=bg_grey)
        self._tkpaint(inf, {"bg": bg_grey}, {"bg": BG_SLATE})
        # Logo: lipit jos (deasupra barei de separare). Poster/difuzor: lipite sus (sub bara de separare). Toate au mărime fixă.
        self.logo_cv = tk.Canvas(inf, height=LOGO_H, bg=bg_grey, highlightthickness=0)
        self._tkpaint(self.logo_cv, {"bg": bg_grey}, {"bg": BG_SLATE})
        self.logo_cv.pack(side="bottom", fill="x", pady=(0, 6))
        self.poster_cv = tk.Canvas(inf, height=POSTER_H, bg=bg_grey, highlightthickness=0)
        self._tkpaint(self.poster_cv, {"bg": bg_grey}, {"bg": BG_SLATE})
        self.poster_cv.bind("<Button-1>", self._poster_click)
        self.poster_cv.bind("<Configure>", lambda e: self._later("_poster_job", self._rescale_poster))
        self.logo_cv.bind("<Configure>", lambda e: self._later("_logo_job", self._draw_logo))
        self.logo_cv.bind("<Button-1>", self._logo_click)
        self._poster_job = self._logo_job = None
        # Difuzor retro + plăcuță „Teleops DVB”: afișat implicit, înlocuit doar când există poster (sau afiș de știri)
        self.speaker = SpeakerGrille(inf, bg_grey)
        self._tkpaint(self.speaker, {"bg": bg_grey}, {"bg": BG_SLATE})
        self._sync_speaker()
        self.emboss_font = tkfont.Font(family="DejaVu Sans", size=-16, weight="bold")
        self.search.pack(fill="x", pady=5)

        self.bottom_sep = ttk.Separator(bottom, orient="horizontal")
        self.bottom_sep.pack(fill="x", pady=(0, 5))

        # „Despre”: buton cu iconiță (i alb pe bulină albastră), deasupra barei de volum; deschide o fereastră separată
        self.about_win = None
        self.info_img = tk.PhotoImage(data=make_info_icon())
        self.about_btn = ttk.Button(bottom, image=self.info_img, compound="left", command=self.show_about)
        self.tr.append((self.about_btn, "about_btn"))
        self.chlist_btn = ttk.Button(bottom, command=self.show_channel_list)
        self.tr.append((self.chlist_btn, "chlist_btn"))

        # Trei rotițe pe același rând: volum, joase, înalte (cu valoarea în mijloc și eticheta dedesubt)
        vol = self.vol_frame = ttk.Frame(bottom)
        vol.pack(fill="x", pady=5)
        for col in range(3):
            vol.columnconfigure(col, weight=1, uniform="knob")
        common = dict(bg=bg_grey, font=self.f_hkb)
        tone_fmt = lambda v: f"{v:+d}" if v else "0"
        self.vol_knob = Knob(vol, lo=0, hi=VOL_MAX, value=self.volume, origin=0, step=1, wheel_step=VOL_WHEEL_STEP,
                             default=100, fmt=lambda v: f"{v}%", command=self.on_volume, warn_above=100, **common)
        self.bass_knob = Knob(vol, lo=-TONE_MAX, hi=TONE_MAX, value=self.bass, origin=0, step=1, wheel_step=1,
                              default=0, fmt=tone_fmt, command=lambda v: self.on_tone("bass", v), **common)
        self.treble_knob = Knob(vol, lo=-TONE_MAX, hi=TONE_MAX, value=self.treble, origin=0, step=1, wheel_step=1,
                                default=0, fmt=tone_fmt, command=lambda v: self.on_tone("treble", v), **common)
        for col, knob in enumerate((self.vol_knob, self.bass_knob, self.treble_knob)):
            knob.grid(row=0, column=col, pady=(0, 2))
            self._tkpaint(knob, {"bg": bg_grey}, {"bg": BG_SLATE})
        self.mute_lbl = ttk.Label(vol, cursor="hand2", font=self.f_norm, anchor="center")
        self.mute_lbl.grid(row=1, column=0, sticky="ew")
        self.mute_lbl.bind("<Button-1>", self.toggle_mute)
        for col, key in ((1, "knob_bass"), (2, "knob_treble")):
            lbl = ttk.Label(vol, font=self.f_norm, anchor="center")
            lbl.grid(row=1, column=col, sticky="ew")
            self.tr.append((lbl, key))

        # Butonul EPG ocupă toată lățimea (textul rămâne centrat ca la cele de jos); ⚙ e suprapus pe marginea dreaptă
        epg_row = ttk.Frame(bottom)
        epg_row.pack(fill="x", pady=(5, 0))
        # Butonul EPG se oprește cu 5 px înainte de ⚙ (5 px = aceeași distanță ca între butoanele de pe verticală);
        # padding-ul stâng suplimentar (36 + 5) readuce textul exact în centrul lățimii întregi.
        ttk.Style().configure("Epg.TButton", padding=(3 + CFG_W + CFG_GAP, 3, 3, 3))
        self.epg_btn = ttk.Button(epg_row, command=self.show_epg, style="Epg.TButton")
        self.epg_btn.pack(fill="x", padx=(0, CFG_W + CFG_GAP))
        self.tr.append((self.epg_btn, "epg_btn"))
        self.cfg_btn = ttk.Button(epg_row, text="⚙", command=self.toggle_tuner)
        self.cfg_btn.place(relx=1.0, rely=0.0, anchor="ne", relheight=1.0, width=CFG_W)
        self.cfg_tip = Tip(self.cfg_btn, "")
        self.rec_btn = self._btn(bottom, "rec_off", lambda: self.set_recording(not self.rec_on), pady=(5, 0))
        self.stop_btn = self._btn(bottom, "stop_play", self.on_stop_btn, pady=(5, 0))

        self.apply_translations()
        self._ph_show()
        self.settings_on = bool(self.settings.get("tuner_visible", True))
        self.search_wanted = bool(self.settings.get("search_visible", True))
        self.set_settings_view(self.settings_on)
        self.show_volume(self.volume)
        self.show_mute(self.muted)
        self.reload()
        self.update_scan_buttons()
        self.detect_tuners()
        self.root.after(50, lambda: self.chlist.yview_moveto(self.settings.get("scroll_position", 0.0)))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.chrome.bind_dead_zones(self.panel, exclude=(self.brand, self.mute_lbl))
        self.chrome.bind_drag(self.video)
        self.chrome.bind_drag(self.video_lbl)
        self.chrome.bind_drag(self.speaker)
        root.after(40, self.chrome.start_mpv_poll)
        if self.borderless_var.get():
            root.after(400, self.apply_borderless)
        self.layout()
        self.apply_theme()
        threading.Thread(target=mpv_options, args=(self.mpv_cmd,), daemon=True).start()
        clean_timeshift_dir(self.ts_dir())      # resturi ale bufferului din dosarul înregistrărilor (mpv oprit brusc)
        root.after(20000, self._theme_poll)
        root.after(250, self.tick)
        root.after(100, self.poll_events)

    def t(self, key):
        return tr(self.lang, key)

    def _lbl(self, parent, key):
        w = ttk.Label(parent)
        w.pack(anchor="w", pady=5)
        self.tr.append((w, key))
        return w

    def _btn(self, parent, key, cmd, pady=(5, 0)):
        w = ttk.Button(parent, command=cmd)
        w.pack(fill="x", pady=pady)
        self.tr.append((w, key))
        return w

    @staticmethod
    def set_enabled(btn, on):
        btn.state(["!disabled"] if on else ["disabled"])

    def toggle_tuner(self):
        self.set_settings_view(not self.settings_on)

    def set_settings_view(self, show):
        """Setările și (lista de canale + EPG + căutare) se exclud reciproc."""
        self.settings_on = show
        for w in (self.tuner_container, self.chlist_btn, self.about_btn, self.bottom_sep, self.epg_lbl, self.main_sep, self.list_frame,
                  self.info_frame, self.search):
            w.pack_forget()
        if show:
            self.tuner_container.pack(fill="x")
            self.chlist_btn.pack(fill="x", pady=(5, 0), before=self.vol_frame)
            self.about_btn.pack(fill="x", pady=(5, 0), before=self.vol_frame)
            self.bottom_sep.pack(fill="x", pady=(5, 5), before=self.vol_frame)     # sub „Despre”, deasupra volumului
        else:
            self.bottom_sep.pack(fill="x", pady=(0, 5), before=self.vol_frame)
            self.epg_lbl.pack(fill="x", pady=5)
            self.main_sep.pack(fill="x", pady=(5, 0))
            (self.info_frame if self.info_mode else self.list_frame).pack(fill="both", expand=True, pady=5)
            if self.search_wanted and not self.info_mode:
                self.search.pack(fill="x", pady=5, before=self.bottom_sep)
        self._min_h = 0
        self.root.after_idle(self.fit_min_height)

    def show_channel_list(self):
        """Lista de canale se vede mereu (ieșim și din vederea „logo + poster”, care o ascunde)."""
        self.info_mode = False
        self.set_settings_view(False)

    def show_about(self):
        if self.about_win and self.about_win.winfo_exists():
            self.about_win.lift()
            return
        self.about_win = AboutDialog(self)

    def layout(self):
        """Aranjează panoul și video-ul: panoul pe partea opusă playerului sau ascuns complet."""
        self.panel.pack_forget()
        if self.ui_visible:
            self.panel.pack(side="right" if self.video_side == "left" else "left", fill="y", before=self.video)
            self._min_h = 0
            self.root.after_idle(self.fit_min_height)
        else:
            self.root.minsize(160, 120)
            self.root.focus_set()

    def toggle_ui(self, _=None):
        self.ui_visible = not self.ui_visible
        self.layout()

    def swap_side(self):
        self.video_side = "left" if self.video_side == "right" else "right"
        self.layout()

    def toggle_fullscreen(self, _=None):
        if not self.fullscreen:
            self._pre_fs_geom = self.root.geometry()
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def _typing(self):
        """True cât se scrie într-un câmp de text (scurtăturile `.`, `f` și `i` trebuie ignorate)."""
        try:
            if self.jump_win is not None and self.jump_win.winfo_exists():     # căutarea J deschisă: scurtăturile stau
                return True
            return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox))
        except (KeyError, tk.TclError):
            return False

    def on_key_dot(self, _=None):
        if not self._typing():
            self.toggle_ui()

    def on_key_f(self, _=None):
        if not self._typing():
            self.toggle_fullscreen()

    # ---------- vederea „informații”: logo + poster
    def on_key_info(self, _=None):
        if not self._typing():
            self.toggle_info()

    def on_brand_click(self):
        # Titlul rămâne o scurtătură funcțională și când panoul de setări este deschis.
        self.toggle_info()

    def toggle_info(self, _=None):
        # Vederea informații înlocuiește setările dacă acestea sunt deschise;
        # astfel Ctrl+H / click pe titlu produce întotdeauna o schimbare vizibilă.
        if self.settings_on:
            self.info_mode = True
            self.set_settings_view(False)
        else:
            self.info_mode = not self.info_mode
            self.set_settings_view(False)
        if self.info_mode:
            self._info_key = None
            self.root.after(60, lambda: self.refresh_info(True))

    def _sync_speaker(self):
        """Afișează difuzorul + emblema implicit; le înlocuiește cu poster_cv doar când există un poster sau afiș de știri."""
        has_poster = self.show_media_var.get() and (self._news or self._poster_img is not None)
        if self.show_media_var.get():
            if not self.logo_cv.winfo_manager():
                self.logo_cv.pack(side="bottom", fill="x", pady=(0, 6))
        else:
            self.logo_cv.pack_forget()

        if has_poster:
            self.speaker.pack_forget()
            if not self.poster_cv.winfo_manager():
                self.poster_cv.pack(side="top", fill="x", anchor="n")
        else:
            self.poster_cv.pack_forget()
            if not self.speaker.winfo_manager():
                self.speaker.pack(side="top", fill="x", anchor="n")

        self._min_h = 0
        self.root.after_idle(self.fit_min_height)

    def on_toggle_media(self):
        self._sync_speaker()
        if not self.show_media_var.get():
            self._logo_tok += 1
            self._poster_tok += 1
            self._logo_img = self._poster_img = self._poster_raw = self._poster_link = self._logo_link = None
            self._news = False
            self._poster_last_size = (0, 0)
            self._draw_logo()
            self._draw_poster()
        else:
            self._info_key = None
            self._poster_last_attempt = 0.0
            if self.info_mode and not self.settings_on:
                self.refresh_info(True)

    def _later(self, attr, fn):
        """Execută `fn` după o scurtă pauză de la ultimul eveniment de redimensionare (nu la fiecare pixel)."""
        old = getattr(self, attr, None)
        if old:
            self.root.after_cancel(old)
        setattr(self, attr, self.root.after(220, lambda: (setattr(self, attr, None), fn())))

    def country(self):
        """Țara pentru logo-uri: setarea „country”, apoi cea citită din semnal (TOT), apoi ultima cunoscută, apoi limba sistemului."""
        man = str(self.settings.get("country", "")).strip().upper()
        if len(man) == 2:
            return man
        c3 = getattr(self.stream.ts, "country3", None) if self.stream and self.stream.ts else None
        if c3 in CC3:
            self.country_auto = CC3[c3]
        if self.country_auto:
            return self.country_auto
        loc = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
        m = re.search(r"_([A-Z]{2})", loc)
        if m and not loc.lower().startswith("en_"):
            return m.group(1)
        return "RO"

    def _country_values(self):
        return [self.t("country_auto")] + [f"{c} – {n}" for c, n in COUNTRY_NAMES.items()]

    def _sync_country_box(self):
        man = str(self.settings.get("country", "")).strip().upper()
        vals = self._country_values()
        self.country_box.configure(values=vals)
        self.country_box.current(next((i for i, v in enumerate(vals) if i and v[:2] == man), 0))
        self.country_tip.text = self.t("country_tip")

    def on_country(self, _=None):
        i = self.country_box.current()
        self.settings["country"] = "" if i <= 0 else list(COUNTRY_NAMES)[i - 1]
        self.chlist.focus_set()
        self._info_key = None
        self._logo_miss_reset()
        if self.info_mode and not self.settings_on:
            self.refresh_info(True)

    def _logo_miss_reset(self):
        self.media._logo_miss.clear()

    def _now_event(self):
        ev, now = self.epg_events(), time.time()
        return ev[0] if ev and ev[0][0] <= now else None

    def refresh_info(self, force=False):
        if not self.show_media_var.get():
            return
        chan = self.cur if self.stream else None
        ev, cc = self._now_event(), self.country()
        key = (chan, cc, ev[:3] if ev else None)
        old, self._info_key = self._info_key, key
        if key == old and not force:
            retry_poster = (ev is not None and self._poster_img is None and
                            time.time() - self._poster_last_attempt >= 90)
            if retry_poster:
                self._start_poster(ev, cc)
            return
        channel_changed = old is None or old[0] != key[0]
        country_changed = old is None or old[1] != key[1]
        event_changed = old is None or old[2] != key[2]
        if force or channel_changed or country_changed:
            self._start_logo(chan, cc)
        retry_poster = (ev is not None and self._poster_img is None and
                        time.time() - self._poster_last_attempt >= 90)
        if force or channel_changed or country_changed or event_changed or retry_poster:
            self._start_poster(ev, cc)

    def _poster_box(self):
        """Caseta maximă a posterului: lățimea canvasului și înălțimea MAXIMĂ fixă (POSTER_H), nu cea curentă a canvasului."""
        w = self.poster_cv.winfo_width()
        return (max(w, 60) if w > 1 else INFO_W), POSTER_H

    def _cv_size(self, cv, dw, dh):
        return max(cv.winfo_width(), 60) if cv.winfo_width() > 1 else dw, max(cv.winfo_height(), 40) if cv.winfo_height() > 1 else dh

    def _start_logo(self, chan, cc):
        self._logo_tok += 1
        tok, self._logo_img, self._logo_link = self._logo_tok, None, None
        self._draw_logo()
        if not self.show_media_var.get() or not chan:
            return
        w, h = self._cv_size(self.logo_cv, INFO_W, LOGO_H)

        def work():
            png = image_to_png(self.media.logo_bytes(chan, cc), w - 40, h - 14)
            link = self.channel_link(chan, cc)
            self.events.put(lambda: self._logo_ready(tok, png, link))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _resolve_wiki_page(title, lang="ro"):
        """Întoarce URL-ul direct al paginii Wikipedia dacă există o potrivire clară, altfel None."""
        if not title:
            return None
        q = urllib.parse.quote(title)
        api = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={q}&limit=3&namespace=0&format=json"
        raw = http_get(api, timeout=6)
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
            titles = data[1] if len(data) > 1 else []
            urls = data[3] if len(data) > 3 else []
            if titles and urls:
                t_low = title.strip().lower()
                for t, u in zip(titles, urls):
                    if t.strip().lower() == t_low or t.strip().lower().startswith(t_low + " "):
                        return u
                return urls[0]
        except (ValueError, TypeError, IndexError):
            pass
        return None

    @classmethod
    def channel_link(cls, chan, cc="RO"):
        """Pagina de Wikipedia despre canalul TV, preferând limba română."""
        query = (chan or "").strip()
        if not query:
            return "https://ro.wikipedia.org/"
        cleaned = re.sub(r"\b(hd|fhd|uhd|4k|sd|hevc|h265|h264|dvb|mpeg4|mpeg2)\b", " ", query, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–:.,") or query
        candidates = [cleaned] if re.search(r"\btv\b", cleaned, re.I) else [f"{cleaned} TV", cleaned]
        langs = ["ro"] if (cc or "").upper() in ("RO", "MD") else ["ro", "en"]
        for lang in langs:
            for cand in candidates:
                direct = cls._resolve_wiki_page(cand, lang=lang)
                if direct:
                    return direct
        search_q = urllib.parse.quote(candidates[0])
        return f"https://ro.wikipedia.org/w/index.php?search={search_q}"

    def _logo_ready(self, tok, png, link=None):
        if tok != self._logo_tok or not png:
            return
        self._logo_link = link
        try:
            w, h = self._cv_size(self.logo_cv, INFO_W, LOGO_H)
            self._logo_img = fit_photo(tk.PhotoImage(master=self.root, data=base64.b64encode(png)), w - 40, h - 14)
        except tk.TclError:
            return
        self._draw_logo()

    def _draw_logo(self):
        cv = self.logo_cv
        cv.delete("all")
        if self.show_media_var.get() and self._logo_img is not None:            # fără logo încărcat nu se afișează nimic
            w, h = self._cv_size(cv, INFO_W, LOGO_H)
            cv.create_image(w // 2, h - 7, image=self._logo_img, anchor="s")      # lipit jos, deasupra barei de separare
        cv.configure(cursor="hand2" if self.show_media_var.get() and self._logo_img is not None and self._logo_link else "arrow")

    def _start_poster(self, ev, cc=None):
        cc = cc or self.country()
        self._poster_tok += 1
        tok = self._poster_tok
        self._poster_img = self._poster_raw = self._poster_link = None
        self._poster_last_size = (0, 0)
        # Știrile nu au poster (căutarea găsea filme fără legătură, ex. „Stirile” → un film): desenăm un afiș.
        # Doar după titlu: genul EPG 2 (News/Current affairs) e pus de unele canale (ex. Digi 24) pe toate emisiunile,
        # inclusiv talk-show-uri („La cină”), așa că nu e un criteriu de încredere pentru afișul de știri.
        self._news = bool(ev) and self.show_media_var.get() and bool(NEWS.search(fold(ev[2])))
        self._draw_poster()
        if not self.show_media_var.get() or not ev:
            self._poster_last_attempt = 0.0
            return
        if self._news:
            self._poster_last_attempt = time.time()
            return
        title, text = ev[2], ev[3]
        genre = self.epg_genre(ev)
        if genre is None and self.cur and re.search(r"film|cinema|movie", fold(self.cur)):
            genre = 1       # EPG-ul nu spune genul, dar canalul e de filme (Film Cafe, Film Mania...)
        self._poster_last_attempt = time.time()
        w, h = self._poster_box()

        def work():
            raw, link = self.media.poster(title, text, genre, cc)
            png = image_to_png(raw, w - 16, h - 2 * POSTER_PAD) if raw else None
            self.events.put(lambda: self._poster_ready(tok, raw, png, link, (w, h)))
        threading.Thread(target=work, daemon=True).start()

    def epg_genre(self, ev):
        ts = self.stream.ts if self.stream else None
        return ts.genre.get(ev[:3]) if ts else None

    def _poster_ready(self, tok, raw, png, link, size=(0, 0)):
        if tok != self._poster_tok:
            return
        self._poster_raw, self._poster_link = raw, link
        self._poster_last_size = size
        self._set_poster_png(png)

    def _set_poster_png(self, png):
        self._poster_img = None
        if png:
            try:
                w, h = self._poster_box()
                self._poster_img = fit_photo(tk.PhotoImage(master=self.root, data=base64.b64encode(png)), w - 16, h - 2 * POSTER_PAD)
            except tk.TclError:
                self._poster_img = None
        self._draw_poster()

    def _rescale_poster(self):
        """Fereastra și-a schimbat dimensiunea: posterul se refă la mărimea nouă (evitând conversiile duplicate)."""
        if not self.info_mode or not self.show_media_var.get():
            return
        if not self._poster_raw:
            self._draw_poster()
            return
        w, h = self._poster_box()
        if (w, h) == self._poster_last_size and self._poster_img is not None:
            self._draw_poster()
            return
        tok, raw = self._poster_tok, self._poster_raw

        def work():
            png = image_to_png(raw, w - 16, h - 2 * POSTER_PAD)
            self.events.put(lambda: tok == self._poster_tok and self._poster_ready(tok, raw, png, self._poster_link, (w, h)))
        threading.Thread(target=work, daemon=True).start()

    def _draw_news(self, cv):
        """Afiș stilizat pentru știri: două benzi identice ca stil (chenar alb, text alb, umbră): roșie „BREAKING NEWS”
        și albastră „Totul va fi bine!”."""
        w, h = self._poster_box()
        pad = 14
        lines = self.t("news_lines").split("\n")[:2]
        bands = ((lines[0], "#c0111f"), (lines[1], "#1f5fbf"))
        en_lines = tr("English", "news_lines").split("\n")[:2]       # mărimea se calculează mereu după textul englezesc (cel mai lung)
        size = 26
        while size > 9:
            f = tkfont.Font(family="DejaVu Sans", size=-size, weight="bold")
            if all(f.measure(t) <= w - 2 * pad - 14 for t in en_lines):
                break
            size -= 1
        band_h, gap = f.metrics("linespace") + 16, max(10, size // 2)
        y = POSTER_PAD
        cv.configure(height=min(POSTER_H, 2 * band_h + gap + 2 * POSTER_PAD))      # canvasul cât afișul, maxim POSTER_H
        for t, col in bands:
            cv.create_rectangle(pad // 2, y + 2, w - pad // 2 + 1, y + band_h + 2, fill=themed("#8a8a8a", "#161719"), outline="")   # umbră
            cv.create_rectangle(pad // 2, y, w - pad // 2, y + band_h, fill=col, outline="#ffffff", width=2)
            cv.create_text(w // 2, y + band_h // 2, text=t, font=f, fill="#ffffff")
            y += band_h + gap

    def _draw_poster(self):
        self._sync_speaker()
        cv = self.poster_cv
        cv.delete("all")
        if self.show_media_var.get() and self._news:
            self._draw_news(cv)
        elif self.show_media_var.get() and self._poster_img is not None:
            w = self._poster_box()[0]
            cv.configure(height=min(POSTER_H, self._poster_img.height() + 2 * POSTER_PAD))   # canvasul cât posterul (max POSTER_H)
            cv.create_image(w // 2, POSTER_PAD, image=self._poster_img, anchor="n")      # lipit sus, sub bara de separare
        cv.configure(cursor="hand2" if self.show_media_var.get() and self._poster_img is not None and self._poster_link else "arrow")

    @staticmethod
    def _open_url(url):
        try:
            subprocess.Popen(["xdg-open", url], env=get_clean_env(), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            import webbrowser
            webbrowser.open(url)

    def _poster_click(self, _=None):
        if self._poster_link and self._poster_img is not None:
            self._open_url(self._poster_link)

    def _logo_click(self, _=None):
        """Click pe logo: deschide pagina de Wikipedia a canalului (preferabil în română)."""
        if self._logo_link and self._logo_img is not None and self.show_media_var.get():
            self._open_url(self._logo_link)

    def on_key_m(self, _=None):
        if not self._typing():
            self.toggle_mute()

    def _click_away(self, e):
        jw = self.jump_win
        try:
            if jw is None or not jw.winfo_exists():
                return
            w = e.widget
            while isinstance(w, tk.Misc):
                if w is jw:
                    return
                w = w.master
        except tk.TclError:
            return
        jw.close()

    def on_key_back(self, _=None):
        if not self._typing():
            self.go_prev()

    def go_prev(self):
        """Backspace: înapoi la canalul văzut înainte (apăsat din nou, revine la cel de acum)."""
        known = {c for c, _ in self.tv_channels + self.radio_channels}
        if self.scan_active:
            return
        if self.prev_channel in known and self.prev_channel != self.cur:
            self.try_tune(self.prev_channel)
        elif self.stream:
            self.stream.toast(self.t("prev_none"), 2000)

    def open_jump(self, _=None):
        """Tasta J: căutare rapidă de canale în mijlocul ferestrei."""
        if self._typing() or self.scan_active:
            return
        if self.jump_win and self.jump_win.winfo_exists():
            self.jump_win.entry.focus_force()
            return
        seen, items = set(), []
        radio = {c for c, _ in self.radio_channels}
        names = [c for c, _ in self.tv_channels + self.radio_channels]
        for c in [n for n in names if n in self.favorites] + names:      # favoritele întâi, ca în listă
            if c in seen:
                continue
            seen.add(c)
            star = "★  " if c in self.favorites else "    "
            items.append((c, f"{star}{'📻' if c in radio else '📺'}  {c.strip()}{'   🔑' if c in self.locked else ''}"))
        if items:
            self.jump_win = JumpDialog(self, items)
            if self.stream:
                self.stream.capture_keys(True)

    def toggle_rec(self, _=None):
        if self.stream or self.rec_on:
            self.set_recording(not self.rec_on)

    def _sync_stop_btn(self):
        txt = self.t("stop_play" if self.stream else "quit_app")
        if self.stop_btn.cget("text") != txt:
            self.stop_btn.configure(text=txt)

    def on_stop_btn(self):
        if self.stream:
            self._stop_t = time.time()
            self.stop()
        elif time.time() - self._stop_t > 0.7:     # evită ieșirea accidentală la dublu click
            self.on_close()

    def on_ui_msg(self, msg):
        if self.jump_win is not None and msg != "quit-app":
            jw = self.jump_win
            try:
                if jw.winfo_exists():       # tastele au ajuns la mpv în loc de căsuță: le scriem noi, fără alte comenzi
                    if msg.startswith("key:"):
                        jw.feed_key(msg[4:])      # Enter / Esc pot închide căsuța chiar aici
                    if not jw._closed:
                        jw.focus_entry()
                    return
            except tk.TclError:
                pass
        if msg.startswith("key:"):
            return
        if msg == "toggle-ui":
            self.toggle_ui()
        elif msg == "toggle-fs":
            self.toggle_fullscreen()
        elif msg == "quit-app":
            self.on_close()
        elif msg == "toggle-rec":
            self.toggle_rec()
        elif msg == "show-epg":
            self.show_epg()
        elif msg == "toggle-mute":
            self.toggle_mute()
        elif msg == "toggle-info":
            self.toggle_info()
        elif msg == "prev-channel":
            self.go_prev()
        elif msg == "jump-channel":
            self.open_jump()
        elif msg in ("vol-up", "vol-down"):
            self.wheel_volume(VOL_WHEEL_STEP if msg == "vol-up" else -VOL_WHEEL_STEP)
        elif msg in ("ch-up", "ch-down"):
            self.pick_step(1 if msg == "ch-up" else -1)
        elif msg == "ch-enter":
            self.pick_commit()
        elif msg == "ch-cancel":
            self.pick_abort()

    # ---- mutarea ferestrei prin tragere (fără titlebar)

    def apply_borderless(self):
        if not self.chrome.set_borderless(self.borderless_var.get()):
            self.borderless_var.set(False)
            messagebox.showwarning(TITLE, self.t("x11_na"), parent=self.root)

    def fit_min_height(self):
        """Înălțimea minimă = tot ce nu e listă + LIST_MIN_H; astfel nimic din jur nu e tăiat."""
        if not self.ui_visible:
            return
        self.root.update_idletasks()
        need = self.main.winfo_reqheight()
        if not self.settings_on and not self.info_mode:          # cu setările / vederea „informații” lista e ascunsă
            need += LIST_MIN_H - self.list_frame.winfo_reqheight()
        if need != self._min_h:
            self._min_h = need
            self.root.minsize(PANEL_W + VIDEO_MIN_W, need)
        if self.root.winfo_ismapped() and not self.fullscreen and self.root.winfo_height() < need:
            self.root.geometry(f"{self.root.winfo_width()}x{need}")

    def poll_events(self):
        """Rulează evenimentele venite de la mpv. O eroare într-un eveniment nu mai oprește bucla (altfel moare tot
        ce vine de la mpv: scurtături, volum pe rotița mouse-ului, mesaje)."""
        try:
            while True:
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    ev()
                except Exception:
                    logging.getLogger("teleops").exception("eroare într-un eveniment mpv")
        finally:
            if not getattr(self, "_closing", False):
                self.root.after(30, self.poll_events)

    def on_lang(self, _=None):
        self.lang = self.lang_box.get()
        self.apply_translations()
        self.fill_channels()
        if self.stream:
            self.stream.send_labels()
            self.stream.show_tv_osd()

    def apply_translations(self):
        self.root.title(TITLE)
        for w, key in self.tr:
            w.configure(text=self.t(key))
        self.rec_btn.configure(text=self.t("rec_on" if self.rec_on else "rec_off"))
        self.show_mute(self.muted)
        if self.about_win and self.about_win.winfo_exists():      # textele ei nu se schimbă din mers: se închide
            self.about_win.destroy()
        self.refresh_tip.text = self.t("refresh_tip")
        self.cfg_tip.text = self.t("cfg_tip")
        self.fast_tip.text = self.t("fast_tip")
        self.reset_tip.text = self.t("reset_tip")
        self._draw_poster()
        self._sync_country_box()
        self._sync_theme_box()
        self._sync_ts_mode_box()
        self.ts_tip.text = self.t("ts_tip")
        self.tuner_win.title(self.t("tuner_title"))
        self._sync_stop_btn()
        self.update_video_msg()
        if self._ph_active:
            self.search_var.set(self.t("search_ph"))
        if not self.adapter_items:
            self.adapter.set(self.t("no_tuner"))

    # ---- schimbarea canalului cu ↑/↓ de pe video: banner cu numele, comutarea după CH_PICK_MS sau la Enter
    def _pick_names(self):
        """Canalele între care se mută ↑/↓: cele din lista afișată (cu filtrul de căutare), în ordinea ei, fără cele codate.
        Dacă filtrul n-a lăsat niciunul, toate canalele."""
        names = [m[1] for m in self.list_items_meta if m[0] == "channel" and m[1] not in self.locked]
        if not names:
            names = [c for c, _ in self.tv_channels + self.radio_channels if c not in self.locked]
        return names

    def pick_step(self, d):
        names = self._pick_names()
        if not names or not self.stream:
            return
        base = self._pick if self._pick in names else self.cur
        i = (names.index(base) + d) % len(names) if base in names else (0 if d > 0 else len(names) - 1)
        self._pick = names[i]
        if self._pick_job:
            self.root.after_cancel(self._pick_job)
        self._pick_job = self.root.after(CH_PICK_MS, self.pick_commit)
        self.stream.show_banner(self._pick.strip(), CH_PICK_MS, True)
        for idx, meta in enumerate(self.list_items_meta):        # lista arată și ea canalul ales
            if meta[0] == "channel" and meta[1] == self._pick:
                self.chlist.selection_clear(0, "end")
                self.chlist.selection_set(idx)
                if not self.settings_on:
                    self.chlist.see(f"{idx + 1}.0")
                break

    def pick_commit(self):
        """Pornește canalul ales cu ↑/↓ (după 3 secunde sau la Enter)."""
        name = self._pick
        self._pick_cancel()
        if name and name != self.cur:
            self.try_tune(name)

    def pick_abort(self):
        """Esc: renunță la canalul ales cu ↑/↓ (rămâne cel curent); fără alegere în curs, nu face nimic."""
        if not self._pick:
            return
        self._pick_cancel()
        if self.stream:
            self.stream.hide_banner()
        self.select_current()

    def _pick_cancel(self):
        self._pick = None
        if self._pick_job:
            self.root.after_cancel(self._pick_job)
            self._pick_job = None

    # ---- Timeshift
    def _ts_sizes(self):
        """Mărimile permise de modul ales: în RAM cel mult TIMESHIFT_RAM_MAX."""
        return tuple(n for n in TIMESHIFT_SIZES if self.ts_mode == "disk" or n <= TIMESHIFT_RAM_MAX)

    def _fill_ts_sizes(self, mb):
        """Pune în listă mărimile modului curent și alege `mb` (sau cea mai apropiată permisă)."""
        sizes = self._ts_sizes()
        self.ts_box.configure(values=[f"{n} MB" for n in sizes])
        self.ts_box.current(sizes.index(mb) if mb in sizes else (len(sizes) - 1 if mb > sizes[-1] else 0))

    def _ts_size(self):
        sizes, i = self._ts_sizes(), self.ts_box.current()
        return sizes[i] if 0 <= i < len(sizes) else sizes[0]

    def _sync_ts_mode_box(self):
        self.ts_mode_box.configure(values=[self.t("ts_mode_disk"), self.t("ts_mode_ram")])
        self.ts_mode_box.current(1 if self.ts_mode == "ram" else 0)

    def on_ts_mode(self, _=None):
        prev = self._ts_size()
        self.ts_mode = "ram" if self.ts_mode_box.current() == 1 else "disk"
        self._fill_ts_sizes(prev)
        self.on_timeshift(_)

    def ts_dir(self):
        """Unde ține mpv bufferul pe disc: dosarul „timeshift” din dosarul înregistrărilor."""
        return self.rec_dir / "timeshift"

    def ts_mb(self):
        """MB de buffer pentru Streamer; 0 = Timeshift oprit."""
        return self._ts_size() if self.ts_var.get() else 0

    def _sync_ts_box(self):
        st = "readonly" if self.ts_var.get() else "disabled"
        self.ts_box.configure(state=st)
        self.ts_mode_box.configure(state=st)

    def on_timeshift(self, _=None):
        self._sync_ts_box()
        if self.stream and self.cur:
            if self.rec_on:         # nu oprim o înregistrare pentru o setare
                self.stream.toast(self.t("ts_later"), 4000)
            else:
                self.tune(self.cur)
        elif _ is not None:
            self.chlist.focus_set()

    # ---- fereastra „Tuner TV”
    def show_tuner(self):
        self.tuner_win.show()

    # ---- „Programările mele” (fila din fereastra EPG)
    def my_schedules(self):
        """Înregistrările și vizionările programate care n-au pornit încă, în ordinea startului: [(\"rec\"|\"watch\", job)]."""
        rows = [("rec", j) for j in self.schedule.jobs if j.state != ACTIVE] + [("watch", j) for j in self.watch.jobs]
        return sorted(rows, key=lambda r: r[1].start)

    def cancel_schedule(self, kind, job):
        if kind == "rec":
            if job is self.rec_job:
                self.set_recording(False)
            self.schedule.remove(job)
        else:
            self.watch.remove(job)

    def clear_schedules(self):
        for kind, job in self.my_schedules():
            self.cancel_schedule(kind, job)

    # ---- temă: luminoasă (aspectul original) / întunecată (din darkmode.py) / automată (după sistem)
    def _style_ttk(self):
        """Stilurile ttk ale temei active. La schimbarea temei se refac toate (stilurile sunt ținute pe fiecare temă)."""
        st = self.st
        if not DARK:
            st.theme_use("default")
            st.configure("TLabel", font=self.f_bold)
            st.configure("Brand.TLabel", font=self.f_brand, foreground="#555555")   # aceeași culoare ca mesajul „Se încarcă...”
            st.configure("Rec.TLabel", font=self.f_bold, foreground="#dc2626")
            st.configure("Epg.TLabel", font=self.f_norm)
            st.configure("EpgB.TLabel", font=self.f_bold)
            st.configure("Hk.TLabel", font=self.f_hk)
            st.configure("HkB.TLabel", font=self.f_hkb)
            st.configure("TButton", font=self.f_norm)
            st.configure("TCheckbutton", font=self.f_norm)
            st.configure("TCombobox", font=self.f_norm)
            self.bg_grey = self.light_bg
        else:
            st.theme_use("clam")
            bg = self.bg_grey = BG_SLATE
            st.configure(".", background=bg, foreground=TXT_LIGHT, bordercolor=BORDER_SLATE,
                         darkcolor=BG_DARK, lightcolor=BORDER_SLATE, troughcolor=BG_DARK,
                         focuscolor=ACCENT_LED, selectbackground=ACCENT_LED, selectforeground=ON_ACCENT)
            st.configure("TFrame", background=bg)
            st.configure("TLabelframe", background=bg, bordercolor=BORDER_SLATE)
            st.configure("TLabelframe.Label", background=bg, foreground=ACCENT_LED, font=self.f_bold)
            st.configure("TSeparator", background=BORDER_SLATE)
            st.configure("TLabel", background=bg, foreground=TXT_LIGHT, font=self.f_bold)
            st.configure("Brand.TLabel", background=bg, font=self.f_brand, foreground=ACCENT_LED)
            st.configure("Rec.TLabel", background=bg, font=self.f_bold, foreground="#ff5c5c")
            st.configure("Epg.TLabel", background=bg, foreground=TXT_LIGHT, font=self.f_norm)
            st.configure("EpgB.TLabel", background=bg, foreground=ACCENT_LED, font=self.f_bold)
            st.configure("Hk.TLabel", background=bg, foreground=TXT_LIGHT, font=self.f_hk)
            st.configure("HkB.TLabel", background=bg, foreground=ACCENT_LED, font=self.f_hkb)
            st.configure("TButton", background=BG_PANEL, foreground=TXT_LIGHT, bordercolor=BORDER_SLATE,
                         padding=(8, 4), font=self.f_norm)
            st.map("TButton",
                   background=[("disabled", BG_SLATE), ("pressed", BG_DARK), ("active", ACCENT_HOVER)],
                   foreground=[("disabled", "#6a6e75"), ("active", "#ffffff")],
                   bordercolor=[("focus", ACCENT_LED), ("active", ACCENT_LED)])
            st.configure("TCheckbutton", background=bg, foreground=TXT_LIGHT,
                         indicatorbackground=BG_DARK, indicatorforeground=ACCENT_LED, font=self.f_norm)
            st.map("TCheckbutton",
                   background=[("active", bg)],
                   foreground=[("disabled", "#6a6e75"), ("active", "#ffffff")],
                   indicatorbackground=[("selected", BG_DARK), ("active", BG_PANEL)])
            st.configure("TCombobox", fieldbackground=BG_PANEL, background=BG_PANEL, foreground=TXT_LIGHT,
                         arrowcolor=ACCENT_LED, bordercolor=BORDER_SLATE, font=self.f_norm)
            st.map("TCombobox",
                   fieldbackground=[("readonly", BG_PANEL), ("disabled", BG_SLATE)],
                   foreground=[("readonly", TXT_LIGHT), ("disabled", "#6a6e75")],
                   bordercolor=[("focus", ACCENT_LED), ("hover", ACCENT_LED)])
            st.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG_DARK,
                         bordercolor=BORDER_SLATE, arrowcolor=ACCENT_LED)
            st.map("Vertical.TScrollbar", background=[("active", ACCENT_HOVER)])
            st.configure("Horizontal.TProgressbar", background=ACCENT_LED, troughcolor=BG_DARK, bordercolor=BORDER_SLATE)
            st.configure("Horizontal.TScale", background=bg, troughcolor=BG_DARK)
            st.configure("TNotebook", background=bg, bordercolor=BORDER_SLATE)
            st.configure("TNotebook.Tab", background=BG_DARK, foreground=TXT_MUTED, padding=(10, 4), font=self.f_norm)
            st.map("TNotebook.Tab",
                   background=[("selected", BG_PANEL), ("active", ACCENT_HOVER)],
                   foreground=[("selected", ACCENT_LED), ("active", TXT_LIGHT)])
        st.configure("Epg.TButton", padding=(3 + CFG_W + CFG_GAP, 3, 3, 3))

    def _tkpaint(self, w, light, dark):
        """Înregistrează un widget Tk (nu ttk) pentru schimbarea temei. `light` = opțiunile aspectului original;
        celelalte opțiuni pe care le schimbă `dark` își păstrează valoarea implicită din tema luminoasă."""
        saved = {k: w.cget(k) for k in dark if k not in light}
        self._themed.append((w, {**saved, **light}, dark))
        return w

    def _apply_tk_colors(self):
        alive = []
        for w, light, dark in self._themed:
            try:
                w.configure(**(dark if DARK else light))
            except tk.TclError:
                continue
            alive.append((w, light, dark))
        self._themed = alive

    def _theme_popdowns(self):
        """Culorile listelor derulante ale combobox-urilor (sunt widgeturi Tk separate, nu urmează stilul ttk)."""
        if not DARK and not self._dark_seen:
            return                      # tema luminoasă de la pornire: nimic de schimbat
        bg, fg, sbg, sfg = themed(self.light_lb, (BG_PANEL, TXT_LIGHT, ACCENT_LED, ON_ACCENT))
        for opt, val in (("background", bg), ("foreground", fg), ("selectBackground", sbg), ("selectForeground", sfg)):
            self.root.option_add(f"*TCombobox*Listbox.{opt}", val)         # cele create mai târziu (în dialoguri)
        for cb in self._combos:
            try:
                pop = self.root.tk.call("ttk::combobox::PopdownWindow", str(cb))
                self.root.tk.call(f"{pop}.f.l", "configure", "-background", bg, "-foreground", fg,
                                  "-selectbackground", sbg, "-selectforeground", sfg)
            except tk.TclError:
                pass

    def _sync_theme_box(self):
        self.theme_box.configure(values=[self.t("theme_light"), self.t("theme_dark"), self.t("theme_auto")])
        self.theme_box.current(THEME_MODES.index(self.theme_mode))

    def on_theme(self, _=None):
        i = self.theme_box.current()
        self.theme_mode = THEME_MODES[i] if 0 <= i < len(THEME_MODES) else "light"
        self.chlist.focus_set()
        self.apply_theme()

    def apply_theme(self, dark=None):
        """Aplică tema aleasă pe loc. Ferestrele secundare (Despre, EPG) se închid: se recreează cu tema nouă."""
        if dark is None:
            dark = system_prefers_dark() if self.theme_mode == "auto" else self.theme_mode == "dark"
        if bool(dark) == DARK:
            return
        set_dark(dark)
        self._dark_seen = self._dark_seen or DARK
        for win in (self.about_win, self.epg_win):
            try:
                if win and win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                pass
        self._style_ttk()
        self._apply_tk_colors()
        self.tuner_win.configure(bg=self.bg_grey)
        self.chlist.retheme(self.bg_grey)
        self._theme_popdowns()
        self._draw_poster()
        self._draw_logo()

    def _theme_poll(self):
        """Cu tema „Automată”, urmărește schimbarea temei sistemului (la 20 s, într-un fir: nu blochează interfața)."""
        if getattr(self, "_closing", False):
            return
        if self.theme_mode == "auto":
            def work():
                dark = system_prefers_dark()
                self.events.put(lambda: self.theme_mode == "auto" and self.apply_theme(dark))
            threading.Thread(target=work, daemon=True).start()
        self.root.after(20000, self._theme_poll)

    def show_volume(self, v):
        self.volume = v
        self.vol_knob.set(v)

    def show_mute(self, m):
        self.muted = m
        self.mute_lbl.configure(text=f"{'🔇' if m else '🔊'} {self.t('osd_volume')}")

    def _tone_setting(self, key):
        try:
            return max(-TONE_MAX, min(TONE_MAX, int(self.settings.get(key, 0))))
        except (TypeError, ValueError):
            return 0

    def on_tone(self, which, v):
        """Joase / înalte: mesaj imediat, filtrul audio se reface după 150 ms (nu la fiecare pas de tras)."""
        setattr(self, which, v)
        if self.stream:
            self.stream.toast(f"{self.t('knob_' + which)}: {v:+d} dB", 2500)
            if self._tone_job:
                self.root.after_cancel(self._tone_job)
            self._tone_job = self.root.after(150, self._apply_tone)

    def _apply_tone(self):
        self._tone_job = None
        if self.stream:
            self.stream.set_tone(self.bass, self.treble)

    def on_volume(self, val):
        v = round(float(val))
        if v != self.volume:
            self.volume = v
            if self.stream:
                self.stream.set_prop("volume", v)
                self.stream.toast(f"{self.t('osd_volume')}: {v}%", 3000)

    def wheel_volume(self, delta):
        """Rotița de mouse de pe video: același drum ca glisorul (eticheta, mpv, mesajul „Volum”)."""
        v = int(max(0, min(self.vol_knob.hi, self.volume + delta)))
        self.on_volume(v)
        self.vol_knob.set(v)

    def toggle_mute(self, _=None):
        self.show_mute(not self.muted)
        if self.stream:
            self.stream.set_prop("mute", self.muted)
            self.stream.toast(self.t("osd_mute_on" if self.muted else "osd_mute_off"), 3000)

    def on_key_i(self, event=None):
        if self.stream and not self._typing():      # dezactivată cât timp se scrie în căutare
            self.stream.show_channel_info()

    def is_radio(self, name):
        return bool(name) and any(c == name for c, _ in self.radio_channels)

    def set_loading(self, name):
        self.loading, self.load_name = True, name
        self.update_video_msg()

    def update_video_msg(self):
        name = (self.load_name if self.loading else (self.cur or "")).strip()
        if self.loading:
            txt = f"{name}\n{self.t('loading')}" if name else self.t("loading")
        elif not self.stream:
            txt = f"📺⇄📻 {TITLE}"          # repaus: același stil ca la „Se încarcă...”
        elif self.is_radio(self.cur):
            txt = f"📻  {name}"
        else:
            txt = ""
        if txt:
            self.video_lbl.configure(text=txt)
            self.video_lbl.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.video_lbl.place_forget()

    def on_mpv_prop(self, name, v):
        if name == "volume": self.show_volume(round(v))
        elif name == "mute": self.show_mute(bool(v))
        elif name == "volume-max": self.vol_knob.set_range(v)
        elif (name == "vo-configured" and v) or (name == "audio-params" and self.is_radio(self.cur)):
            if self.loading:           # a apărut imaginea (sau sunetul, la radio): dispare „Se încarcă...”
                self.loading = False
                self.update_video_msg()

    def _ph_show(self, _=None):
        if not self.search_var.get():
            self._ph_active = True
            self.search_var.set(self.t("search_ph"))

    def _ph_hide(self, _=None):
        if self._ph_active:
            self._ph_active = False
            self.search_var.set("")

    def toggle_search(self, _=None):
        if self.info_mode:
            return
        scroll_pos = self.chlist.yview()
        self.search_wanted = not self.search_wanted
        if not self.search_wanted:
            self.chlist.focus_set()
            self._ph_active = False
            self.search_var.set("")
            self._ph_show()
            self.search.pack_forget()
        elif not self.settings_on:
            self.search.pack(fill="x", pady=5, before=self.bottom_sep)
        self.chlist.yview_moveto(scroll_pos[0])
        self.root.after_idle(self.fit_min_height)

    def select_current(self):
        name = self.cur or self.last_channel
        self.chlist.selection_clear(0, "end")
        if name:
            for idx, meta in enumerate(self.list_items_meta):
                if meta[0] == "channel" and meta[1] == name:
                    self.chlist.selection_set(idx)
                    break

    def _channel_at(self, i):
        """Numele canalului de la poziția i din listă (None pentru antete/spații)."""
        meta = self.list_items_meta[i] if 0 <= i < len(self.list_items_meta) else None
        return meta[1] if meta and meta[0] == "channel" else None

    def on_list_double(self, e):
        name = self._channel_at(self.chlist.nearest(e.y))
        if name is not None:
            self.try_tune(name)

    def try_tune(self, name):
        if name in self.locked:
            messagebox.showinfo(TITLE, self.t("scrambled"), parent=self.root)
        else:
            self.tune(name)

    def on_ctrl_click(self, e):
        name = self._channel_at(self.chlist.nearest(e.y))
        if name is not None:
            self.favorites ^= {name}      # adaugă/elimină din favorite
            self.fill_channels()

    def on_list_enter(self, _=None):
        sel = self.chlist.curselection()
        name = self._channel_at(sel[0]) if sel else None
        if name is not None:
            self.try_tune(name)

    def tick(self):
        self.root.after(250, self.tick)
        if self.stream and not self.stream.alive():
            s, name = self.stream, self.cur
            rc = s.zap.poll()
            self.stop()
            if (rc or 0) > 0:
                if not list_frontends():
                    messagebox.showerror(self.t("play_err"), self.t("tuner_crash"), parent=self.root)
                    self.detect_tuners()
                elif not s.got_data and self._retry < 1 and name and time.time() - s.t0 < 20:
                    # cold start: prima pornire a eșuat înainte să primească date -> a doua, automat
                    self.root.after(800, lambda: self.tune(name, 1))
                elif rc == 255:
                    messagebox.showerror(self.t("play_err"), self.t("tuner_crash"), parent=self.root)
                    self.detect_tuners()
                else:
                    messagebox.showerror(self.t("play_err"), f"dvbv5-zap: cod {rc}", parent=self.root)
        on = self.stream is not None
        self.set_enabled(self.rec_btn, on)
        self.set_enabled(self.epg_btn, on or bool(self.schedule.jobs or self.watch.jobs))     # fără redare: doar cu programări
        self._sync_stop_btn()      # fără redare, butonul devine „Închide programul”
        self.brand.configure(text=self.cur.strip() if on and self.cur else TITLE)
        self.set_epg(self.epg_now_next() if on else "")
        if self.info_mode and not self.settings_on:
            self.refresh_info()
        if self.rec_on:
            txt = self._rec_txt()
            self.rec_lbl.configure(text=txt)
            if self.stream and txt != self._rec_osd_txt:      # reîmprospătat la secundă; reface și overlay-ul dacă IPC era încă neconectat
                self._rec_osd_txt = txt
                self.stream.set_rec_osd(txt)
        self._schedule_tick()
        self.fit_min_height()

    def open_mpv_config(self):
        if self.mpv_dialog and self.mpv_dialog.winfo_exists():
            self.mpv_dialog.lift()
            return
        self.mpv_dialog = MpvDialog(self.root, lang=self.lang, opts=self.mpv_opts, mpv_cmd=self.mpv_cmd,
                                    on_saved=self._mpv_saved)

    def _mpv_saved(self, opts):
        """Opțiunile mpv s-au salvat în mpv.conf: le reținem și repornim canalul curent ca să se aplice."""
        self.mpv_opts = opts
        update_settings(mpv_opts=opts)
        name = self.cur
        if self.stream and name:
            self.tune(name)

    def reset_program(self):
        """Aduce programul la starea de după instalare: șterge tot din ~/.config/TeleopsDVB (canale, setări, mpv.conf,
        programări, cache, jurnale) și închide programul. Înregistrările video nu se ating."""
        if not messagebox.askyesno(TITLE, self.t("reset_confirm"), icon="warning", default="no", parent=self.root):
            return
        self._closing = True            # on_close nu mai salvează setările la ieșire
        self.scan_cancelled = True
        try:
            if self.scan_proc:
                self.scan_proc.kill()
            self.stop()
        except Exception:
            pass
        try:
            rec = self.rec_dir.resolve()
        except OSError:
            rec = self.rec_dir
        for p in list(CONF_DIR.iterdir()) if CONF_DIR.is_dir() else []:
            try:
                if rec == p.resolve() or p.resolve() in rec.parents:      # dosarul de înregistrări, dacă e aici, rămâne
                    continue
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
            except OSError:
                pass
        messagebox.showinfo(TITLE, self.t("reset_done"), parent=self.root)
        self.root.destroy()

    def choose_rec_dir(self):
        start = self.rec_dir if self.rec_dir.is_dir() else Path.home()
        d = filedialog.askdirectory(parent=self.root, initialdir=start, title=self.t("rec_dir_title"))
        if d:
            self.rec_dir = Path(d)
            self.rec_tip.text = d

    def epg_events(self):
        return self.stream.ts.events() if self.stream and self.stream.ts else []

    def epg_now_next(self):
        if self.stream and not self.stream.ts:
            return self.t("epg_na")
        ev, now, rows = self.epg_events(), time.time(), []
        if ev and ev[0][0] <= now:
            rows.append(("now", ev.pop(0)))
        if ev:
            rows.append(("next", ev[0]))
        return [(f"{self.t(k)}:", e[2]) for k, e in rows] or self.t("epg_wait")

    def set_epg(self, data):
        if data == self._epg_shown:
            return
        self._epg_shown = data
        for w in (*self.epg_k, *self.epg_v, self.epg_msg):
            w.grid_remove()
        if isinstance(data, str):
            if data:
                self.epg_msg.configure(text=data)
                self.epg_msg.grid(row=0, column=0, columnspan=2, sticky="w")
            return
        for i, (k, title) in enumerate(data):
            self.epg_k[i].configure(text=k)
            self.epg_v[i].configure(text=title)
            self.epg_k[i].grid(row=i, column=0, sticky="nw", padx=(0, 6))
            self.epg_v[i].grid(row=i, column=1, sticky="w")

    def show_epg(self):
        if self.epg_win and self.epg_win.winfo_exists():
            self.epg_win.lift()
            return
        self.epg_win = EpgWindow(self)

    def detect_tuners(self):
        keep = self.adapter_data() or self.settings.get("adapter", "")

        def work():
            items = [probe_tuner(a, f) for a, f in list_frontends()]
            self.events.put(lambda: self.apply_tuners(items, keep))
        threading.Thread(target=work, daemon=True).start()

    def apply_tuners(self, items, keep):
        self.adapter_items = items
        if items:
            self.adapter.configure(values=[i[0] for i in items])
            self.adapter.current(next((n for n, i in enumerate(items) if i[1] == keep), 0))
        else:
            self.adapter.configure(values=[])
            self.adapter.set(self.t("no_tuner"))
        self.update_scan_buttons()
        self.warm_async()
        if not self._autoplay_done:
            self._autoplay_done = True
            names = {c for c, _ in self.tv_channels + self.radio_channels}
            if (self.autoplay_var.get() and items and not self.stream and not self.scan_active
                    and self.last_channel in names and self.last_channel not in self.locked):
                self.tune(self.last_channel)        # dacă tunerul se încălzește încă, tune() așteaptă singur

    def warm_async(self):
        ad = self.adapter_data()
        names = [c for c, _ in self.tv_channels + self.radio_channels]
        ch = self.last_channel if self.last_channel in names else (names[0] if names else "")
        if not ad or not ch or ad in self.warmed or self.warm_busy or self.scan_active:
            return
        self.warm_busy = True

        def work():
            try: warm_up(ad, channel=ch)
            finally: self.events.put(lambda: self._warm_done(ad))
        threading.Thread(target=work, daemon=True).start()

    def _warm_done(self, ad):
        self.warm_busy = False
        self.warmed.add(ad)

    def _adapter_item(self):
        i = self.adapter.current()
        return self.adapter_items[i] if self.adapter_items and i >= 0 else None

    def adapter_systems(self):
        it = self._adapter_item()
        return tuple(it[2]) if it else ()

    def adapter_data(self):
        it = self._adapter_item()
        return it[1] if it else ""

    def update_scan_buttons(self):
        it = self._adapter_item()
        systems = it[2] if it else None
        if systems is None:
            cable = terr = False
        elif systems:
            cable = any(s.startswith("DVBC") for s in systems)
            terr = any(s.startswith(("DVBT", "ISDBT")) for s in systems)
        else:
            cable = terr = True
        if self.scan_active:
            cable = terr = False
        self.set_enabled(self.scan_c_btn, cable)
        self.set_enabled(self.scan_t_btn, terr)
        self.set_enabled(self.ca_btn, bool(self.adapter_items) and not self.scan_active
                         and bool(self.tv_channels or self.radio_channels))

    def reload(self):
        self.tv_channels, self.radio_channels, self.locked = load_channels()
        self._radio_names = {c for c, _ in self.radio_channels}
        self.set_enabled(self.chlist_btn, bool(self.tv_channels or self.radio_channels))
        self.fill_channels()
        self.update_scan_buttons()

    def fill_channels(self):
        scroll_pos = self.chlist.yview()
        q = "" if self._ph_active else self.search_var.get().lower()
        self.chlist.clear()
        self.list_items_meta = []

        def spacer(tag):
            self.chlist.add("")
            self.list_items_meta.append(("header", tag, "div"))

        def title(key):
            txt = self.t(key)
            self.chlist.add(txt, title=True)
            self.list_items_meta.append(("header", txt, "title"))

        def channel(c, label, kind):
            self.chlist.add(label, selectable=True, locked=c in self.locked)
            self.list_items_meta.append(("channel", c, kind))

        lock = lambda c: "   🔑" if c in self.locked else ""
        all_tv = [c for c, _ in self.tv_channels if q in c.lower()]
        all_rad = [c for c, _ in self.radio_channels if q in c.lower()]

        fav_tv = [c for c in all_tv if c in self.favorites]
        fav_rad = [c for c in all_rad if c in self.favorites]
        norm_tv = [c for c in all_tv if c not in self.favorites]
        norm_rad = [c for c in all_rad if c not in self.favorites]

        has_prev = False

        if fav_tv or fav_rad:
            spacer("space_top")
            title("fav_title")
            spacer("space_bot")
            for c in fav_tv + fav_rad:
                icon = "📻" if c in self._radio_names else "📺"
                channel(c, f"★  {icon}  {c.strip()}{lock(c)}", "fav")
            has_prev = True

        if all_tv:
            if has_prev:
                spacer("space_top_tv")
            title("tv_title")
            spacer("space_bot_tv")
            for c in norm_tv:
                channel(c, f"  📺  {c.strip()}{lock(c)}", "tv")
            has_prev = True

        if all_rad:
            if has_prev:
                spacer("space_top_rad")
            title("radio_title")
            spacer("space_bot_rad")
            for c in norm_rad:
                channel(c, f"  📻  {c.strip()}{lock(c)}", "radio")

        self.select_current()
        self.chlist.yview_moveto(scroll_pos[0])

    def _scan_begin(self):
        self.stop()
        self.scan_active, self.scan_cancelled = True, False
        self.update_scan_buttons()
        if not self.tuner_win.is_open():            # scanarea pornită din altă parte: arătăm progresul
            self.tuner_win.show()
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_bar.start(15)
        self.set_enabled(self.cancel_btn, True)
        self.cancel_btn.pack(fill="x", pady=(0, 5))

    def _scan_end(self):
        self.scan_proc = None
        self.scan_active = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.cancel_btn.pack_forget()
        self.update_scan_buttons()

    def _wait_warm(self):
        """Așteaptă (max ~20 s) să se termine „bâzâitul” tunerului din fundal."""
        for _ in range(100):
            if not self.warm_busy: break
            time.sleep(0.2)

    def _detect(self, ad):
        detect_services(ad, lambda: self.scan_cancelled, lambda pr: setattr(self, "scan_proc", pr))

    def start_scan(self, mode):
        if self.scan_active:
            return
        if not shutil.which("dvbv5-scan"):
            messagebox.showerror("Eroare", "Lipsește pachetul dvb-tools.", parent=self.root)
            return
        if len(re.findall(r"\d+", self.adapter_data())) < 2:
            messagebox.showerror(self.t("scan_err"), self.t("no_tuner"), parent=self.root)
            return
        ad, systems = self.adapter_data(), self.adapter_systems()
        self._scan_begin()

        def work():
            try:
                ok, err, cancelled = run_scan(
                    ad, mode, systems, cancelled=lambda: self.scan_cancelled,
                    set_proc=lambda p: setattr(self, "scan_proc", p), wait_warm=self._wait_warm,
                    is_warm=lambda: ad in self.warmed, mark_warm=lambda: self.warmed.add(ad),
                    detect=lambda: self._detect(ad))
            except Exception as e:
                ok, err, cancelled = False, str(e), self.scan_cancelled
            self.events.put(lambda: self.on_scan(ok, err, cancelled))
        threading.Thread(target=work, daemon=True).start()

    def start_ca_detect(self):
        ad = self.adapter_data()
        if self.scan_active or not ad or not (self.tv_channels or self.radio_channels):
            return
        if not zap_all_pids():
            messagebox.showwarning(TITLE, self.t("epg_na"), parent=self.root)
            return
        self._scan_begin()

        def work():
            self._wait_warm()
            err = ""
            try: self._detect(ad)
            except Exception as e: err = str(e)
            cancelled = self.scan_cancelled
            self.events.put(lambda: self.on_ca_done(err, cancelled))
        threading.Thread(target=work, daemon=True).start()

    def on_ca_done(self, err, cancelled):
        self._scan_end()
        if cancelled:
            return
        self.reload()
        if err:
            messagebox.showwarning(self.t("scan_err"), err, parent=self.root)
        else:
            messagebox.showinfo(TITLE, f"{self.t('ca_done')} {len(self.locked)}", parent=self.root)

    def cancel_scan(self):
        if not self.scan_active:
            return
        self.scan_cancelled = True
        self.set_enabled(self.cancel_btn, False)
        p = self.scan_proc
        if p and p.poll() is None:
            p.terminate()
            def _kill():
                if p.poll() is None:
                    p.kill()
            t = threading.Timer(2.0, _kill)
            t.daemon = True
            t.start()

    def on_scan(self, ok, err, cancelled=False):
        self._scan_end()
        if cancelled:
            return
        if ok:
            self.reload()
            total_count = len(self.tv_channels) + len(self.radio_channels)
            messagebox.showinfo(TITLE, f"{self.t('scan_done')} {total_count}", parent=self.root)
        else:
            messagebox.showwarning(self.t("scan_err"), err, parent=self.root)

    def tune(self, name, retry=0, wait=0):
        if self.warm_busy and wait < 60:       # tunerul e „bâzâit” în fundal: așteaptă fără să blocheze fereastra
            self.set_loading(name)
            self.root.after(200, lambda: self.tune(name, retry, wait + 1))
            return
        if self.cur and self.cur != name:
            self.prev_channel = self.cur          # pentru Backspace
        self.stop(fast=True)                  # mpv-ul vechi se închide în fundal
        self.set_loading(name)
        time.sleep(0.05)
        self._retry = retry                    # NU mai tăiem spațiile: numele trebuie să fie exact ca în channels.conf
        try:
            if not self.adapter_data():
                raise RuntimeError(self.t("no_tuner"))
            all_dict = {c: sid for c, sid in self.tv_channels + self.radio_channels}
            self.stream = Streamer(self.mpv_cmd, self.adapter_data(), name, all_dict.get(name, 0),
                                   {"volume": self.volume, "mute": self.muted},
                                   lambda k, v: self.events.put(lambda: self.on_mpv_prop(k, v)),
                                   get_lang_func=lambda: self.lang,
                                   wid=self.video.winfo_id(),
                                   on_msg=lambda m: self.events.put(lambda: self.on_ui_msg(m)),
                                   tone=(self.bass, self.treble), fast=bool(self.fast_var.get()),
                                   timeshift=self.ts_mb(), ts_disk=self.ts_mode == "disk", ts_dir=self.ts_dir())
            for flag, key in ((self.stream.ts_fallback, "ts_fp_fallback"), (self.stream.ts_nodisk, "ts_no_disk")):
                if flag:                        # ne-am abătut de la setarea aleasă: spunem de ce
                    self.root.after(4000, lambda s=self.stream, k=key: s is self.stream and s.toast(self.t(k), 9000))
            self.cur = self.last_channel = name
            self.select_current()
        except Exception as e:
            self.loading = False
            self.update_video_msg()
            messagebox.showerror(self.t("play_err"), str(e), parent=self.root)

    def stop(self, fast=False):
        self._pick_cancel()
        self.set_recording(False)
        if self.stream:
            self.stream.stop(background=fast)
        self.stream = self.cur = None
        self.loading = False
        self.update_video_msg()

    # ---- înregistrări programate (din fereastra EPG)
    def is_scheduled(self, start, end):
        return bool(self.cur and self.schedule.find(self.cur, start, end))

    def schedule_toggle(self, start, end, title):
        """Programează sau anulează înregistrarea unei emisiuni de pe canalul curent:
        "added" | "removed" | "past" | "added_over" (adăugată; în `last_dropped` sunt vizionările „Vreau să vizionez” de pe alt canal,
        suprapuse, anulate: înregistrarea are prioritate)."""
        self.last_conflict, self.last_dropped = None, []
        if not self.cur:
            return "past"
        job = self.schedule.find(self.cur, start, end)
        if job:
            if job is self.rec_job:
                self.set_recording(False)
            self.schedule.remove(job)
            return "removed"
        if end <= time.time():
            return "past"
        if not self.schedule.add(self.cur, title, start, end):
            return "past"
        self.last_dropped = self.watch.clash(self.cur, start - PRE, end + POST)
        for w in self.last_dropped:
            self.watch.remove(w)
        return "added_over" if self.last_dropped else "added"

    # ---- „Vreau să vizionez” (din fereastra EPG): comutare automată pe canalul emisiunii
    def is_watch(self, start, end):
        return bool(self.cur and self.watch.find(self.cur, start, end))

    def watch_toggle(self, start, end, title):
        """Programează sau anulează comutarea automată pe canalul curent la ora emisiunii:
        "added" | "removed" | "past" | "running" (rulează deja, pe canalul curent) | "conflict" (în `last_conflict`: înregistrare pe alt canal)."""
        self.last_conflict = None
        if not self.cur:
            return "past"
        job = self.watch.find(self.cur, start, end)
        if job:
            self.watch.remove(job)
            return "removed"
        now = time.time()
        if end <= now:
            return "past"
        if start - WATCH_LEAD <= now:
            return "running"
        clash = self.schedule.clash(self.cur, start - WATCH_LEAD, end)
        if clash:
            self.last_conflict = clash[0]
            return "conflict"
        return "added" if self.watch.add(self.cur, title, start, end) else "past"

    def _notify(self, text):
        """Mesaj discret peste imagine dacă mpv rulează; altfel fereastră de informare."""
        if self.stream and self.stream.conn:
            self.stream.toast(text, 8000)
        else:
            messagebox.showinfo(TITLE, text, parent=self.root)

    def _watch_tick(self, now):
        known = {c for c, _ in self.tv_channels + self.radio_channels}
        ctx = WatchCtx(self.rec_on, self.cur, self.stream is not None, self.scan_active)
        for job in list(self.watch.jobs):
            action = watch_plan(job, ctx, now, self.schedule.jobs)
            if action == "wait":
                continue
            if action == "switch" and job.channel not in known:
                self.watch.remove(job)
                self._notify(self.t("watch_fail").format(title=job.title, channel=job.channel.strip()))
                continue
            self.watch.remove(job)                         # restul acțiunilor sunt „o singură dată”
            if action == "switch":
                self.tune(job.channel)
                ctx = WatchCtx(self.rec_on, self.cur, self.stream is not None, self.scan_active)
            elif action in ("skip_rec", "skip_busy"):
                self._notify(self.t("watch_" + action).format(title=job.title, channel=job.channel.strip()))

    def _osd(self, text):
        if self.stream:
            self.stream.toast(text, 5000)

    def _schedule_tick(self):
        """Apelat la fiecare tick: oprește joburile terminate și pornește/pregătește pe cele a căror oră a venit."""
        now = time.time()
        if self.schedule.jobs:
            self._record_tick(now)
        if self.watch.jobs:
            self._watch_tick(now)           # după înregistrări: ele au prioritate

    def _record_tick(self, now):
        for job in self.schedule.expired(now):             # intervalul a trecut fără să fi pornit (ex. aplicația era închisă)
            self.schedule.remove(job)
        for job in self.schedule.finished(now):
            if job is self.rec_job:
                self.set_recording(False)
                self._osd(self.t("sched_finished").format(title=job.title))
            self.schedule.remove(job)
        for job in self.schedule.due(now):
            self._run_job(job, now)

    def _run_job(self, job, now):
        action = plan(job, Ctx(self.rec_on, self.rec_job, self.cur, self.stream is not None), now)
        if action == "start":
            self.set_recording(True, label=job.title)
            if self.rec_on:
                job.state, self.rec_job = ACTIVE, job
                self._osd(self.t("sched_started").format(title=job.title))
            else:                                          # n-a mers (ex. director invalid): nu repetăm la nesfârșit
                self.schedule.remove(job)
        elif action == "tune":                             # te uiți la altceva: trecem pe canalul de înregistrat
            job.state, job.t_tune = TUNING, now
            self.tune(job.channel)
        elif action == "merge":                            # același canal, deja înregistrat printr-un alt job: îl prelungim
            self.rec_job.end = max(self.rec_job.end, job.end)
            self.schedule.remove(job)
        elif action == "adopt":                            # înregistrai deja manual acest canal: se oprește la sfârșitul emisiunii
            job.state, self.rec_job = ACTIVE, job
        elif action in ("cancel_busy", "cancel_fail"):
            self.schedule.remove(job)
            messagebox.showwarning(TITLE, self.t("sched_busy" if action == "cancel_busy" else "sched_fail")
                                   .format(title=job.title, channel=job.channel.strip()), parent=self.root)

    def _rec_txt(self):
        h, r = divmod(int(time.time() - self.rec_t0), 3600)
        return f"● REC {h}:{r // 60:02d}:{r % 60:02d}"

    def set_recording(self, on, label=None):
        """Pornește/oprește înregistrarea canalului curent. `label` (ex. titlul emisiunii) intră în numele fișierului."""
        if on == self.rec_on or (on and not self.stream):
            return
        try:
            if on:
                self.rec_dir.mkdir(parents=True, exist_ok=True)
                name = (self.cur or "canal").strip() + (f" - {label}" if label else "")
                name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)[:90].strip()
                self.stream.start_rec(self.rec_dir / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.ts")
            elif self.stream:
                self.stream.stop_rec()
        except OSError as e:
            messagebox.showerror(self.t("rec_dir"), str(e), parent=self.root)
            return
        self.rec_on = on
        if not on and self.rec_job:        # oprită (de utilizator sau la schimbarea canalului): programarea se încheie
            self.schedule.remove(self.rec_job)
            self.rec_job = None
        if on:
            self.rec_t0 = time.time()
            txt = self._rec_txt()          # „● REC 0:00:00”
            self.rec_lbl.configure(text=txt)
            self.stream.set_rec_osd(txt)
            self.rec_lbl.pack(after=self.top, fill="x", pady=(0, 5))
        else:
            self.rec_lbl.pack_forget()
            self._rec_osd_txt = ""
            if self.stream:
                self.stream.set_rec_osd(None)
        self.rec_btn.configure(text=self.t("rec_on" if on else "rec_off"))
        self.root.after_idle(self.fit_min_height)

    def on_close(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        filtered = not self._ph_active and bool(self.search_var.get())
        save_settings({
            "lang": self.lang,
            "muted": self.muted,
            "volume": self.volume,
            "last_channel": self.cur or self.last_channel,
            "prev_channel": self.prev_channel,
            "bass": self.bass,
            "treble": self.treble,
            "search_visible": self.search_wanted,
            "geometry": self._pre_fs_geom if self.fullscreen and self._pre_fs_geom else self.root.geometry(),
            "video_side": self.video_side,
            "borderless": bool(self.borderless_var.get()),
            "autoplay_last": bool(self.autoplay_var.get()),
            "tmdb_key": self.settings.get("tmdb_key", ""),
            "country": self.settings.get("country", ""),
            "country_auto": self.country_auto,
            "fast_switch": bool(self.fast_var.get()),
            "show_media": bool(self.show_media_var.get()),
            "adapter": self.adapter_data() or self.settings.get("adapter", ""),
            "tuner_visible": self.settings_on,
            "scroll_position": self.settings.get("scroll_position", 0.0) if filtered else self.chlist.yview()[0],
            "rec_dir": str(self.rec_dir),
            "favorites": list(self.favorites),
            "mpv_opts": self.mpv_opts,
            "theme": self.theme_mode,
            "timeshift": bool(self.ts_var.get()),
            "timeshift_mb": self._ts_size(),
            "timeshift_mode": self.ts_mode,
        })
        self.stop()
        clean_timeshift_dir(self.ts_dir())
        self.scan_cancelled = True
        if self.scan_proc:
            self.scan_proc.kill()
        self.root.destroy()


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: app  ·  Punctul de pornire: compune totul
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE app/app
#   Punctul de pornire: verifică dependențele, pregătește configurația și rulează fereastra principală.
# ──────────────────────────────────────────────────────────────────────────────

def _fatal(msg):
    print("Eroare: " + msg)
    tk.Tk().withdraw()
    messagebox.showerror(TITLE, msg)
    sys.exit(1)


def main():
    logging.basicConfig(level=logging.DEBUG if os.environ.get("TELEOPS_DEBUG") else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    mpv_cmd = find_mpv()
    if not mpv_cmd:
        _fatal(MPV_MISSING_MSG)
    if missing := missing_dependencies():
        _fatal(deps_message(missing))
    if not acquire_single_instance():
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo(TITLE, tr(load_settings().get("lang"), "already"))
        sys.exit(0)

    CONF_DIR.mkdir(parents=True, exist_ok=True)
    write_osc_script()              # se rescrie la fiecare pornire
    ensure_mpv_conf()
    clean_timeshift_dir()           # resturi ale bufferului Timeshift (dacă mpv a fost oprit brusc)

    inhibitor = SleepInhibitor()    # fără suspend/screensaver cât rulează programul
    inhibitor.start()
    try:
        root = tk.Tk(baseName=WM_NAME, className=WM_CLASS)
        Main(root, mpv_cmd)
        root.mainloop()
    finally:
        inhibitor.stop()


if __name__ == "__main__":
    main()


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
             · strings_rec: Texte pentru înregistrările programate din EPG. Format: cheie: (ro, en, it).
             · translate: Traduceri: `tr(lang, cheie)`.
    system   Integrare cu sistemul: mediu, X11, D-Bus, anti-sleep, editor, instanță unică
             · dbus_min: Client D-Bus minimal, fără dependențe: doar apeluri de metodă pe session bus.
             · x11: Ajutor peste libX11 prin ctypes (fără dependențe de Tk).
             · env: Mediul de execuție: variabile curate pentru procese copil, căutarea mpv și a uneltelor DVB.
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
    player   mpv + dvbv5-zap: redare, script OSC, opțiuni și validare mpv
             · osc_script: Mini-OSC Lua încorporat în mpv (subtitrare / audio / mute). Se scrie în CONF_DIR la fiecare pornire.
             · mpv_options: Opțiunile mpv oferite în dialogul „Configurează MPV” și transformarea lor în linii de mpv.conf.
             · mpv_check: Validarea unei configurații mpv înainte s-o salvăm: pornește scurt mpv pe o sursă de test.
             · streamer: Redarea unui canal: dvbv5-zap -> (filtru TS) -> mpv încorporat în fereastra Tk, cu control prin IPC.
    ui       Interfața Tkinter (singurul strat care folosește tkinter)
             · constants: Constante ale interfeței.
             · geometry: Geometria redimensionării unei ferestre fără bordură (funcții pure, fără Tk, ușor de testat).
             · widgets: Widgeturi Tk reutilizabile: lista de canale și tooltip.
             · window_chrome: Comportamentul ferestrei: mutare prin tragere, fără bordură/titlebar și redimensionare fără margini.
             · epg_window: Fereastra cu programul TV (EPG) al canalului curent.
             · mpv_dialog: Dialogul „Configurează MPV”: opțiuni alese din liste (potrivite pentru TV), plus acces la mpv.conf.
             · main_window: Fereastra principală: panou cu comenzi + zonă video (mpv încorporat), listă de canale, scanare, înregistrare.
    app      Punctul de pornire: compune totul
             · app: Punctul de pornire: verifică dependențele, pregătește configurația și rulează fereastra principală.

CUM ADAUGI...
  · o opțiune mpv în dialog: o declari în `OPTIONS` (player/mpv_options) și îi tratezi valoarea în `render_block`;
    textele (`mo_<cheie>`, `mh_<cheie>`, `mc_*`) merg în secțiunea i18n/strings_mpv.
  · un text: i18n/strings (cheie -> (ro, en, it)).
  · o decizie de programare/înregistrare: core/schedule (funcția `plan`), apoi execuția în `Main._run_job`.
"""

import configparser
import ctypes
import ctypes.util
import fcntl
import functools
import json
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
import tkinter.font as tkfont
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
WM_NAME, WM_CLASS = "teleops", "Teleops"   # WM_CLASS al ferestrei: GNOME/KDE îl potrivesc cu fișierul .desktop (iconiță în bara de activități)
CONF_DIR = Path.home() / ".config" / "TeleopsDVB"
CHANNELS = CONF_DIR / "channels.conf"
MPV_CONF = CONF_DIR / "mpv.conf"
MPV_CONF_BAK = CONF_DIR / "mpv.conf.bak"           # copia de siguranță de dinainte de prima modificare automată
SETTINGS = CONF_DIR / "settings.json"
SCHEDULE = CONF_DIR / "schedule.json"              # înregistrările programate din EPG
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
target-prim=bt.709
target-trc=bt.1886
scale=spline36
cscale=mitchell
dscale=mitchell
dither-depth=auto
temporal-dither=yes
keep-open=yes
autofit-smaller=1920x1080
autofit-larger=90%x90%
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
    "lang_label": ("Limbă / Language:", "Language:", "Lingua:"),
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
    "hk_epg": ("Informații EPG", "EPG info", "Info EPG"),
    "hk_epg_k": ("CTRL + I", "CTRL + I", "CTRL + I"),
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
    "hk_osc_k": ("Click dreapta pe video", "Right click on video", "Clic destro sul video"),
    "hk_quit": ("Închide programul", "Quit program", "Chiudi il programma"),
    "hk_quit_k": ("CTRL + SHIFT + X", "CTRL + SHIFT + X", "CTRL + SHIFT + X"),
    "loading": ("Se încarcă...", "Loading...", "Caricamento..."),
    "osc_sub": ("Subtitrare", "Subtitles", "Sottotitoli"),
    "osc_audio": ("Coloană sonoră", "Audio track", "Traccia audio"),
    "osc_off": ("Dezactivat", "Off", "Disattivato"),
    "quit_app": ("⏻ Închide programul", "⏻ Quit program", "⏻ Chiudi il programma"),
    "borderless": ("Fără margini și bară de titlu", "No window borders / titlebar", "Senza bordi e barra del titolo"),
    "x11_na": ("Funcția cere X11/XWayland (libX11 indisponibil).", "This needs X11/XWayland (libX11 unavailable).", "Richiede X11/XWayland (libX11 non disponibile)."),
    "side_btn": ("⇄ Player video: stânga / dreapta", "⇄ Video player: left / right", "⇄ Lettore video: sinistra / destra"),
    # Localizare OSD MPV
    "osd_loading": ("Se încarcă EPG...", "Loading EPG...", "Caricamento EPG..."),
    "osd_na": ("Indisponibil", "Unavailable", "Non disponibile"),
    "scrambled": ("Canal codat (criptat): nu poate fi redat fără card/CAM.", "Scrambled (encrypted) channel: it can't be played without a card/CAM.", "Canale criptato: non riproducibile senza card/CAM."),
    "chlist_btn": ("📺 Lista Canale TV", "📺 TV Channel List", "📺 Elenco canali TV"),
    "cfg_tip": ("Setări / Listă canale", "Settings / Channel list", "Impostazioni / Elenco canali"),
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
}


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE i18n/translate
#   Traduceri: `tr(lang, cheie)`.
# ──────────────────────────────────────────────────────────────────────────────

T.update(MPV_T)
T.update(REC_T)


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
                if pid in (0, 0x11, 0x12, self.pmt_pid):
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

    def parse(self, pid, s):
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
            while j + 2 <= len(d):
                tag, ln = d[j], d[j + 1]
                b = d[j + 2:j + 2 + ln]
                if tag == 0x4D and lang is None:
                    lang, n = b[:3], b[3]
                    name, text = dvb_text(b[4:4 + n]), dvb_text(b[5 + n:5 + n + b[4 + n]])
                elif tag == 0x4E and (lang is None or b[1:4] == lang):
                    n = b[4]
                    ext += b[6 + n:6 + n + b[5 + n]]
                j += 2 + ln
            if mjd != 0xFFFF:
                start = (mjd - 40587) * 86400 + bcd(s[i + 4]) * 3600 + bcd(s[i + 5]) * 60 + bcd(s[i + 6])
                dur = bcd(s[i + 7]) * 3600 + bcd(s[i + 8]) * 60 + bcd(s[i + 9])
                self.epg[eid] = (start, start + dur, name, "\n".join(x for x in (text, dvb_text(ext)) if x))
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


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: player  ·  mpv + dvbv5-zap: redare, script OSC, opțiuni și validare mpv
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE player/osc_script
#   Mini-OSC Lua încorporat în mpv (subtitrare / audio / mute). Se scrie în CONF_DIR la fiecare pornire.
# ──────────────────────────────────────────────────────────────────────────────

OSC_LUA = r'''-- Teleops DVB: mini-OSC cu doar subtitrare, coloană sonoră și difuzor (înlocuiește OSC-ul standard mpv).
-- Fișier generat de teleops.py (se rescrie la fiecare pornire).
local L = {sub = "Subtitrare", audio = "Coloană sonoră", off = "Dezactivat"}
local ACC = "FFC040"
local shown, menu, items, timer = false, nil, {}, nil
local last_over, last_hot = false, false
local ov = mp.create_osd_overlay("ass-events")

local function I(v) return math.floor(v + 0.5) end
local function esc(s) return (tostring(s):gsub("[{}\\\n]", " ")) end

local function geom()
    local w, h = mp.get_osd_size()
    if not w or not h or w < 50 or h < 50 then return nil end
    return w, h, math.max(0.8, h / 720)
end

local function bar_rects(w, h, k)
    local bw, bh, gap, m = 46 * k, 34 * k, 8 * k, 18 * k
    local x0, y0 = w - m - 3 * bw - 2 * gap, h - m - bh
    local r = {}
    for i, name in ipairs({"sub", "audio", "spk"}) do
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

local function hit(x, y)
    if not shown then return nil end
    local w, h, k = geom()
    if not w then return nil end
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
    if not shown or not w then
        ov:remove()
        return
    end
    ov.res_x, ov.res_y = w, h
    local bars = bar_rects(w, h, k)
    local mx, my = mp.get_mouse_pos()
    local ln, sub_on = {}, false
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        if t.type == "sub" and t.selected then sub_on = true end
    end
    local muted = mp.get_property_bool("mute", false)
    for _, name in ipairs({"sub", "audio", "spk"}) do
        local r = bars[name]
        local hot = inside(r, mx, my) or menu == name
        ln[#ln + 1] = rect(r[1], r[2], r[3], r[4], hot and "808080" or "000000", hot and "50" or "70")
        local cx, cy = (r[1] + r[3]) / 2, (r[2] + r[4]) / 2
        if name == "sub" then
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
    if not pos or not shown then return end
    if not pos.hover then
        set_hot(false)
        return
    end
    arm()
    local over = hit(pos.x, pos.y) ~= nil
    set_hot(over)
    if over or last_over then render() end
    last_over = over
end)

local function on_click()
    if not shown then return end
    local x, y = mp.get_mouse_pos()
    local kind, v = hit(x, y)
    if kind == "row" then
        apply(menu, v)
        menu = nil
    elseif kind == "btn" then
        if v == "spk" then
            mp.commandv("cycle", "mute")
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

-- „q”, „Q” și Ctrl+C nu mai închid mpv: fereastra video rămâne (programul decide când se oprește redarea)
for _, key in ipairs({"q", "Q", "Ctrl+c"}) do
    mp.add_forced_key_binding(key, "teleops-noquit-" .. key, function() end)
end

-- Pauza nu are sens la TV live: o blocăm (SPACE, p, tastele media, frame-step) și o anulăm dacă apare oricum
for _, key in ipairs({"SPACE", "p", "PAUSE", "PLAY", "PLAYPAUSE", ","}) do
    mp.add_forced_key_binding(key, "teleops-nopause-" .. key, function() end)
end
mp.observe_property("pause", "bool", function(_, v)
    if v then mp.set_property_bool("pause", false) end
end)
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


class Streamer:
    OBSERVED = ("volume-max", "volume", "mute", "vo-configured", "audio-params")
    # mesaj -> tastele mpv care îl trimit (cât timp mpv are focusul, Tk nu primește tastele; „i” simplu rămâne nativ mpv)
    KEYS = {"show-info-osd": ("Ctrl+i",), "toggle-ui": (".", "MBTN_LEFT_DBL"), "toggle-fs": ("f", "F", "F11"),
            "exit-fs": ("ESC",), "toggle-rec": ("Ctrl+r", "Ctrl+R"), "quit-app": ("Ctrl+X", "Ctrl+Shift+x", "Ctrl+Shift+X")}

    def __init__(self, mpv_cmd, adapter, channel, sid, props, on_prop, get_lang_func=None, wid=None, on_msg=None):
        self.props, self.on_prop, self.conn = dict(props), on_prop, None
        self.on_msg = on_msg or (lambda *_: None)
        self.osc_hot = False        # cursorul e pe un buton/meniu al mini-OSC-ului din mpv
        self.rec, self.lock = None, threading.Lock()
        self.t0, self.got_data = time.time(), False
        self.channel_name = channel
        self.get_lang = get_lang_func or (lambda: "Română")
        self.ts = TSFilter(sid) if sid and zap_all_pids() else None
        a, f = re.findall(r"\d+", adapter)
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        self.sock_name = f"teleops-{os.getpid()}.sock"
        self.sock = str(IPC_DIR / self.sock_name)

        zap_cmd = ["dvbv5-zap", "-c", str(CHANNELS), "-a", a, "-f", f, "-r", "-P" if self.ts else "-p", "-o", "-", channel]
        
        self.zap = None
        for attempt in range(2):
            p = subprocess.Popen(zap_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=get_clean_env())
            time.sleep(0.3)
            if p.poll() is None:
                self.zap = p
                break
            try:
                p.terminate()
            except Exception:
                pass
            if attempt == 0:
                time.sleep(0.5)
        
        if not self.zap:
            self.zap = subprocess.Popen(zap_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=get_clean_env())

        mpv = [*mpv_cmd, "--no-terminal", f"--include={MPV_CONF}", f"--input-ipc-server={self.sock}",
               "--sid=auto", "--sub-visibility=yes", f"--volume={props['volume']}",
               f"--mute={'yes' if props['mute'] else 'no'}", f"--title=TV - {channel.strip()}"]
        env = get_clean_env()
        if wid:   # încorporat în fereastra Tk: --wid există doar pe X11 (XWayland), deci interzicem backend-ul Wayland
            mpv += [f"--wid={wid}", f"--gpu-context={GPU_CONTEXT}", "--window-dragging=no", "--osc=no", "--osd-bar=no", f"--script={OSC_PATH}"]
            env.pop("WAYLAND_DISPLAY", None)
        self.mpv = subprocess.Popen(mpv + ["-"], stdin=subprocess.PIPE, env=env)
        for target in (self.pump, self.ipc):
            threading.Thread(target=target, daemon=True).start()

    def alive(self):
        return self.zap.poll() is None and self.mpv.poll() is None

    def pump(self):
        src = self.zap.stdout.fileno()
        try:
            while data := os.read(src, 1 << 16):
                self.got_data = True
                if self.ts: data = self.ts.feed(data)
                if data:
                    self.mpv.stdin.write(data)
                    self.mpv.stdin.flush()
                    with self.lock:
                        if self.rec: self.rec.write(data)
        except (OSError, ValueError):
            pass

    def t(self, key):
        return tr(self.get_lang(), key)

    def ipc(self):
        for _ in range(150):
            if not self.alive(): return
            c = socket.socket(socket.AF_UNIX)
            try:
                c.connect(str(self.sock))
                break
            except OSError:
                c.close()
                time.sleep(0.1)
        else:
            return
        self.conn = c
        for k, v in self.props.items():
            self.cmd("set_property", k, v)
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
                        if args[0] == "show-info-osd": self.show_tv_osd()
                        elif args[0] == "teleops-osc-hot": self.osc_hot = args[1:2] == ["1"]
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
        now = time.time()
        now_lbl = self.t("now").upper()
        next_lbl = self.t("next").upper()
        rem_lbl = self.t("osd_rem")
        now_title = self.t("osd_loading")
        next_title = self.t("osd_loading") if self.ts else self.t("osd_na")
        prog_bar = "[░░░░░░░░░░░░░░░░░░░░] 0%"

        cur, nxt = self._now_next(now)
        if cur:
            start, end, title, _ = cur
            now_title = title
            total = end - start
            if total > 0:
                rem = max(0, int((end - now) / 60))
                progress = max(0.0, min(1.0, (now - start) / total))
                filled = int(progress * 20)
                prog_bar = "[" + "█" * filled + "░" * (20 - filled) + f"] {rem_lbl}: {rem} min"
        if nxt:
            next_title = nxt[2]

        osd_text = (
            f"                  {self.channel_name.strip()}                  \n"
            f"────────────────────────────────────────\n"
            f"▶ {now_lbl}: {now_title}\n"
            f"{prog_bar}\n"
            f"⏭ {next_lbl}: {next_title}"
        )
        self.cmd("show-text", osd_text, 15000)

    def cmd(self, *args):
        if self.conn:
            try: self.conn.sendall((json.dumps({"command": args}) + "\n").encode())
            except OSError: pass

    def set_prop(self, name, value):
        self.props[name] = value
        self.cmd("set_property", name, value)

    def send_labels(self):
        self.cmd("script-message", "teleops-labels", self.t("osc_sub"), self.t("osc_audio"), self.t("osc_off"))

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

    def stop(self):
        self.on_prop = self.on_msg = lambda *_: None
        self.stop_rec()
        for p in (self.zap, self.mpv):
            try:
                p.terminate()
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                p.kill()
        subprocess.run(["pkill", "-f", self.sock_name], stderr=subprocess.DEVNULL, env=get_clean_env())
        Path(self.sock).unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# STRAT: ui  ·  Interfața Tkinter (singurul strat care folosește tkinter)
# ══════════════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────────────────────────────
# SECȚIUNE ui/constants
#   Constante ale interfeței.
# ──────────────────────────────────────────────────────────────────────────────

VOL_MAX = 130           # volume-max implicit în mpv
TXT_DARK = "#000000"    # culoare text implicită
LIST_MIN_H = 150        # înălțimea minimă (px) a listei de canale la strângerea ferestrei
CFG_W, CFG_GAP = 36, 5     # lățimea butonului ⚙ și spațiul dintre el și butonul EPG
PANEL_W = 320           # lățimea fixă a panoului cu comenzi
VIDEO_MIN_W = 480       # lățimea minimă a zonei video

HOTKEYS = (("hk_play", "hk_play_k"), ("hk_fav", "hk_fav_k"), ("hk_search", "hk_search_k"),      # lista de canale
           ("hk_epg", "hk_epg_k"), ("hk_rec", "hk_rec_k"),                                      # canalul curent
           ("hk_osc", "hk_osc_k"), ("hk_fs", "hk_fs_k"), ("hk_ui", "hk_ui_k"),                  # video
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
        sel_bg, sel_fg = probe.cget("selectbackground"), probe.cget("selectforeground")
        probe.destroy()
        kw.setdefault("width", 1)
        kw.setdefault("height", 1)
        super().__init__(master, wrap="none", cursor="arrow", insertwidth=0, padx=2, pady=0,
                         borderwidth=0, takefocus=True, **kw)
        self.selectable = []
        self.tag_configure("title", justify="center", underline=True)
        self.tag_configure("locked", foreground="#dc2626")      # canale codate: text maro-roșiatic
        self.tag_configure("cur", background=sel_bg, foreground=sel_fg)
        self.tag_raise("cur")
        # fără bindingurile implicite ale lui Text (editare, selecție cu mouse-ul)
        self.bindtags((str(self), str(self.winfo_toplevel()), "all"))
        self.bind("<Button-1>", self._click)
        self.bind("<Up>", lambda e: self._step(-1))
        self.bind("<Down>", lambda e: self._step(1))
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", self._wheel)
        self.bind("<Button-5>", self._wheel)

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
        tk.Label(self.tw, text=self.text, background="#ffffe0", foreground="#000000", relief="solid", borderwidth=1,
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
    is_scheduled(start, end), schedule_toggle(start, end, titlu)."""

    def __init__(self, host):
        super().__init__(host.root)
        self.title(host.t("epg_btn"))
        self.geometry("640x580")
        self.minsize(600, 540)

        st = ttk.Style()
        st.configure("Epg.Treeview", background=host.bg_grey, fieldbackground=host.bg_grey,
                     foreground=TXT_DARK, font=host.f_norm)
        st.configure("Epg.Treeview.Heading", font=host.f_bold)
        st.map("Epg.Treeview", background=[("selected", "#4a6984")], foreground=[("selected", "#ffffff")])
        self.configure(bg=host.bg_grey)

        mf = ttk.Frame(self, padding=10)
        mf.pack(fill="both", expand=True)

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
        btn_row.pack(fill="x", pady=(0, 10))
        rec_btn = ttk.Button(btn_row, text=host.t("epg_rec_btn"))
        rec_btn.pack(side="left")
        Tip(rec_btn, host.t("epg_rec_tip"), wrap=320)
        status = ttk.Label(btn_row, text="", wraplength=360, justify="left")
        status.pack(side="left", padx=12)

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
            """Butonul programează sau anulează, după emisiunea selectată."""
            sel = tree.selection()
            if not sel or sel[0] not in ev_map:
                rec_btn.configure(text=host.t("epg_rec_btn"))
                rec_btn.state(["disabled"])
                return
            s, e = ev_map[sel[0]][:2]
            rec_btn.configure(text=host.t("epg_rec_cancel" if host.is_scheduled(s, e) else "epg_rec_btn"))
            rec_btn.state(["!disabled"])

        def toggle_rec():
            sel = tree.selection()
            if not sel or sel[0] not in ev_map:
                return
            s, e, name, _ = ev_map[sel[0]]
            result = host.schedule_toggle(s, e, name)
            status.configure(text={
                "added": host.t("epg_rec_added").format(start=hm(s), end=hm(e), margin=PRE // 60),
                "removed": host.t("epg_rec_removed"),
                "past": host.t("epg_rec_past")}[result])
            render()

        rec_btn.configure(command=toggle_rec)
        tree.bind("<<TreeviewSelect>>", on_select)

        days_dict = {
            "Română": ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"],
            "English": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "Italiano": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        }

        def render():
            if not self.winfo_exists():
                return
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
                mark = "⏺ " if host.is_scheduled(s, e) else ""
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

        refresh()


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
# SECȚIUNE ui/main_window
#   Fereastra principală: panou cu comenzi + zonă video (mpv încorporat), listă de canale, scanare, înregistrare.
# ──────────────────────────────────────────────────────────────────────────────

class Main:
    def __init__(self, root, mpv_cmd):
        self.root, self.settings, self.mpv_cmd = root, load_settings(), mpv_cmd
        self.mpv_opts, self.mpv_dialog = clean_mpv_opts(self.settings.get("mpv_opts", {})), None
        self.schedule, self.rec_job = RecordingSchedule(SCHEDULE), None      # înregistrări programate din EPG
        self.lang = self.settings.get("lang") if self.settings.get("lang") in LANGS else LANGS[0]
        self.last_channel = self.settings.get("last_channel", "")
        self.favorites = set(self.settings.get("favorites", []))
        self._radio_names = set()
        self.events = queue.Queue()
        self.stream, self.tv_channels, self.radio_channels, self.cur, self.scan_proc = None, [], [], None, None
        self.scan_active, self.scan_cancelled = False, False
        self.rec_on, self._ph_active, self.epg_win = False, False, None
        self.rec_t0, self.muted = 0, bool(self.settings.get("muted", False))
        self.volume = max(0, min(int(self.settings.get("volume", 100)), VOL_MAX))
        self.adapter_items, self.tr = [], []
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

        for fmt, letters, fn in (("<Control-Key-{}>", "iI", self.on_key_i),         # EPG („i” simplu rămâne liber pentru mpv)
                                 ("<Control-Key-{}>", "rR", self.toggle_rec),       # pornește/oprește înregistrarea
                                 ("<Control-Shift-Key-{}>", "xX", lambda e: self.on_close()),
                                 ("<Key-{}>", "fF", self.on_key_f)):                # ecran complet
            for ch in letters:
                root.bind(fmt.format(ch), fn)
        root.bind("<period>", self.on_key_dot)
        root.bind("<F11>", self.toggle_fullscreen)
        root.bind("<Escape>", lambda e: self.fullscreen and self.toggle_fullscreen())

        base = tkfont.nametofont("TkDefaultFont")

        def font(size, weight):
            f = base.copy()
            f.configure(size=size, weight=weight)
            return f
        self.f_norm, self.f_bold, f_brand = font(-13, "normal"), font(-13, "bold"), font(-18, "bold")
        self.f_load, self.f_hk, self.f_hkb = font(-22, "bold"), font(-11, "normal"), font(-11, "bold")
        
        st = ttk.Style()
        st.theme_use("default")
        
        st.configure("TLabel", font=self.f_bold)
        st.configure("Brand.TLabel", font=f_brand, foreground="#555555")   # aceeași culoare ca mesajul „Se încarcă...”
        st.configure("Rec.TLabel", font=self.f_bold, foreground="#dc2626")
        st.configure("Epg.TLabel", font=self.f_norm)
        st.configure("EpgB.TLabel", font=self.f_bold)
        st.configure("Hk.TLabel", font=self.f_hk)
        st.configure("HkB.TLabel", font=self.f_hkb)
        st.configure("TButton", font=self.f_norm)
        st.configure("TCheckbutton", font=self.f_norm)
        st.configure("TCombobox", font=self.f_norm)

        bg_grey = self.bg_grey = st.lookup("TFrame", "background") or root.cget("bg")

        # Panou cu comenzi (lățime fixă) + zonă video (mpv încorporat prin --wid). Ordinea de împachetare
        # o stabilește layout(): panoul primește partea opusă playerului, video-ul ocupă restul.
        self.panel = tk.Frame(root, width=PANEL_W)
        self.panel.pack_propagate(False)
        self.video = tk.Frame(root, bg=self.bg_grey, width=640, height=360)
        self.video.pack(side="left", fill="both", expand=True)
        self.chrome = WindowChrome(root, self.video, self.x11, get_stream=lambda: self.stream,
                                   is_fullscreen=lambda: self.fullscreen)
        self.video.bind("<Button-1>", lambda e: self.video.focus_set())
        self.video.bind("<Double-Button-1>", self.toggle_ui)   # când nu rulează mpv (altfel îl prinde mpv)
        # mesaj în mijlocul zonei video cât mpv nu are încă imagine (e acoperit automat de fereastra mpv)
        self.video_lbl = tk.Label(self.video, bg=self.bg_grey, fg="#555555", font=self.f_load, justify="center")
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
        self.chrome.bind_drag(self.brand)   # tragere = mută fereastra
        self.brand.grid(row=0, column=0, sticky="ew")
        self.rec_lbl = ttk.Label(main, style="Rec.TLabel", anchor="center")
        self.top = top

        self.tuner_container = tc = ttk.Frame(main)
        tc.pack(fill="x")
        self._lbl(tc, "lang_label")
        self.lang_box = ttk.Combobox(tc, values=LANGS, state="readonly", font=self.f_norm)
        self.lang_box.set(self.lang)
        self.lang_box.bind("<<ComboboxSelected>>", self.on_lang)
        self.lang_box.pack(fill="x", pady=5)

        lrow = ttk.Frame(tc)
        lrow.pack(fill="x", pady=5)
        refresh = ttk.Button(lrow, text="↻", width=2, command=self.detect_tuners)
        refresh.pack(side="left", padx=(0, 6))
        self.refresh_tip = Tip(refresh, "")
        tl = ttk.Label(lrow)
        tl.pack(side="left")
        self.tr.append((tl, "tuner_label"))
        self.adapter = ttk.Combobox(tc, state="readonly", font=self.f_norm)
        self.adapter.bind("<<ComboboxSelected>>", lambda e: self.update_scan_buttons())
        self.adapter.pack(fill="x", pady=5)

        self.scan_c_btn = self._btn(tc, "scan_c", lambda: self.start_scan("dvbc"))
        self.scan_t_btn = self._btn(tc, "scan_t", lambda: self.start_scan("dvbt"))
        self.chlist_btn = self._btn(tc, "chlist_btn", lambda: self.set_settings_view(False))
        self.ca_btn = self._btn(tc, "ca_btn", self.start_ca_detect)
        self._btn(tc, "cfg_mpv", self.open_mpv_config)
        self._btn(tc, "side_btn", self.swap_side)
        self.rec_tip = Tip(self._btn(tc, "rec_dir", self.choose_rec_dir), str(self.rec_dir))
        self.borderless_var = tk.BooleanVar(value=bool(self.settings.get("borderless", False)))
        cb = ttk.Checkbutton(tc, variable=self.borderless_var, command=self.apply_borderless)
        cb.pack(fill="x", pady=(5, 0))
        self.tr.append((cb, "borderless"))
        self.progress_bar = ttk.Progressbar(tc, mode="indeterminate")
        self.cancel_btn = self._btn(tc, "scan_cancel", self.cancel_scan)
        self.cancel_btn.pack_forget()

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
        self.search.pack(fill="x", pady=5)

        self.bottom_sep = ttk.Separator(bottom, orient="horizontal")
        self.bottom_sep.pack(fill="x", pady=(0, 5))

        # Comenzi rapide: apar deasupra barei de volum doar când setările sunt afișate
        hk = self.hk_frame = ttk.Frame(bottom)
        hk.pack(fill="x", pady=(0, 2))
        hk.columnconfigure(0, weight=1)
        hk_title = ttk.Label(hk, style="HkB.TLabel")
        hk_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self.tr.append((hk_title, "hk_title"))
        for r, (d, k) in enumerate(HOTKEYS, 1):
            dl = ttk.Label(hk, style="Hk.TLabel", wraplength=160, justify="left")
            kl = ttk.Label(hk, style="HkB.TLabel", wraplength=125, justify="right")
            dl.grid(row=r, column=0, sticky="nw", pady=1)
            kl.grid(row=r, column=1, sticky="ne", padx=(6, 0), pady=1)
            self.tr += [(dl, d), (kl, k)]

        vol = self.vol_frame = ttk.Frame(bottom)
        vol.pack(fill="x", pady=5)
        self.mute_lbl = ttk.Label(vol, cursor="hand2", font=self.f_norm)
        self.mute_lbl.pack(side="left")
        self.mute_lbl.bind("<Button-1>", self.toggle_mute)
        self.vol_lbl = ttk.Label(vol, width=5, anchor="e", font=self.f_norm)
        self.vol_lbl.pack(side="right")
        self.vol_slider = ttk.Scale(vol, from_=0, to=VOL_MAX, orient="horizontal", command=self.on_volume)
        self.vol_slider.pack(side="left", fill="x", expand=True, padx=6)

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
        root.after(40, self.chrome.start_mpv_poll)
        if self.borderless_var.get():
            root.after(400, self.apply_borderless)
        self.layout()
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
        for w in (self.tuner_container, self.hk_frame, self.epg_lbl, self.main_sep, self.list_frame, self.search):
            w.pack_forget()
        if show:
            self.tuner_container.pack(fill="x")
            self.hk_frame.pack(fill="x", pady=(0, 2), before=self.vol_frame)
        else:
            self.epg_lbl.pack(fill="x", pady=5)
            self.main_sep.pack(fill="x", pady=(5, 0))
            self.list_frame.pack(fill="both", expand=True, pady=5)
            if self.search_wanted:
                self.search.pack(fill="x", pady=5, before=self.bottom_sep)
        self._min_h = 0
        self.root.after_idle(self.fit_min_height)

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
        """True cât se scrie într-un câmp de text (scurtăturile `.` și `f` trebuie ignorate)."""
        try:
            return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox))
        except KeyError:
            return False

    def on_key_dot(self, _=None):
        if not self._typing():
            self.toggle_ui()

    def on_key_f(self, _=None):
        if not self._typing():
            self.toggle_fullscreen()

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
        if msg == "toggle-ui":
            self.toggle_ui()
        elif msg == "toggle-fs" or (msg == "exit-fs" and self.fullscreen):
            self.toggle_fullscreen()
        elif msg == "quit-app":
            self.on_close()
        elif msg == "toggle-rec":
            self.toggle_rec()

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
        if not self.settings_on:          # cu setările afișate lista e ascunsă
            need += LIST_MIN_H - self.list_frame.winfo_reqheight()
        if need != self._min_h:
            self._min_h = need
            self.root.minsize(PANEL_W + VIDEO_MIN_W, need)
        if self.root.winfo_ismapped() and not self.fullscreen and self.root.winfo_height() < need:
            self.root.geometry(f"{self.root.winfo_width()}x{need}")

    def poll_events(self):
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        if not getattr(self, "_closing", False):
            self.root.after(100, self.poll_events)

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
        self.refresh_tip.text = self.t("refresh_tip")
        self.cfg_tip.text = self.t("cfg_tip")
        self._sync_stop_btn()
        self.update_video_msg()
        if self._ph_active:
            self.search_var.set(self.t("search_ph"))
        if not self.adapter_items:
            self.adapter.set(self.t("no_tuner"))

    def show_volume(self, v):
        self.volume = v
        self.vol_lbl.configure(text=f"{v}%")
        self.vol_slider.set(v)

    def show_mute(self, m):
        self.muted = m
        self.mute_lbl.configure(text="🔇" if m else "🔊")

    def on_volume(self, val):
        v = round(float(val))
        if v != self.volume:
            self.volume = v
            self.vol_lbl.configure(text=f"{v}%")
            if self.stream:
                self.stream.set_prop("volume", v)
                self.stream.cmd("show-text", f"{self.t('osd_volume')}: {v}%", 3000)

    def toggle_mute(self, _=None):
        self.show_mute(not self.muted)
        if self.stream:
            self.stream.set_prop("mute", self.muted)
            self.stream.cmd("show-text", self.t("osd_mute_on" if self.muted else "osd_mute_off"), 3000)

    def on_key_i(self, event=None):
        if self.stream and not self._typing():      # dezactivată cât timp se scrie în căutare
            self.stream.show_tv_osd()

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
        elif name == "volume-max": self.vol_slider.configure(to=v)
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
        for b in (self.rec_btn, self.epg_btn):
            self.set_enabled(b, on)
        self._sync_stop_btn()      # fără redare, butonul devine „Închide programul”
        self.brand.configure(text=self.cur.strip() if on and self.cur else TITLE)
        self.set_epg(self.epg_now_next() if on else "")
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
        self.set_enabled(self.ca_btn, bool(self.adapter_items) and not self.scan_active)

    def reload(self):
        self.tv_channels, self.radio_channels, self.locked = load_channels()
        self._radio_names = {c for c, _ in self.radio_channels}
        self.set_enabled(self.chlist_btn, bool(self.tv_channels or self.radio_channels))
        self.fill_channels()

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
        self.stop()
        self.set_loading(name)
        time.sleep(0.15)
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
                                   on_msg=lambda m: self.events.put(lambda: self.on_ui_msg(m)))
            self.cur = self.last_channel = name
            self.select_current()
        except Exception as e:
            self.loading = False
            self.update_video_msg()
            messagebox.showerror(self.t("play_err"), str(e), parent=self.root)

    def stop(self):
        self.set_recording(False)
        if self.stream:
            self.stream.stop()
        self.stream = self.cur = None
        self.loading = False
        self.update_video_msg()

    # ---- înregistrări programate (din fereastra EPG)
    def is_scheduled(self, start, end):
        return bool(self.cur and self.schedule.find(self.cur, start, end))

    def schedule_toggle(self, start, end, title):
        """Programează sau anulează înregistrarea unei emisiuni de pe canalul curent: "added" | "removed" | "past"."""
        if not self.cur:
            return "past"
        job = self.schedule.find(self.cur, start, end)
        if job:
            if job is self.rec_job:
                self.set_recording(False)
            self.schedule.remove(job)
            return "removed"
        return "added" if self.schedule.add(self.cur, title, start, end) else "past"

    def _osd(self, text):
        if self.stream:
            self.stream.cmd("show-text", text, 5000)

    def _schedule_tick(self):
        """Apelat la fiecare tick: oprește joburile terminate și pornește/pregătește pe cele a căror oră a venit."""
        if not self.schedule.jobs:
            return
        now = time.time()
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
            "search_visible": self.search_wanted,
            "geometry": self._pre_fs_geom if self.fullscreen and self._pre_fs_geom else self.root.geometry(),
            "video_side": self.video_side,
            "borderless": bool(self.borderless_var.get()),
            "adapter": self.adapter_data() or self.settings.get("adapter", ""),
            "tuner_visible": self.settings_on,
            "scroll_position": self.settings.get("scroll_position", 0.0) if filtered else self.chlist.yview()[0],
            "rec_dir": str(self.rec_dir),
            "favorites": list(self.favorites),
            "mpv_opts": self.mpv_opts,
        })
        self.stop()
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


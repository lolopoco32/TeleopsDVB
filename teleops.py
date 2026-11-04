#!/usr/bin/env python3
"""Teleops DVB - Tkinter + mpv + dvbv5-zap, cu EPG și subtitrări DVB (nu doar cele embedded).
Dependențe: python3-tk, mpv (sau io.mpv.Mpv Flatpak), dvb-tools (dvbv5-scan, dvbv5-zap, dvb-fe-tool)
"""
import configparser, fcntl, functools, json, os, queue, re, select, shutil, socket, subprocess, sys, threading, time
import ctypes, ctypes.util
import tkinter as tk
import tkinter.font as tkfont
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

TITLE = "Teleops DVB"
CONF_DIR = Path.home() / ".config" / "TeleopsDVB"
CHANNELS = CONF_DIR / "channels.conf"
MPV_CONF = CONF_DIR / "mpv.conf"
SETTINGS = CONF_DIR / "settings.json"
SERVICES = CONF_DIR / "services.json"   # tip serviciu + flag 'codat' (din SDT), scris după scanare
REC_DIR = Path.home() / "Videos" / "TeleopsDVB"
ICON_PATH = Path(__file__).parent / "icon.png"
if not ICON_PATH.exists():
    ICON_PATH = Path("/usr/share/icons/hicolor/256x256/apps/teleops.png")
IPC_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "app/io.mpv.Mpv"
VOL_MAX = 130           # volume-max implicit în mpv
TXT_DARK = "#000000"    # culoare text implicită
LIST_MIN_H = 150        # înălțimea minimă (px) a listei de canale la strângerea ferestrei
PANEL_W = 320           # lățimea fixă a panoului cu comenzi
VIDEO_MIN_W = 480       # lățimea minimă a zonei video
GPU_CONTEXT = os.environ.get("TELEOPS_GPU_CONTEXT", "x11egl")   # mpv încorporat cere X11 (XWayland sub Wayland)

MPV_CONF_DATA = """# MPV configuration file
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
demuxer-lavf-probe-size=10000000
demuxer-lavf-analyzeduration=10.0
demuxer-readahead-seconds=5
"""

OSC_PATH = CONF_DIR / "teleops-osc.lua"
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
    elseif menu then
        menu = nil
    else
        hide()
        return
    end
    show()
end

local function on_dbl()
    local x, y = mp.get_mouse_pos()
    if hit(x, y) then return end
    mp.commandv("script-message", "toggle-ui")
end

mp.add_forced_key_binding("MBTN_LEFT", "teleops-click", on_click)
mp.add_forced_key_binding("MBTN_LEFT_DBL", "teleops-dbl", on_dbl)
mp.add_forced_key_binding("MBTN_RIGHT", "teleops-rclick", function()
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

for _, key in ipairs({"q", "Q", "Ctrl+c"}) do
    mp.add_forced_key_binding(key, "teleops-noquit-" .. key, function() end)
end

for _, key in ipairs({"SPACE", "p", "PAUSE", "PLAY", "PLAYPAUSE", ","}) do
    mp.add_forced_key_binding(key, "teleops-nopause-" .. key, function() end)
end
mp.observe_property("pause", "bool", function(_, v)
    if v then mp.set_property_bool("pause", false) end
end)
'''

CONF_DIR.mkdir(parents=True, exist_ok=True)
try: OSC_PATH.write_text(OSC_LUA, encoding="utf-8")
except OSError: pass
if not MPV_CONF.exists():
    MPV_CONF.write_text(MPV_CONF_DATA, encoding="utf-8")

LANGS = ("Română", "English", "Italiano")
T = {
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
    "hk_title": ("⌨️ Comenzi rapide", "⌨️ Hotkeys", "⌨️ Scorciatoie"),
    "hk_search": ("Arată/ascunde căutarea", "Show/hide search", "Mostra/nascondi ricerca"),
    "hk_search_k": ("Click Dreapta pe listă", "Right Click on list", "Clic destro sulla lista"),
    "hk_epg": ("Informații EPG", "EPG info", "Info EPG"),
    "hk_epg_k": ("CTRL + I", "CTRL + I", "CTRL + I"),
    "hk_fav": ("Adaugă / Elimină din Favorite", "Add / Remove Favorites", "Aungi / Rimuovi Preferiti"),
    "hk_fav_k": ("CTRL + Click Stânga", "CTRL + Left Click", "CTRL + Clic sinistro"),
    "hk_play": ("Redă canalul", "Play channel", "Riproduci il canale"),
    "hk_play_k": ("Dublu click / Enter", "Double click / Enter", "Doppio clic / Invio"),
    "hk_cfg": ("Ascunde/arată setările", "Hide/show settings", "Nascondi/mostra impostazioni"),
    "hk_cfg_k": ("Click pe titlu", "Click on title", "Clic sul titolo"),
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
    "osd_loading": ("Se încarcă EPG...", "Loading EPG...", "Caricamento EPG..."),
    "osd_na": ("Indisponibil", "Unavailable", "Non disponibile"),
    "scrambled": ("Canal codat (criptat): nu poate fi redat fără card/CAM.", "Scrambled (encrypted) channel: it can't be played without a card/CAM.", "Canale criptato: non riproducibile senza card/CAM."),
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

MPV_CONFIG_T = {
    "win_title": ("Configurare Avansată Completă MPV", "Complete Advanced MPV Configuration", "Configurazione Avanzata Completa MPV"),
    "tab_video": ("Video & Randare", "Video & Rendering", "Video e Rendering"),
    "tab_color": ("Culori & Gamma", "Colors & Gamma", "Colori e Gamma"),
    "tab_audio": ("Audio & Limbă", "Audio & Language", "Audio e Lingua"),
    "tab_subs": ("Subtitrări & Font", "Subtitles & Fonts", "Sottotitoli e Font"),
    "tab_advanced": ("Avansat & Cache", "Advanced & Cache", "Avanzato e Cache"),
    "btn_save": ("💾 Salvează setările", "💾 Save Settings", "💾 Salva Impostazioni"),
    "btn_reset": ("🔄 Resetează la Default", "🔄 Reset to Default", "🔄 Ripristina Predefiniti"),
    "btn_edit_conf": ("📝 Deschide mpv.conf", "📝 Open mpv.conf", "📝 Apri mpv.conf"),
}

def load_settings():
    try: return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception: return {}

def save_settings(d):
    try: SETTINGS.write_text(json.dumps(d), encoding="utf-8")
    except OSError: pass

def get_clean_env():
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "LIBPATH", "PYTHONPATH"):
        env.pop(var, None)
        env.pop(f"{var}_ORIG", None)
    return env

def find_mpv():
    if shutil.which("mpv"):
        return ["mpv"]
    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", "io.mpv.Mpv"], capture_output=True).returncode == 0:
        return ["flatpak", "run", "io.mpv.Mpv"]
    msg = ("Playerul MPV nu a fost găsit pe sistem.\n\nInstalează-l prin:\n  sudo apt install mpv\n"
           "sau\n  flatpak install flathub io.mpv.Mpv")
    print("Eroare: " + msg)
    tk.Tk().withdraw()
    messagebox.showerror(TITLE, msg)
    sys.exit(1)

def check_dependencies():
    missing = []
    if not shutil.which("dvbv5-zap") or not shutil.which("dvbv5-scan"):
        missing.append("dvb-tools (conține dvbv5-zap, dvbv5-scan)")
    if missing:
        msg = "Următoarele dependențe lipsesc pe sistem:\n\n" + "\n".join(f"  • {m}" for m in missing) + "\n\nInstalează-le prin:\n  sudo apt install dvb-tools"
        print("Eroare: " + msg)
        tk.Tk().withdraw()
        messagebox.showerror(TITLE, msg)
        sys.exit(1)

MPV = find_mpv()
check_dependencies()

class SleepInhibitor:
    def __init__(self):
        self.proc = None
        self.start()

    def start(self):
        try:
            if shutil.which("systemd-inhibit"):
                self.proc = subprocess.Popen(
                    ["systemd-inhibit", "--what=idle:sleep", "--who=TeleopsDVB", "--why=Live TV playback", "sleep", "infinity"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=get_clean_env()
                )
            elif shutil.which("xdg-screensaver"):
                subprocess.run(["xdg-screensaver", "suspend", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=1)
            if shutil.which("xdg-screensaver"):
                subprocess.run(["xdg-screensaver", "resume", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

@functools.cache
def zap_all_pids():
    try:
        r = subprocess.run(["dvbv5-zap", "--help"], capture_output=True, text=True, timeout=5, env=get_clean_env())
        return bool(re.search(r"^\s*-P\b", r.stdout + r.stderr, re.M))
    except (OSError, subprocess.SubprocessError):
        return False

HOTKEYS = (("hk_play", "hk_play_k"), ("hk_fav", "hk_fav_k"), ("hk_search", "hk_search_k"),
           ("hk_epg", "hk_epg_k"), ("hk_rec", "hk_rec_k"),
           ("hk_osc", "hk_osc_k"), ("hk_fs", "hk_fs_k"), ("hk_ui", "hk_ui_k"),
           ("hk_cfg", "hk_cfg_k"), ("hk_quit", "hk_quit_k"))

class X11:
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
        data = (c.c_ulong * 5)(2, 0, 0 if on else 1, 0, 0)
        rr, parent, kids, n = c.c_ulong(), c.c_ulong(), c.c_void_p(), c.c_uint()
        lib.XQueryTree(self.dpy, xid, c.byref(rr), c.byref(parent), c.byref(kids), c.byref(n))
        if kids:
            lib.XFree(kids)
        for win in {xid, parent.value} - {0, self.root}:
            lib.XChangeProperty(self.dpy, win, atom, atom, 32, 0, c.cast(data, c.c_void_p), 5)
        lib.XFlush(self.dpy)

def dvb_text(b):
    enc = None
    if b and b[0] < 0x20:
        c, b = b[0], b[1:]
        if c == 0x10: enc, b = f"iso-8859-{b[1]}", b[2:]
        else: enc = {0x11: "utf-16-be", 0x15: "utf-8"}.get(c, f"iso-8859-{c + 4}")
    try: s = b.decode(enc or "utf-8")
    except (UnicodeDecodeError, LookupError): s = b.decode("iso-8859-2", "replace")
    return re.sub(r"[\x80-\x9f]", lambda m: "\n" * (m.group() == "\x8a"), s).strip()

bcd = lambda x: (x >> 4) * 10 + (x & 15)
hm = lambda ts: datetime.fromtimestamp(ts).strftime("%H:%M")

class TSFilter:
    def __init__(self, sid):
        self.sid, self.pmt_pid, self.keep = sid, None, {0}
        self.bufs, self.rest, self.epg = {}, b"", {}
        self.sdt = {}

    def feed(self, data):
        data, out, i = self.rest + data, bytearray(), 0
        while i + 188 <= len(data):
            if data[i] != 0x47:
                i += 1
                continue
            if not data[i + 1] & 0x80:
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
        if pkt[1] & 0x40:
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
        if pid == 0 and t == 0:
            for j in range(8, len(s) - 4, 4):
                if (s[j] << 8 | s[j + 1]) == self.sid:
                    self.pmt_pid = (s[j + 2] & 0x1F) << 8 | s[j + 3]
                    self.keep.add(self.pmt_pid)
        elif pid == self.pmt_pid and t == 2 and num == self.sid:
            pids = {(s[8] & 0x1F) << 8 | s[9]}
            i = 12 + ((s[10] & 0x0F) << 8 | s[11])
            while i + 5 <= len(s) - 4:
                pids.add((s[i + 1] & 0x1F) << 8 | s[i + 2])
                i += 5 + ((s[i + 3] & 0xF) << 8 | s[i + 3 + 1])
            self.keep = {0, self.pmt_pid} | pids
        elif pid == 0x12 and (t == 0x4E or 0x50 <= t <= 0x5F) and num == self.sid:
            self.eit(s)
        elif pid == 0x11 and t == 0x42:
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

class Streamer:
    OBSERVED = ("volume-max", "volume", "mute", "vo-configured", "audio-params")
    KEYS = {"show-info-osd": ("Ctrl+i",), "toggle-ui": (".", "MBTN_LEFT_DBL"), "toggle-fs": ("f", "F", "F11"),
            "exit-fs": ("ESC",), "toggle-rec": ("Ctrl+r", "Ctrl+R"), "quit-app": ("Ctrl+X", "Ctrl+Shift+x", "Ctrl+Shift+X")}

    def __init__(self, adapter, channel, sid, props, on_prop, get_lang_func=None, wid=None, on_msg=None):
        self.props, self.on_prop, self.conn = dict(props), on_prop, None
        self.on_msg = on_msg or (lambda *_: None)
        self.osc_hot = False
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
            try: p.terminate()
            except Exception: pass
            if attempt == 0: time.sleep(0.5)
        
        if not self.zap:
            self.zap = subprocess.Popen(zap_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=get_clean_env())

        mpv = [*MPV, "--no-terminal", f"--include={MPV_CONF}", f"--input-ipc-server={self.sock}",
               "--sid=auto", "--sub-visibility=yes", f"--volume={props['volume']}",
               f"--mute={'yes' if props['mute'] else 'no'}", f"--title=TV - {channel.strip()}"]
        env = get_clean_env()
        if wid:
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
        lang = self.get_lang()
        idx = LANGS.index(lang) if lang in LANGS else 0
        return T[key][idx]

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
            t0 = time.time()
            time.sleep(3.0 if self.ts else 0.5)
            self.send_labels()
            shown = False
            while self.alive() and time.time() - t0 < 60:
                ok = self.epg_complete()
                if ok or (not shown and time.time() - t0 >= 12):
                    self.show_tv_osd()
                    shown = True
                    if ok: break
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
        if not self.ts: return None, None
        events = self.ts.events()
        cur = max((e for e in events if e[0] <= now < e[1]), key=lambda e: e[0], default=None)
        after = cur[1] if cur else now
        nxt = min((e for e in events if e[0] >= after - 60 and e is not cur), key=lambda e: e[0], default=None)
        return cur, nxt

    def epg_complete(self):
        if not self.ts: return True
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
        if nxt: next_title = nxt[2]

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

def load_services():
    try: return json.loads(SERVICES.read_text(encoding="utf-8"))
    except Exception: return {}

def load_channels():
    cp = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    cp.optionxform = str
    cp.read(CHANNELS, encoding="utf-8")
    svc = load_services()
    tv, radio, locked = [], [], set()
    for n in cp.sections():
        if re.search(r"^SW |SW DL|SmartDTV", n): continue
        sec = cp[n]
        sid = sec.get("SERVICE_ID", "").strip()
        stype = sec.get("SERVICE_TYPE", "").strip()
        meta = svc.get(f"{sec.get('FREQUENCY', '').strip()}:{sid}", {})
        is_radio = bool(stype in ("2", "0x2") or meta.get("t") in (2, 0x0A)
                        or ("VIDEO_PID" not in sec and "AUDIO_PID" in sec)
                        or re.search(r"\bradio\b|\bfm\b|europa\s*fm", n.lower()))
        if meta.get("ca"): locked.add(n)
        (radio if is_radio else tv).append((n, int(sid) if sid.isdigit() else 0))
    tv.sort(key=lambda x: x[0].strip().lower())
    radio.sort(key=lambda x: x[0].strip().lower())
    return tv, radio, locked

def list_frontends():
    return sorted(tuple(map(int, re.findall(r"\d+", str(p)))) for p in Path("/dev/dvb").glob("adapter*/frontend*"))

def probe_tuner(a, f):
    name, systems = "", []
    if shutil.which("dvb-fe-tool"):
        try:
            r = subprocess.run(["dvb-fe-tool", "-a", str(a), "-f", str(f)], capture_output=True, text=True,
                               timeout=5, env=get_clean_env())
            out, grab = r.stdout + "\n" + r.stderr, False
            if m := re.search(r"Device (.+?) \(/dev/dvb", out): name = m.group(1).strip()
            for line in out.splitlines():
                if "Supported delivery systems" in line: grab = True
                elif grab:
                    tok = line.strip().strip("[]")
                    if not (re.fullmatch(r"[A-Z0-9_/]+", tok) and line.startswith((" ", "\t"))): break
                    systems.append(tok)
        except Exception: pass
    kinds = dict.fromkeys(re.sub(r"^(ISDB|DVB)", r"\1-", s.split("/")[0]) for s in systems)
    label = name or f"adapter{a} / frontend{f}"
    return (f"{label} ({', '.join(kinds)})" if kinds else label), f"adapter{a}/frontend{f}", systems

def scan_init(mode, systems=()):
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
            if want_t2: ent.append(["DELIVERY_SYSTEM = DVBT2", f"FREQUENCY = {fr}", f"BANDWIDTH_HZ = {bw}", "INVERSION = AUTO"])
            if want_t: ent.append(["DELIVERY_SYSTEM = DVBT", f"FREQUENCY = {fr}", f"BANDWIDTH_HZ = {bw}", "INVERSION = AUTO",
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
    a, f = re.findall(r"\d+", adapter)[:2]
    tmp = CONF_DIR / "warm.tmp"
    if channel: cmd = ["dvbv5-zap", "-c", str(CHANNELS), "-a", a, "-f", f, "-o", "/dev/null", channel]
    else: cmd = ["dvbv5-scan", "-a", a, "-f", f, "-o", str(tmp), str(init)]
    for _ in range(2):
        try: p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace", env=get_clean_env())
        except OSError: return
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
        if not quick_fail: break
        time.sleep(1.0)
    tmp.unlink(missing_ok=True)

class ScrambleCounter:
    def __init__(self, pids):
        self.total, self.scr, self.rest = dict.fromkeys(pids, 0), dict.fromkeys(pids, 0), b""

    def feed(self, data):
        data, i = self.rest + data, 0
        while i + 188 <= len(data):
            if data[i] != 0x47:
                i += 1
                continue
            pid = (data[i + 1] & 0x1F) << 8 | data[i + 2]
            if pid in self.total and not data[i + 1] & 0x80 and data[i + 3] & 0x10:
                self.total[pid] += 1
                if data[i + 3] >> 6: self.scr[pid] += 1
            i += 188
        self.rest = data[i:]

    def verdict(self, pid, need=25):
        t = self.total.get(pid, 0)
        if t < need: return None
        r = self.scr[pid] / t
        return True if r >= 0.8 else False if r <= 0.2 else None

def detect_services(adapter, cancelled, set_proc):
    if not zap_all_pids(): return
    a, f = re.findall(r"\d+", adapter)[:2]
    cp = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    cp.optionxform = str
    cp.read(CHANNELS, encoding="utf-8")
    groups = {}
    for n in cp.sections():
        sec = cp[n]
        fr, sid = sec.get("FREQUENCY", "").strip(), sec.get("SERVICE_ID", "").strip()
        if not (fr and sid.isdigit()): continue
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
                elif p.poll() is not None: break
            _stop_proc(p)
            if any(cnt.total.values()) or cancelled(): break
            time.sleep(1.0)
        for sid, pid in svcs.items():
            res[f"{fr}:{sid}"] = {"t": sdt.sdt.get(sid, (None,))[0], "ca": cnt.verdict(pid) if pid else None}
    if not cancelled():
        SERVICES.write_text(json.dumps(res), encoding="utf-8")

class ChannelList(tk.Text):
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
        self.tag_configure("locked", foreground="#dc2626")
        self.tag_configure("cur", background=sel_bg, foreground=sel_fg)
        self.tag_raise("cur")
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
        while 0 <= i < len(self.selectable) and not self.selectable[i]: i += d
        if 0 <= i < len(self.selectable):
            self.selection_clear()
            self.selection_set(i)
            self.see(f"{i + 1}.0")
        return "break"

    def _wheel(self, e):
        if e.num == 4: self.yview_scroll(-3, "units")
        elif e.num == 5: self.yview_scroll(3, "units")
        else: self.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

class Tip:
    def __init__(self, w, text):
        self.w, self.text, self.tw = w, text, None
        w.bind("<Enter>", self.show)
        w.bind("<Leave>", self.hide)

    def show(self, _=None):
        if self.tw: return
        self.tw = tk.Toplevel(self.w)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{self.w.winfo_rootx()}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        tk.Label(self.tw, text=self.text, background="#ffffe0", relief="solid", borderwidth=1).pack()

    def hide(self, _=None):
        if self.tw: self.tw.destroy(); self.tw = None

class Main:
    def __init__(self, root):
        self.root, self.settings = root, load_settings()
        self.inhibitor = SleepInhibitor()
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
        self._mdrag, self._btn_prev = None, False
        self._stop_t, self._rec_osd_txt = 0.0, ""
        self.loading, self.load_name = False, ""

        self.list_items_meta = []
        self.locked, self.warmed, self.warm_busy, self._retry = set(), set(), False, 0

        if ICON_PATH.exists():
            try:
                self._icon = tk.PhotoImage(file=str(ICON_PATH))
                root.iconphoto(True, self._icon)
            except tk.TclError: pass

        self.video_side = self.settings.get("video_side") if self.settings.get("video_side") in ("left", "right") else "right"
        self.ui_visible, self.fullscreen, self._pre_fs_geom = True, False, ""
        gw, h, pos = 1100, 840, ""
        if m := re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", self.settings.get("geometry", "")):
            gw, h, pos = int(m.group(1)), int(m.group(2)), m.group(3) + m.group(4)
            if gw < PANEL_W + VIDEO_MIN_W: gw = 1100
        root.geometry(f"{gw}x{h}{pos}")
        root.minsize(PANEL_W + VIDEO_MIN_W, 400)
        self._min_h = 0
        root.resizable(True, True)

        for fmt, letters, fn in (("<Control-Key-{}>", "iI", self.on_key_i),
                                 ("<Control-Key-{}>", "rR", self.toggle_rec),
                                 ("<Control-Shift-Key-{}>", "xX", lambda e: self.on_close()),
                                 ("<Key-{}>", "fF", self.on_key_f)):
            for ch in letters: root.bind(fmt.format(ch), fn)
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
        st.configure("Brand.TLabel", font=f_brand)
        st.configure("Rec.TLabel", font=self.f_bold, foreground="#dc2626")
        st.configure("Epg.TLabel", font=self.f_norm)
        st.configure("EpgB.TLabel", font=self.f_bold)
        st.configure("Hk.TLabel", font=self.f_hk)
        st.configure("HkB.TLabel", font=self.f_hkb)
        st.configure("TButton", font=self.f_norm)
        st.configure("TCheckbutton", font=self.f_norm)
        st.configure("TCombobox", font=self.f_norm)

        bg_grey = self.bg_grey = st.lookup("TFrame", "background") or root.cget("bg")

        self.panel = tk.Frame(root, width=PANEL_W)
        self.panel.pack_propagate(False)
        self.video = tk.Frame(root, bg=self.bg_grey, width=640, height=360)
        self.video.pack(side="left", fill="both", expand=True)
        self.video.bind("<Button-1>", lambda e: self.video.focus_set())
        self.video.bind("<Double-Button-1>", self.toggle_ui)
        self.video_lbl = tk.Label(self.video, bg=self.bg_grey, fg="#555555", font=self.f_load, justify="center")
        self.video_lbl.bind("<Button-1>", lambda e: self.video.focus_set())
        self.video_lbl.bind("<Double-Button-1>", self.toggle_ui)
        main = ttk.Frame(self.panel, padding=14)
        main.pack(fill="both", expand=True)
        self.main = main

        bottom = ttk.Frame(main)
        bottom.pack(side="bottom", fill="x")

        top = ttk.Frame(main)
        top.pack(fill="x", pady=5)
        top.columnconfigure(0, weight=1)
        self.brand = ttk.Label(top, text=TITLE, style="Brand.TLabel", anchor="center", cursor="hand2")
        self._drag_bind(self.brand, click=self.toggle_tuner)
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
        self.ca_btn = self._btn(tc, "ca_btn", self.start_ca_detect)
        self._btn(tc, "cfg_mpv", self.open_advanced_mpv_config)
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
        
        for key in ("<Return>", "<KP_Enter>"): self.chlist.bind(key, self.on_list_enter)
        self.chlist.bind("<Button-3>", self.toggle_search)
        self.search.pack(fill="x", pady=5)

        self.bottom_sep = ttk.Separator(bottom, orient="horizontal")
        self.bottom_sep.pack(fill="x", pady=(0, 5))

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

        self.epg_btn = self._btn(bottom, "epg_btn", self.show_epg, pady=(5, 0))
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
        self._bind_drag(self.panel)
        self._drag_bind(self.video)
        self._drag_bind(self.video_lbl)
        root.after(40, self._mpv_drag_poll)
        if self.borderless_var.get(): root.after(400, self.apply_borderless)
        self.layout()
        root.after(250, self.tick)
        root.after(100, self.poll_events)

    def t(self, key):
        return T[key][LANGS.index(self.lang)]

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
            if self.search_wanted: self.search.pack(fill="x", pady=5, before=self.bottom_sep)
        self._min_h = 0
        self.root.after_idle(self.fit_min_height)

    def layout(self):
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
        if not self.fullscreen: self._pre_fs_geom = self.root.geometry()
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def _typing(self):
        try: return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox))
        except KeyError: return False

    def on_key_dot(self, _=None):
        if not self._typing(): self.toggle_ui()

    def on_key_f(self, _=None):
        if not self._typing(): self.toggle_fullscreen()

    def toggle_rec(self, _=None):
        if self.stream or self.rec_on: self.set_recording(not self.rec_on)

    def _sync_stop_btn(self):
        txt = self.t("stop_play" if self.stream else "quit_app")
        if self.stop_btn.cget("text") != txt: self.stop_btn.configure(text=txt)

    def on_stop_btn(self):
        if self.stream:
            self._stop_t = time.time()
            self.stop()
        elif time.time() - self._stop_t > 0.7: self.on_close()

    def on_ui_msg(self, msg):
        if msg == "toggle-ui": self.toggle_ui()
        elif msg == "toggle-fs" or (msg == "exit-fs" and self.fullscreen): self.toggle_fullscreen()
        elif msg == "quit-app": self.on_close()
        elif msg == "toggle-rec": self.toggle_rec()

    def _win_pos(self):
        m = re.match(r"\d+x\d+([+-]+\d+)([+-]+\d+)", self.root.geometry())
        if not m: return self.root.winfo_x(), self.root.winfo_y()
        return int(m.group(1).replace("+-", "-")), int(m.group(2).replace("+-", "-"))

    def _drag_to(self, p, x, y):
        x0, y0, wx, wy, moved = p
        dx, dy = x - x0, y - y0
        if moved or abs(dx) + abs(dy) >= 4:
            moved = True
            self.root.geometry(f"+{wx + dx}+{wy + dy}")
        return x0, y0, wx, wy, moved

    def _drag_bind(self, w, click=None):
        st = {}
        def motion(e):
            if st.get("p") and not self.fullscreen: st["p"] = self._drag_to(st["p"], e.x_root, e.y_root)
        def release(e):
            p = st.pop("p", None)
            if p and not p[4] and click: click()
        w.bind("<ButtonPress-1>", lambda e: st.update(p=(e.x_root, e.y_root, *self._win_pos(), False)), add="+")
        w.bind("<B1-Motion>", motion, add="+")
        w.bind("<ButtonRelease-1>", release, add="+")

    def _bind_drag(self, w):
        if type(w) in (tk.Frame, ttk.Frame, ttk.Label) and w not in (self.brand, self.mute_lbl):
            self._drag_bind(w)
        for c in w.winfo_children(): self._bind_drag(c)

    def _mpv_drag_poll(self):
        self.root.after(12 if self._mdrag else 40, self._mpv_drag_poll)
        if not (self.x11 and self.stream) or self.fullscreen:
            self._mdrag = self._btn_prev = None
            return
        try: x, y, mask = self.x11.pointer()
        except Exception: return
        down = bool(mask & X11.BUTTON1)
        v = self.video
        if down and not self._btn_prev:
            if (v.winfo_rootx() <= x < v.winfo_rootx() + v.winfo_width() and v.winfo_rooty() <= y < v.winfo_rooty() + v.winfo_height()
                    and not self.stream.osc_hot):
                self._mdrag = (x, y, *self._win_pos(), False)
        elif down and self._mdrag: self._mdrag = self._drag_to(self._mdrag, x, y)
        elif not down: self._mdrag = None
        self._btn_prev = down

    def apply_borderless(self):
        if not self.x11:
            self.borderless_var.set(False)
            messagebox.showwarning(TITLE, self.t("x11_na"), parent=self.root)
            return
        self.root.update_idletasks()
        self.x11.set_borderless(self.root.winfo_id(), self.borderless_var.get())

    def fit_min_height(self):
        if not self.ui_visible: return
        self.root.update_idletasks()
        need = self.main.winfo_reqheight()
        if not self.settings_on: need += LIST_MIN_H - self.list_frame.winfo_reqheight()
        if need != self._min_h:
            self._min_h = need
            self.root.minsize(PANEL_W + VIDEO_MIN_W, need)
        if self.root.winfo_ismapped() and not self.fullscreen and self.root.winfo_height() < need:
            self.root.geometry(f"{self.root.winfo_width()}x{need}")

    def poll_events(self):
        try:
            while True: self.events.get_nowait()()
        except queue.Empty: pass
        if not getattr(self, "_closing", False): self.root.after(100, self.poll_events)

    def on_lang(self, _=None):
        self.lang = self.lang_box.get()
        self.apply_translations()
        self.fill_channels()
        if self.stream:
            self.stream.send_labels()
            self.stream.show_tv_osd()

    def apply_translations(self):
        self.root.title(TITLE)
        for w, key in self.tr: w.configure(text=self.t(key))
        self.rec_btn.configure(text=self.t("rec_on" if self.rec_on else "rec_off"))
        self.refresh_tip.text = self.t("refresh_tip")
        self._sync_stop_btn()
        self.update_video_msg()
        if self._ph_active: self.search_var.set(self.t("search_ph"))
        if not self.adapter_items: self.adapter.set(self.t("no_tuner"))

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
        if self.stream and not self._typing(): self.stream.show_tv_osd()

    def is_radio(self, name):
        return bool(name) and any(c == name for c, _ in self.radio_channels)

    def set_loading(self, name):
        self.loading, self.load_name = True, name
        self.update_video_msg()

    def update_video_msg(self):
        name = (self.load_name if self.loading else (self.cur or "")).strip()
        if self.loading: txt = f"{name}\n{self.t('loading')}" if name else self.t("loading")
        elif not self.stream: txt = f"📺⇄📻 {TITLE}"
        elif self.is_radio(self.cur): txt = f"📻  {name}"
        else: txt = ""
        if txt:
            self.video_lbl.configure(text=txt)
            self.video_lbl.place(relx=0.5, rely=0.5, anchor="center")
        else: self.video_lbl.place_forget()

    def on_mpv_prop(self, name, v):
        if name == "volume": self.show_volume(round(v))
        elif name == "mute": self.show_mute(bool(v))
        elif name == "volume-max": self.vol_slider.configure(to=v)
        elif (name == "vo-configured" and v) or (name == "audio-params" and self.is_radio(self.cur)):
            if self.loading:
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
        elif not self.settings_on: self.search.pack(fill="x", pady=5, before=self.bottom_sep)
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
        meta = self.list_items_meta[i] if 0 <= i < len(self.list_items_meta) else None
        return meta[1] if meta and meta[0] == "channel" else None

    def on_list_double(self, e):
        name = self._channel_at(self.chlist.nearest(e.y))
        if name is not None: self.try_tune(name)

    def try_tune(self, name):
        if name in self.locked: messagebox.showinfo(TITLE, self.t("scrambled"), parent=self.root)
        else: self.tune(name)

    def on_ctrl_click(self, e):
        name = self._channel_at(self.chlist.nearest(e.y))
        if name is not None:
            self.favorites ^= {name}
            self.fill_channels()

    def on_list_enter(self, _=None):
        sel = self.chlist.curselection()
        name = self._channel_at(sel[0]) if sel else None
        if name is not None: self.try_tune(name)

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
                    self.root.after(800, lambda: self.tune(name, 1))
                elif rc == 255:
                    messagebox.showerror(self.t("play_err"), self.t("tuner_crash"), parent=self.root)
                    self.detect_tuners()
                else: messagebox.showerror(self.t("play_err"), f"dvbv5-zap: cod {rc}", parent=self.root)
        on = self.stream is not None
        for b in (self.rec_btn, self.epg_btn): self.set_enabled(b, on)
        self._sync_stop_btn()
        self.brand.configure(text=self.cur.strip() if on and self.cur else TITLE)
        self.set_epg(self.epg_now_next() if on else "")
        if self.rec_on:
            txt = self._rec_txt()
            self.rec_lbl.configure(text=txt)
            if self.stream and txt != self._rec_osd_txt:
                self._rec_osd_txt = txt
                self.stream.set_rec_osd(txt)
        self.fit_min_height()

    def open_advanced_mpv_config(self):
        """Fereastră nouă de configurare MPV compactă, perfect centrată și aliniată simetric."""
        w = tk.Toplevel(self.root)
        idx_lang = LANGS.index(self.lang) if self.lang in LANGS else 0
        w.title(MPV_CONFIG_T["win_title"][idx_lang])
        w.geometry("620x540")
        w.resizable(False, False)
        w.transient(self.root)
        w.grab_set()

        cfg_lines = []
        if MPV_CONF.exists():
            try: cfg_lines = MPV_CONF.read_text(encoding="utf-8").splitlines()
            except Exception: pass
        
        cfg_dict = {}
        for line in cfg_lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg_dict[k.strip()] = v.strip()

        notebook = ttk.Notebook(w)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        def make_scrollable_tab(parent_nb, tab_title):
            f = ttk.Frame(parent_nb)
            canvas = tk.Canvas(f, borderwidth=0, highlightthickness=0)
            scrollbar = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
            
            # Container intern centrat cu lățime fixă uniformă pentru aliniere perfectă a chenarelor
            inner_container = ttk.Frame(canvas)
            scrollable_frame = ttk.Frame(inner_container, padding=10)
            scrollable_frame.pack(anchor="center", fill="both", expand=True)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            win_id = canvas.create_window((0, 0), window=inner_container, anchor="nw")
            
            def _on_canvas_configure(e):
                canvas.itemconfig(win_id, width=e.width)
            canvas.bind("<Configure>", _on_canvas_configure)
            
            canvas.configure(yscrollcommand=scrollbar.set)
            
            def _on_mousewheel(e):
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            parent_nb.add(f, text=tab_title)
            return scrollable_frame

        tab_v = make_scrollable_tab(notebook, MPV_CONFIG_T["tab_video"][idx_lang])
        tab_c = make_scrollable_tab(notebook, MPV_CONFIG_T["tab_color"][idx_lang])
        tab_a = make_scrollable_tab(notebook, MPV_CONFIG_T["tab_audio"][idx_lang])
        tab_s = make_scrollable_tab(notebook, MPV_CONFIG_T["tab_subs"][idx_lang])
        tab_adv = make_scrollable_tab(notebook, MPV_CONFIG_T["tab_advanced"][idx_lang])

        widgets_map = {}
        grid_pos = {}

        def add_opt(tab, key, title_tr, desc_tr, default_val, options, choice_descs=None):
            col, row = grid_pos.get(tab, (0, 0))
            
            # Cadru exterior pentru aliniere simetrică pe 2 coloane centrate
            cell_frame = ttk.Frame(tab)
            cell_frame.grid(row=row, column=col, padx=6, pady=4, sticky="nsew")
            tab.columnconfigure(col, weight=1)

            frame = ttk.LabelFrame(cell_frame, text=title_tr[idx_lang], padding=(8, 6))
            frame.pack(fill="both", expand=True)
            
            val = cfg_dict.get(key, default_val)
            var = tk.StringVar(value=val)
            
            # Combobox centrat în interiorul chenarului
            cb = ttk.Combobox(frame, textvariable=var, values=options, state="readonly", width=22, justify="center")
            cb.pack(pady=(2, 4))
            widgets_map[key] = var

            # Text de descriere centrat frumos sub meniu
            desc_label = ttk.Label(frame, font=self.f_hk, foreground="#555555", wraplength=250, justify="center", anchor="center")
            desc_label.pack(fill="x", padx=2)

            def update_description(*args):
                cur_val = var.get()
                base_text = desc_tr[idx_lang]
                if choice_descs and cur_val in choice_descs:
                    sub_desc = choice_descs[cur_val]
                    if isinstance(sub_desc, tuple): sub_desc = sub_desc[idx_lang]
                    full_text = f"{base_text}\n• {sub_desc}"
                else:
                    full_text = base_text
                desc_label.configure(text=full_text)

            var.trace_add("write", update_description)
            update_description()

            if col == 0:
                grid_pos[tab] = (1, row)
            else:
                grid_pos[tab] = (0, row + 1)

        LANG_OPTIONS = [
            "rum,ron,ro,en,it",
            "rum,ron,ro",
            "en,ro,it",
            "ro,en",
            "it,en,ro",
            "en,it,ro",
            "de,en,ro",
            "fr,en,ro"
        ]

        # Tab Video & Randare
        add_opt(tab_v, "profile", ("Profil Randare", "Rendering Profile", "Profilo Rendering"),
                ("Setează profilul calității video.", "Set video quality profile.", "Imposta il profilo di qualità video."), "gpu-hq", ["gpu-hq", "fast", "default"],
                choice_descs={
                    "gpu-hq": ("Calitate maximă (recomandat pentru claritate)", "Top quality (recommended)", "Massima qualità"),
                    "fast": ("Performanță crescută, sacrifică din filtre", "Higher performance, lower filters", "Prestazioni elevate"),
                    "default": ("Profilul standard simplu mpv", "Simple standard profile", "Profilo standard semplice")
                })
        
        add_opt(tab_v, "hwdec", ("Accelerare Hardware", "Hardware Acceleration", "Accelerazione Hardware"),
                ("Decodare video pe GPU pentru a reduce CPU.", "GPU video decoding to reduce CPU load.", "Decodifica video GPU per ridurre il carico CPU."), "auto", ["auto", "yes", "no", "auto-copy", "nvdec", "vaapi"],
                choice_descs={
                    "auto": ("Detectează automat cel mai bun mod hardware", "Auto-detect best hardware mode", "Rileva automaticamente"),
                    "yes": ("Activează decodarea hardware directă pe GPU", "Enable direct GPU hardware decoding", "Abilita decodifica hardware"),
                    "no": ("Decodare exclusiv software pe procesor (CPU)", "Software-only CPU decoding", "Solo decodifica software CPU"),
                    "auto-copy": ("Decodare cu copiere automată în memorie", "HW decode with memory auto-copy", "Copia automatica memoria"),
                    "nvdec": ("Accelerare dedicată plăcilor NVIDIA", "Dedicated NVIDIA cards acceleration", "Accelerazione schede NVIDIA"),
                    "vaapi": ("Interfață standard VA-API pentru Intel/AMD", "Standard VA-API for Intel and AMD", "Standard VA-API")
                })

        add_opt(tab_v, "vo", ("Driver Video (VO)", "Video Output Driver", "Driver Output Video"),
                ("Interfața grafică utilizată pentru redare.", "Graphics interface used for rendering video.", "Interfaccia grafica usata per il rendering."), "gpu", ["gpu", "gpu-next", "xv", "x11"],
                choice_descs={
                    "gpu": ("Output OpenGL/Vulkan modern și stabil", "Modern stable OpenGL/Vulkan output", "Output moderno stabile"),
                    "gpu-next": ("Motor experimental bazat pe libplacebo", "Experimental next-gen engine", "Motore sperimentale nuovo"),
                    "xv": ("XVideo legacy pentru plăci mai vechi", "Legacy XVideo for older hardware", "XVideo legacy"),
                    "x11": ("Redare de bază direct pe fereastra X11", "Basic X11 window rendering", "Rendering base X11")
                })

        add_opt(tab_v, "gpu-api", ("API Grafic", "Graphics API", "API Grafica"),
                ("Modul de interacțiune cu placa video.", "Graphic card backend interface.", "Interfaccia backend scheda video."), "opengl", ["opengl", "vulkan", "auto"],
                choice_descs={
                    "opengl": ("API compatibil și stabil pe majoritatea plăcilor", "Stable and compatible API", "API stabile e compatibile"),
                    "vulkan": ("API grafic modern de înaltă performanță", "Modern high-performance graphics API", "API grafico moderno alte prestazioni"),
                    "auto": ("Selectează automat API-ul optim", "Automatically select optimal API", "Selezione automatica")
                })

        add_opt(tab_v, "scale", ("Scalare Luma (Scale)", "Luma Scaler", "Ridimensionamento Luma"),
                ("Algoritm de scalare pentru claritate video.", "Scaling algorithm for video sharpness.", "Algoritmo di ridimensionamento per la nitidezza."), "spline36", ["spline36", "mitchell", "bicubic", "lanczos", "bilinear"],
                choice_descs={
                    "spline36": ("Echilibru excelent între claritate și artefacte", "Excellent balance of sharpness and artifacts", "Ottimo bilanciamento nitidezza"),
                    "mitchell": ("Imagine netedă, reduce zgomotul", "Smooth image, reduces ringing", "Immagine uniforme"),
                    "bicubic": ("Standard rapid și eficient", "Fast and efficient standard", "Standard veloce ed efficiente"),
                    "lanczos": ("Foarte clar, poate genera margini luminoase", "Very sharp, can produce slight ringing", "Molto nitido"),
                    "bilinear": ("Cel mai rapid, dar cu claritate redusă", "Fastest, lowest quality", "Più veloce, minor qualità")
                })

        add_opt(tab_v, "cscale", ("Scalare Croma (Cscale)", "Chroma Scaler", "Ridimensionamento Croma"),
                ("Algoritm dedicat scalării culorilor.", "Dedicated algorithm for color channels scaling.", "Algoritmo dedicato per i canali colore."), "mitchell", ["mitchell", "spline36", "bicubic", "bilinear"],
                choice_descs={
                    "mitchell": ("Culori naturale și bine delimitate", "Natural and well-defined colors", "Colori naturali e definiti"),
                    "spline36": ("Precizie ridicată la tranzițiile de culoare", "High precision in color transitions", "Alta precisione nei colori"),
                    "bicubic": ("Randare rapidă a canalelor de croma", "Fast chroma channels rendering", "Rendering rapido dei colori"),
                    "bilinear": ("Consum minim de resurse", "Minimum resource usage", "Minimo consumo di risorse")
                })

        add_opt(tab_v, "dither-depth", ("Profunzime Dithering", "Dither Depth", "Profondità Dithering"),
                ("Reduce artefactele de culoare pe ecrane.", "Reduces color banding artifacts.", "Riduce gli artefatti di banding colore."), "auto", ["auto", "8", "10", "no"],
                choice_descs={
                    "auto": ("Detectează adâncimea corectă a ecranului", "Auto-detect screen bit depth", "Rileva automatica profondità"),
                    "8": ("Forțează dithering pe 8 biți", "Force 8-bit dithering", "Forza dithering a 8 bit"),
                    "10": ("Forțează dithering pe 10 biți", "Force 10-bit dithering", "Forza dithering a 10 bit"),
                    "no": ("Dezactivează complet dithering-ul", "Disable dithering completely", "Disabilita completamente")
                })

        add_opt(tab_v, "cursor-autohide", ("Ascundere Cursor", "Cursor Autohide", "Nascondi Cursore"),
                ("Timpul în milisecunde până la ascundere.", "Delay in ms before hiding mouse cursor.", "Ritardo in ms prima di nascondere il cursore."), "1000", ["500", "1000", "2000", "always", "no"],
                choice_descs={
                    "500": ("Ascunde cursorul după 0.5 secunde", "Hide cursor quickly after 0.5s", "Nascondi rapidamente"),
                    "1000": ("Ascunde cursorul după 1 secundă", "Hide after 1 second of inactivity", "Nascondi dopo 1 secondo"),
                    "2000": ("Ascunde cursorul după 2 secunde", "Hide after 2 seconds", "Nascondi dopo 2 secondi"),
                    "always": ("Ascunde cursorul permanent", "Always hide cursor permanently", "Nascondi sempre"),
                    "no": ("Cursorul rămâne mereu vizibil", "Cursor remains always visible", "Cursore sempre visibile")
                })

        # Tab Culori & Gamma
        add_opt(tab_c, "video-output-levels", ("Nivel Ieșire Culori", "Color Output Levels", "Livelli Output Colore"),
                ("Gama dinamică RGB (Full 0-255 recomandat).", "RGB dynamic range (Full 0-255 recommended).", "Gamma dinamica RGB (Full 0-255 consigliata)."), "full", ["full", "limited", "auto"],
                choice_descs={
                    "full": ("Gamă completă 0-255, negru profund (recomandat)", "Full range 0-255, deep blacks (recommended)", "Gamma completa 0-255"),
                    "limited": ("Gamă limitată 16-235 pentru televizoare vechi", "Limited range 16-235 for legacy TVs", "Gamma limitata 16-235"),
                    "auto": ("Selectează automat nivelul optim", "Automatically select output level", "Selezione automatica livello")
                })

        add_opt(tab_c, "target-prim", ("Spațiu de Culoare", "Target Primaries", "Spazio Colore"),
                ("Profilul de culori primare al ecranului.", "Display primary color space profile.", "Profilo spazio colore primario del display."), "bt.709", ["bt.709", "bt.2020", "srgb", "auto"],
                choice_descs={
                    "bt.709": ("Standard HD rec.709 pentru TV și conținut uzual", "HD standard rec.709 for regular TV", "Standard HD rec.709"),
                    "bt.2020": ("Standard extins pentru 4K UHD modern", "Extended standard for modern 4K UHD", "Standard esteso 4K UHD"),
                    "srgb": ("Spațiu standard pentru monitoare PC", "Standard space for PC monitors", "Spazio standard monitor PC"),
                    "auto": ("Detectează spațiul de culoare automat", "Auto-detect color primaries", "Rileva automaticamente")
                })

        add_opt(tab_c, "target-trc", ("Curba de Transfer Gamma", "Target TRC / Gamma", "Curva Gamma"),
                ("Curba de corecție gamma pentru luminozitate.", "Gamma transfer curve for proper luminance.", "Curva di correzione gamma."), "bt.1886", ["bt.1886", "srgb", "pq", "hlg", "auto"],
                choice_descs={
                    "bt.1886": ("Standard universal pentru ecrane TV și monitoare", "Universal standard for screens and TVs", "Standard universale TV"),
                    "srgb": ("Curbă gamma specifică sRGB", "Specific sRGB gamma curve", "Curva gamma sRGB"),
                    "pq": ("Curbă HDR (Perceptual Quantizer)", "HDR curve (Perceptual Quantizer)", "Curva HDR PQ"),
                    "hlg": ("Curbă HDR HLG pentru transmisii live", "HLG HDR curve for live TV broadcasts", "Curva HDR HLG")
                })

        add_opt(tab_c, "contrast", ("Contrast Video", "Video Contrast", "Contrasto Video"),
                ("Modifică nivelul de contrast al imaginii.", "Modifies video playback contrast level.", "Modifica il livello di contrasto video."), "0", ["-20", "-10", "0", "10", "20"],
                choice_descs={
                    "0": ("Nivel de contrast standard nemodificat", "Standard unchanged contrast level", "Livello standard"),
                    "10": ("Crește ușor contrastul imaginii", "Slightly increases image contrast", "Aumenta leggermente il contrasto"),
                    "20": ("Crește puternic contrastul imaginii", "Strongly increases contrast", "Aumenta fortemente il contrasto"),
                    "-10": ("Reduce ușor contrastul imaginii", "Slightly decreases contrast", "Riduce leggermente il contrasto")
                })

        # Tab Audio & Limbă
        add_opt(tab_a, "alang", ("Ordinea Limbilor Audio", "Audio Language Priority", "Priorità Lingua Audio"),
                ("Alege ordinea preferată pentru audio.", "Select preferred order for audio languages.", "Seleziona l'ordine preferito per l'audio."), "rum,ron,ro,en,it", LANG_OPTIONS,
                choice_descs={
                    "rum,ron,ro,en,it": ("Prioritate Română, apoi Engleză și Italiană", "Priority Romanian, then English and Italian", "Priorità Romeno, poi Inglese e Italiano"),
                    "rum,ron,ro": ("Exclusiv limba Română", "Romanian language exclusively", "Solo lingua romena"),
                    "en,ro,it": ("Prioritate Engleză, apoi Română", "Priority English, then Romanian", "Priorità Inglese, poi Romeno"),
                    "ro,en": ("Română și Engleză", "Romanian and English", "Romeno e Inglese")
                })

        add_opt(tab_a, "af", ("Filtru / Normalizare Audio", "Audio Filter / Normalization", "Filtro / Normalizzazione Audio"),
                ("Comprimă dinamica sunetului pentru volum uniform.", "Compresses dynamic range for uniform volume.", "Comprime la gamma dinamica per volume uniforme."), "none", ["none", "drunoid", "loudnorm"],
                choice_descs={
                    "none": ("Fără filtre audio aplicate (sunet original direct)", "No audio filters applied (direct original sound)", "Nessun filtro audio applicato"),
                    "drunoid": ("Normalizare dinamică optimizată pentru voce", "Dynamic normalization optimized for speech", "Normalizzazione dinamica"),
                    "loudnorm": ("Normalizare standard EBU R128 a volumului", "Standard EBU R128 loudness normalization", "Normalizzazione standard EBU R128")
                })

        add_opt(tab_a, "volume-max", ("Volum Maxim (%)", "Volume Max Limit (%)", "Volume Massimo (%)"),
                ("Limita superioară a amplificării peste 100%.", "Upper volume amplification limit over 100%.", "Limite superiore amplificazione volume oltre 100%."), "130", ["100", "120", "130", "150", "200"],
                choice_descs={
                    "100": ("Volum maxim limitat strict la 100%", "Volume strictly limited to 100%", "Volume massimo limitato al 100%"),
                    "130": ("Amplificare maximă de 130% (recomandat)", "Maximum amplification 130% (recommended)", "Amplificazione massima 130%"),
                    "150": ("Amplificare puternică până la 150%", "Strong amplification up to 150%", "Forte amplificazione fino al 150%"),
                    "200": ("Amplificare dublă până la 200%", "Double amplification up to 200%", "Doppia amplificazione fino al 200%")
                })

        # Tab Subtitrări & Font
        add_opt(tab_s, "slang", ("Ordinea Limbilor Subtitrare", "Subtitle Language Priority", "Priorità Lingua Sottotitoli"),
                ("Alege ordinea preferată pentru subtitrări.", "Select preferred order for subtitles.", "Seleziona l'ordine preferito per i sottotitoli."), "rum,ron,ro,en,it", LANG_OPTIONS,
                choice_descs={
                    "rum,ron,ro,en,it": ("Prioritate Română, apoi Engleză și Italiană", "Priority Romanian, then English and Italian", "Priorità Romeno, poi Inglese e Italiano"),
                    "rum,ron,ro": ("Exclusiv subtitrare în limba Română", "Romanian subtitles exclusively", "Solo sottotitoli in romeno"),
                    "en,ro,it": ("Prioritate Engleză, apoi Română", "Priority English, then Romanian", "Priorità Inglese, poi Romeno"),
                    "ro,en": ("Română și Engleză", "Romanian and English", "Romeno e Inglese")
                })

        add_opt(tab_s, "sub-font-size", ("Dimensiune Font Subtitrare", "Subtitle Font Size", "Dimensione Carattere Sottotitoli"),
                ("Mărimea textului pentru subtitrări.", "Text size for rendered subtitles.", "Dimensione del testo per i sottotitoli."), "36", ["28", "32", "36", "40", "44", "48"],
                choice_descs={
                    "28": ("Font compact, ideal pentru ecrane mici", "Compact font for small screens", "Font compatto"),
                    "36": ("Dimensiune standard echilibrată (recomandat)", "Balanced standard size (recommended)", "Dimensione standard bilanciata"),
                    "44": ("Font mare, ușor de citit de la distanță", "Large font, easily readable from distance", "Font grande facilmente leggibile"),
                    "48": ("Font foarte mare", "Very large font size", "Font molto grande")
                })

        add_opt(tab_s, "sub-visibility", ("Vizibilitate Subtitrări", "Subtitles Visibility", "Visibilità Sottotitoli"),
                ("Afișarea automată a subtitrărilor la pornire.", "Automatic subtitles display upon start.", "Visualizzazione automatica dei sottotitoli."), "yes", ["yes", "no"],
                choice_descs={
                    "yes": ("Activează automat subtitrările disponibile", "Automatically enable available subtitles", "Attiva automaticamente i sottotitoli"),
                    "no": ("Dezactivează afișarea automată a subtitrărilor", "Disable automatic subtitles display", "Disabilita visualizzazione automatica")
                })

        # Tab Avansat & Cache
        add_opt(tab_adv, "demuxer-readahead-seconds", ("Cache Readahead (secunde)", "Readahead Cache (seconds)", "Cache Readahead (secondi)"),
                ("Cantitatea de flux stocată în buffer.", "Stream amount buffered in memory ahead of playback.", "Quantità di flusso memorizzata in buffer."), "5", ["2", "5", "10"],
                choice_descs={
                    "2": ("Buffer scurt pentru pornire rapidă", "Short buffer for fast startup", "Buffer corto per avvio rapido"),
                    "5": ("Buffer stabil de 5 secunde (recomandat)", "Stable 5s buffer (recommended for live TV)", "Buffer stabile di 5 secondi"),
                    "10": ("Buffer mare de 10 secunde pentru semnal instabil", "Large 10s buffer for unstable signal", "Buffer grande di 10 secondi")
                })

        add_opt(tab_adv, "keep-open", ("Menține Player Deschis", "Keep Player Open", "Mantieni Lettore Aperto"),
                ("Evită închiderea ferestrei la pierderea semnalului.", "Prevents window closing on brief signal loss.", "Evita la chiusura della finestra se manca il segnale."), "yes", ["yes", "always", "no"],
                choice_descs={
                    "yes": ("Menține fereastra deschisă la finalul fluxului", "Keep player window open on stream end", "Mantieni finestra aperta"),
                    "always": ("Menține playerul deschis permanent", "Keep player open permanently", "Mantieni sempre aperto"),
                    "no": ("Închide fereastra imediat ce fluxul se oprește", "Close window immediately on stream stop", "Chiudi alla fine")
                })

        btn_frame = ttk.Frame(w, padding=6)
        btn_frame.pack(fill="x", side="bottom")

        def save_config():
            new_lines = ["# MPV configuration file (Teleops DVB Complete Advanced Editor)"]
            for k, var in widgets_map.items():
                val = var.get().strip()
                if val and val != "none": new_lines.append(f"{k}={val}")
            try:
                MPV_CONF.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                w.destroy()
            except Exception as e:
                messagebox.showerror(TITLE, str(e), parent=w)

        def reset_config():
            try:
                MPV_CONF.write_text(MPV_CONF_DATA, encoding="utf-8")
                w.destroy()
            except Exception as e:
                messagebox.showerror(TITLE, str(e), parent=w)

        ttk.Button(btn_frame, text=MPV_CONFIG_T["btn_save"][idx_lang], command=save_config).pack(side="left", padx=4)
        ttk.Button(btn_frame, text=MPV_CONFIG_T["btn_reset"][idx_lang], command=reset_config).pack(side="left", padx=4)
        ttk.Button(btn_frame, text=MPV_CONFIG_T["btn_edit_conf"][idx_lang], command=self.open_mpv_config).pack(side="right", padx=4)

    def open_mpv_config(self):
        MPV_CONF.touch()
        path = str(MPV_CONF.resolve())
        for cmd in ("xdg-open", "gio open", "kate", "gedit", "kwrite", "mousepad", "xed", "pluma", "gnome-text-editor"):
            argv = cmd.split()
            if shutil.which(argv[0]):
                subprocess.Popen(argv + [path], env=get_clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
        messagebox.showwarning("Atenție", f"Fișierul există la:\n{path}\n\nNu s-a găsit niciun editor de text.", parent=self.root)

    def choose_rec_dir(self):
        start = self.rec_dir if self.rec_dir.is_dir() else Path.home()
        d = filedialog.askdirectory(parent=self.root, initialdir=start, title=self.t("rec_dir_title"))
        if d:
            self.rec_dir = Path(d)
            self.rec_tip.text = d

    def epg_events(self):
        return self.stream.ts.events() if self.stream and self.stream.ts else []

    def epg_now_next(self):
        if self.stream and not self.stream.ts: return self.t("epg_na")
        ev, now, rows = self.epg_events(), time.time(), []
        if ev and ev[0][0] <= now: rows.append(("now", ev.pop(0)))
        if ev: rows.append(("next", ev[0]))
        return [(f"{self.t(k)}:", e[2]) for k, e in rows] or self.t("epg_wait")

    def set_epg(self, data):
        if data == self._epg_shown: return
        self._epg_shown = data
        for w in (*self.epg_k, *self.epg_v, self.epg_msg): w.grid_remove()
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
        w = self.epg_win = tk.Toplevel(self.root)
        w.title(self.t("epg_btn"))
        w.geometry("640x520")
        w.minsize(600, 480)

        st = ttk.Style()
        st.configure("Epg.Treeview", background=self.bg_grey, fieldbackground=self.bg_grey,
                     foreground=TXT_DARK, font=self.f_norm)
        st.configure("Epg.Treeview.Heading", font=self.f_bold)
        st.map("Epg.Treeview", background=[("selected", "#4a6984")], foreground=[("selected", "#ffffff")])
        w.configure(bg=self.bg_grey)

        mf = ttk.Frame(w, padding=10)
        mf.pack(fill="both", expand=True)

        t_frame = ttk.Frame(mf)
        t_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("date", "time", "title")
        tree = ttk.Treeview(t_frame, columns=columns, show="headings", selectmode="browse", style="Epg.Treeview")
        
        tree.heading("date", text=self.t("epg_date"))
        tree.heading("time", text=self.t("epg_time"))
        tree.heading("title", text=self.t("epg_title"))

        tree.column("date", width=100, minwidth=80, anchor="w")
        tree.column("time", width=110, minwidth=90, anchor="w")
        tree.column("title", width=380, minwidth=200, anchor="w")

        sb = ttk.Scrollbar(t_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)

        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        d_frame = ttk.LabelFrame(mf, text=self.t("epg_desc"), padding=8)
        d_frame.pack(fill="both", expand=False)

        desc_txt = tk.Text(d_frame, wrap="word", font=self.f_norm, height=6,
                           bg=self.bg_grey, fg=TXT_DARK, relief="flat", highlightthickness=0, state="disabled")
        d_sb = ttk.Scrollbar(d_frame, orient="vertical", command=desc_txt.yview)
        desc_txt.configure(yscrollcommand=d_sb.set)

        desc_txt.pack(side="left", fill="both", expand=True)
        d_sb.pack(side="right", fill="y")

        events_map = {}

        def on_select(event):
            selected = tree.selection()
            if selected:
                item_id = selected[0]
                desc = events_map.get(item_id, "")
                desc_txt.configure(state="normal")
                desc_txt.delete("1.0", "end")
                desc_txt.insert("end", desc if desc else self.t("epg_nodesc"))
                desc_txt.configure(state="disabled")

        tree.bind("<<TreeviewSelect>>", on_select)

        days_dict = {
            "Română": ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"],
            "English": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "Italiano": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        }

        def refresh():
            if not w.winfo_exists(): return
            current_sel = tree.selection()
            selected_vals = (tree.item(current_sel[0], "values") if current_sel else None)

            for item in tree.get_children(): tree.delete(item)
            events_map.clear()

            w.title(f"{self.t('epg_btn')} - {self.cur or ''}")
            evs = self.epg_events()
            for s, e, name, desc in evs:
                dt = datetime.fromtimestamp(s)
                day_name = days_dict.get(self.lang, days_dict["Română"])[dt.weekday()]
                date_str = f"{day_name} {dt.day:02d}.{dt.month:02d}"
                time_str = f"{hm(s)}–{hm(e)}"
                item_id = tree.insert("", "end", values=(date_str, time_str, name))
                events_map[item_id] = desc

            children = tree.get_children()
            if children:
                if selected_vals:
                    match_item = next((child for child in children if tree.item(child, "values") == selected_vals), children[0])
                    tree.selection_set(match_item)
                    tree.see(match_item)
                else:
                    tree.selection_set(children[0])
                    tree.see(children[0])
            else:
                desc_txt.configure(state="normal")
                desc_txt.delete("1.0", "end")
                wait_text = self.t("epg_wait" if self.stream else "epg_none")
                desc_txt.insert("end", wait_text)
                desc_txt.configure(state="disabled")

            w.after(3000, refresh)

        refresh()

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
        if not ad or not ch or ad in self.warmed or self.warm_busy or self.scan_active: return
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
        if systems is None: cable = terr = False
        elif systems:
            cable = any(s.startswith("DVBC") for s in systems)
            terr = any(s.startswith(("DVBT", "ISDBT")) for s in systems)
        else: cable = terr = True
        if self.scan_active: cable = terr = False
        self.set_enabled(self.scan_c_btn, cable)
        self.set_enabled(self.scan_t_btn, terr)
        self.set_enabled(self.ca_btn, bool(self.adapter_items) and not self.scan_active)

    def reload(self):
        self.tv_channels, self.radio_channels, self.locked = load_channels()
        self._radio_names = {c for c, _ in self.radio_channels}
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
            if has_prev: spacer("space_top_tv")
            title("tv_title")
            spacer("space_bot_tv")
            for c in norm_tv: channel(c, f"  📺  {c.strip()}{lock(c)}", "tv")
            has_prev = True

        if all_rad:
            if has_prev: spacer("space_top_rad")
            title("radio_title")
            spacer("space_bot_rad")
            for c in norm_rad: channel(c, f"  📻  {c.strip()}{lock(c)}", "radio")

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
        for _ in range(100):
            if not self.warm_busy: break
            time.sleep(0.2)

    def _detect(self, ad):
        detect_services(ad, lambda: self.scan_cancelled, lambda pr: setattr(self, "scan_proc", pr))

    def start_scan(self, mode):
        if self.scan_active: return
        if not shutil.which("dvbv5-scan"):
            messagebox.showerror("Eroare", "Lipsește pachetul dvb-tools.", parent=self.root)
            return
        nums = re.findall(r"\d+", self.adapter_data())
        if len(nums) < 2:
            messagebox.showerror(self.t("scan_err"), self.t("no_tuner"), parent=self.root)
            return
        a, f = nums[:2]
        init = CONF_DIR / f"auto-scan-{mode[-1]}.conf"
        init.write_text(scan_init(mode, self.adapter_systems()))
        out = CONF_DIR / "channels.scan.tmp"
        out.unlink(missing_ok=True)
        self._scan_begin()

        ad = self.adapter_data()
        warm_init = CONF_DIR / "warm-scan.conf"
        warm_init.write_text(init.read_text().split("\n\n")[0] + "\n\n")

        def has_channels():
            try: return out.exists() and bool(re.search(r"^\[", out.read_text(errors="replace"), re.M))
            except OSError: return False

        def work():
            self._wait_warm()
            if ad not in self.warmed and not self.scan_cancelled:
                warm_up(ad, init=warm_init, maxwait=4.0)
                self.warmed.add(ad)
            warm_init.unlink(missing_ok=True)
            cmd = ["dvbv5-scan", "-a", a, "-f", f, "-o", str(out), str(init)]
            rc, err = -1, ""
            for attempt in range(3):
                if self.scan_cancelled: break
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=get_clean_env())
                self.scan_proc = p
                if self.scan_cancelled: p.terminate()
                tail = deque(maxlen=20)
                for l in p.stdout:
                    line = l.strip()
                    if line: tail.append(line)
                rc = p.wait()
                if self.scan_cancelled: break
                time.sleep(0.6)
                if rc == 0 and has_channels(): break
                err = "\n".join(tail) or f"Cod ieșire {rc}"
                if attempt < 2: time.sleep(2.0)
            cancelled = self.scan_cancelled
            ok = (not cancelled) and rc == 0 and has_channels()
            if ok:
                os.replace(out, CHANNELS)
                SERVICES.unlink(missing_ok=True)
                try: self._detect(ad)
                except Exception: pass
            else: out.unlink(missing_ok=True)
            self.events.put(lambda: self.on_scan(ok, err, cancelled))
        threading.Thread(target=work, daemon=True).start()

    def start_ca_detect(self):
        ad = self.adapter_data()
        if self.scan_active or not ad or not (self.tv_channels or self.radio_channels): return
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
        if cancelled: return
        self.reload()
        if err: messagebox.showwarning(self.t("scan_err"), err, parent=self.root)
        else: messagebox.showinfo(TITLE, f"{self.t('ca_done')} {len(self.locked)}", parent=self.root)

    def cancel_scan(self):
        if not self.scan_active: return
        self.scan_cancelled = True
        self.set_enabled(self.cancel_btn, False)
        p = self.scan_proc
        if p and p.poll() is None:
            p.terminate()
            def _kill():
                if p.poll() is None: p.kill()
            t = threading.Timer(2.0, _kill)
            t.daemon = True
            t.start()

    def on_scan(self, ok, err, cancelled=False):
        self._scan_end()
        if cancelled: return
        if ok:
            self.reload()
            total_count = len(self.tv_channels) + len(self.radio_channels)
            messagebox.showinfo(TITLE, f"{self.t('scan_done')} {total_count}", parent=self.root)
        else: messagebox.showwarning(self.t("scan_err"), err, parent=self.root)

    def tune(self, name, retry=0, wait=0):
        if self.warm_busy and wait < 60:
            self.set_loading(name)
            self.root.after(200, lambda: self.tune(name, retry, wait + 1))
            return
        self.stop()
        self.set_loading(name)
        time.sleep(0.15)
        self._retry = retry
        try:
            if not self.adapter_data(): raise RuntimeError(self.t("no_tuner"))
            all_dict = {c: sid for c, sid in self.tv_channels + self.radio_channels}
            self.stream = Streamer(self.adapter_data(), name, all_dict.get(name, 0),
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
        if self.stream: self.stream.stop()
        self.stream = self.cur = None
        self.loading = False
        self.update_video_msg()

    def _rec_txt(self):
        h, r = divmod(int(time.time() - self.rec_t0), 3600)
        return f"● REC {h}:{r // 60:02d}:{r % 60:02d}"

    def set_recording(self, on):
        if on == self.rec_on or (on and not self.stream): return
        try:
            if on:
                self.rec_dir.mkdir(parents=True, exist_ok=True)
                self.stream.start_rec(self.rec_dir / f"{(self.cur or 'canal').replace('/', '_')}_{datetime.now():%Y%m%d_%H%M%S}.ts")
            elif self.stream: self.stream.stop_rec()
        except OSError as e:
            messagebox.showerror(self.t("rec_dir"), str(e), parent=self.root)
            return
        self.rec_on = on
        if on:
            self.rec_t0 = time.time()
            txt = self._rec_txt()
            self.rec_lbl.configure(text=txt)
            self.stream.set_rec_osd(txt)
            self.rec_lbl.pack(after=self.top, fill="x", pady=(0, 5))
        else:
            self.rec_lbl.pack_forget()
            self._rec_osd_txt = ""
            if self.stream: self.stream.set_rec_osd(None)
        self.rec_btn.configure(text=self.t("rec_on" if on else "rec_off"))
        self.root.after_idle(self.fit_min_height)

    def on_close(self):
        if getattr(self, "_closing", False): return
        self._closing = True
        if self.inhibitor: self.inhibitor.stop()
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
        })
        self.stop()
        self.scan_cancelled = True
        if self.scan_proc: self.scan_proc.kill()
        self.root.destroy()

def single_instance():
    global _LOCK_FH
    _LOCK_FH = open(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "teleops-dvb.lock", "w")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False

if __name__ == "__main__":
    if not single_instance():
        lang = load_settings().get("lang")
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo(TITLE, T["already"][LANGS.index(lang) if lang in LANGS else 0])
        sys.exit(0)
    root = tk.Tk()
    Main(root)
    root.mainloop()

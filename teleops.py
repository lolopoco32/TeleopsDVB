#!/usr/bin/env python3
"""Teleops DVB - Tkinter + mpv + dvbv5-zap, cu EPG și subtitrări DVB (nu doar cele embedded).
Dependențe: python3-tk, mpv (sau io.mpv.Mpv Flatpak), dvb-tools (dvbv5-scan, dvbv5-zap, dvb-fe-tool)
"""
import configparser, fcntl, functools, json, os, queue, re, select, shutil, socket, subprocess, sys, threading, time
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

CONF_DIR.mkdir(parents=True, exist_ok=True)
if not MPV_CONF.exists():
    MPV_CONF.write_text(MPV_CONF_DATA, encoding="utf-8")

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
    "channels_label": ("Canale disponibile:", "Available channels:", "Canali disponibili:"),
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
    "hk_epg_k": ("i", "i", "i"),
    "hk_fav": ("Adaugă / Elimină din Favorite", "Add / Remove Favorites", "Aggiungi / Rimuovi Preferiti"),
    "hk_fav_k": ("CTRL + Click Stânga", "CTRL + Left Click", "CTRL + Clic sinistro"),
    "hk_play": ("Redă canalul", "Play channel", "Riproduci il canale"),
    "hk_play_k": ("Dublu click / Enter", "Double click / Enter", "Doppio clic / Invio"),
    "hk_cfg": ("Ascunde/arată setările", "Hide/show settings", "Nascondi/mostra impostazioni"),
    "hk_cfg_k": ("Click pe titlu", "Click on title", "Clic sul titolo"),
    # Localizare OSD MPV
    "osd_loading": ("Se încarcă EPG...", "Loading EPG...", "Caricamento EPG..."),
    "osd_na": ("Indisponibil", "Unavailable", "Non disponibile"),
    "scrambled": ("Canal codat (criptat): nu poate fi redat fără card/CAM.", "Scrambled (encrypted) channel: it can't be played without a card/CAM.", "Canale criptato: non riproducibile senza card/CAM."),
    "ca_btn": ("🔑 Detectează canalele codate", "🔑 Detect scrambled channels", "🔑 Rileva canali criptati"),
    "ca_done": ("Detecție finalizată! Canale codate:", "Detection finished! Scrambled channels:", "Rilevamento completato! Canali criptati:"),
    "already": ("Teleops DVB rulează deja.", "Teleops DVB is already running.", "Teleops DVB è già in esecuzione."),
    "osd_rem": ("Rămas", "Left", "Rimasti"),
}


def load_settings():
    try: return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception: return {}


def save_settings(d):
    try: SETTINGS.write_text(json.dumps(d), encoding="utf-8")
    except OSError: pass


def get_clean_env():
    """Mediu curățat de variabilele injectate de PyInstaller."""
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


@functools.cache
def zap_all_pids():
    """True dacă dvbv5-zap are -P (tot transponderul): fără el nu există EPG/subtitrări în flux."""
    try:
        r = subprocess.run(["dvbv5-zap", "--help"], capture_output=True, text=True, timeout=5, env=get_clean_env())
        return bool(re.search(r"^\s*-P\b", r.stdout + r.stderr, re.M))
    except (OSError, subprocess.SubprocessError):
        return False


HOTKEYS = (("hk_search", "hk_search_k"), ("hk_epg", "hk_epg_k"), ("hk_fav", "hk_fav_k"),
           ("hk_play", "hk_play_k"), ("hk_cfg", "hk_cfg_k"))

# ---------------------------------------------------------------- MPEG-TS / DVB SI

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
hm = lambda ts: datetime.fromtimestamp(ts).strftime("%H:%M")


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


class Streamer:
    OBSERVED = ("volume-max", "volume", "mute")

    def __init__(self, adapter, channel, sid, props, on_prop, get_lang_func=None):
        self.props, self.on_prop, self.conn = dict(props), on_prop, None
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

        mpv = [*MPV, "--no-terminal", f"--include={MPV_CONF}", f"--input-ipc-server={self.sock}",
               "--sid=auto", "--sub-visibility=yes", f"--volume={props['volume']}",
               f"--mute={'yes' if props['mute'] else 'no'}", f"--title=TV - {channel.strip()}", "-"]
        self.mpv = subprocess.Popen(mpv, stdin=subprocess.PIPE, env=get_clean_env())
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
        
        self.cmd("keybind", "i", "script-message show-info-osd")        # mpv modern
        self.cmd("define-key", "i", "script-message show-info-osd")     # mpv vechi

        def delayed_osd():
            # Așteaptă încărcarea EPG (EIT) înainte de afișare: minim 3 s, apoi verifică la 0,5 s
            # până când emisiunea curentă ȘI cea următoare sunt cunoscute. Dacă nu apar în 12 s,
            # afișează ce există și reîmprospătează OSD-ul când datele ajung (maxim 60 s).
            t0 = time.time()
            time.sleep(3.0 if self.ts else 0.5)
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
                    
                    if e.get("event") == "client-message" and e.get("args") and e["args"][0] == "show-info-osd":
                        self.show_tv_osd()

                    if e.get("event") == "property-change" and e.get("data") is not None:
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

    def start_rec(self, path):
        with self.lock: self.rec = open(path, "wb")

    def stop_rec(self):
        with self.lock:
            if self.rec: self.rec.close(); self.rec = None

    def stop(self):
        self.on_prop = lambda *_: None
        self.stop_rec()
        for p in (self.zap, self.mpv):
            try:
                p.terminate()
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                p.kill()
        subprocess.run(["pkill", "-f", self.sock_name], stderr=subprocess.DEVNULL, env=get_clean_env())
        Path(self.sock).unlink(missing_ok=True)


# ---------------------------------------------------------------- canale / tunere

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


# ---------------------------------------------------------------- interfața

class Main:
    def __init__(self, root):
        self.root, self.settings = root, load_settings()
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

        self.list_items_meta = []
        self.locked, self.warmed, self.warm_busy, self._retry = set(), set(), False, 0

        if ICON_PATH.exists():
            try:
                self._icon = tk.PhotoImage(file=str(ICON_PATH))
                root.iconphoto(True, self._icon)
            except tk.TclError:
                pass

        h, pos = 840, ""
        if m := re.match(r"\d+x(\d+)([+-]\d+)([+-]\d+)", self.settings.get("geometry", "")):
            h, pos = int(m.group(1)), m.group(2) + m.group(3)
        root.geometry(f"320x{h}{pos}")
        root.minsize(320, 400)
        self._min_h = 0
        root.resizable(False, True)

        root.bind("<Key-i>", self.on_key_i)
        root.bind("<Key-I>", self.on_key_i)

        base = tkfont.nametofont("TkDefaultFont")
        self.f_norm, self.f_bold, f_brand = base.copy(), base.copy(), base.copy()
        self.f_norm.configure(size=-13, weight="normal")
        self.f_bold.configure(size=-13, weight="bold")
        f_brand.configure(size=-18, weight="bold")
        self.f_hk, self.f_hkb = base.copy(), base.copy()
        self.f_hk.configure(size=-11, weight="normal")
        self.f_hkb.configure(size=-11, weight="bold")
        
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
        st.configure("TCombobox", font=self.f_norm)

        bg_grey = self.bg_grey = st.lookup("TFrame", "background") or root.cget("bg")

        main = ttk.Frame(root, padding=14)
        main.pack(fill="both", expand=True)
        self.main = main

        # Zona de jos se împachetează prima (side="bottom"): la micșorarea ferestrei pe verticală
        # se strânge doar lista de canale, iar butoanele de sus și de jos rămân mereu vizibile.
        bottom = self.bottom = ttk.Frame(main)
        bottom.pack(side="bottom", fill="x")

        top = ttk.Frame(main)
        top.pack(fill="x", pady=5)
        top.columnconfigure(0, weight=1)
        self.brand = ttk.Label(top, text=TITLE, style="Brand.TLabel", anchor="center", cursor="hand2")
        self.brand.bind("<Button-1>", lambda e: self.toggle_tuner())
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
        self._btn(tc, "cfg_mpv", self.open_mpv_config)
        self.rec_tip = Tip(self._btn(tc, "rec_dir", self.choose_rec_dir), str(self.rec_dir))
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

        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(5, 0))

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

        self.epg_btn = self._btn(bottom, "epg_btn", self.show_epg, pady=(5, 0))
        self.rec_btn = self._btn(bottom, "rec_off", lambda: self.set_recording(not self.rec_on), pady=(5, 0))
        self.stop_btn = self._btn(bottom, "stop_play", self.stop, pady=(5, 0))

        self.apply_translations()
        self._ph_show()
        if not self.settings.get("tuner_visible", True):
            tc.pack_forget()
            hk.pack_forget()
        if not self.settings.get("search_visible", True):
            self.search.pack_forget()
        self.show_volume(self.volume)
        self.show_mute(self.muted)
        self.reload()
        self.update_scan_buttons()
        self.detect_tuners()
        self.root.after(50, lambda: self.chlist.yview_moveto(self.settings.get("scroll_position", 0.0)))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after_idle(self.fit_min_height)
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
        if self.tuner_container.winfo_ismapped():
            self.tuner_container.pack_forget()
            self.hk_frame.pack_forget()
        else:
            self.tuner_container.pack(fill="x", before=self.epg_lbl)
            self.hk_frame.pack(fill="x", pady=(0, 2), before=self.vol_frame)
        self.root.after_idle(self.fit_min_height)

    def fit_min_height(self):
        """Înălțimea minimă = tot ce nu e listă + LIST_MIN_H; astfel nimic din jur nu e tăiat."""
        self.root.update_idletasks()
        need = self.main.winfo_reqheight() - self.list_frame.winfo_reqheight() + LIST_MIN_H
        if need != self._min_h:
            self._min_h = need
            self.root.minsize(320, need)
        if self.root.winfo_ismapped() and self.root.winfo_height() < need:
            self.root.geometry(f"320x{need}")   # lățimea e fixă (resizable(False, True))

    def poll_events(self):
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)

    def on_lang(self, _=None):
        self.lang = self.lang_box.get()
        self.apply_translations()
        self.fill_channels()
        if self.stream:
            self.stream.show_tv_osd()

    def apply_translations(self):
        self.root.title(TITLE)
        for w, key in self.tr:
            w.configure(text=self.t(key))
        self.rec_btn.configure(text=self.t("rec_on" if self.rec_on else "rec_off"))
        self.refresh_tip.text = self.t("refresh_tip")
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
                vol_txt = "Volum" if self.lang == "Română" else ("Volume" if self.lang == "English" else "Volume")
                self.stream.cmd("show-text", f"{vol_txt}: {v}%", 3000)

    def toggle_mute(self, _=None):
        self.show_mute(not self.muted)
        if self.stream:
            self.stream.set_prop("mute", self.muted)
            mute_txt = "Mute"
            state_txt = ("Pornit" if self.muted else "Oprit") if self.lang == "Română" else (("On" if self.muted else "Off") if self.lang == "English" else ("Attivo" if self.muted else "Disattivo"))
            self.stream.cmd("show-text", f"{mute_txt}: {state_txt}", 3000)

    def on_key_i(self, event=None):
        # scurtăturile sunt dezactivate cât timp se scrie în căutare (sau în alt câmp de text)
        w = self.root.focus_get()
        if w is self.search or isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox)):
            return
        if self.stream:
            self.stream.show_tv_osd()

    def on_mpv_prop(self, name, v):
        if name == "volume": self.show_volume(round(v))
        elif name == "mute": self.show_mute(bool(v))
        elif name == "volume-max": self.vol_slider.configure(to=v)

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
        if self.search.winfo_ismapped():
            self.chlist.focus_set()
            self._ph_active = False
            self.search_var.set("")
            self._ph_show()
            self.search.pack_forget()
        else:
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

    def on_list_double(self, e):
        i = self.chlist.nearest(e.y)
        if 0 <= i < len(self.list_items_meta):
            meta = self.list_items_meta[i]
            if meta[0] == "channel":
                self.try_tune(meta[1])

    def try_tune(self, name):
        if name in self.locked:
            messagebox.showinfo(TITLE, self.t("scrambled"), parent=self.root)
        else:
            self.tune(name)

    def on_ctrl_click(self, e):
        i = self.chlist.nearest(e.y)
        if 0 <= i < len(self.list_items_meta):
            meta = self.list_items_meta[i]
            if meta[0] == "channel":
                name = meta[1]
                if name in self.favorites:
                    self.favorites.remove(name)
                else:
                    self.favorites.add(name)
                self.fill_channels()

    def on_list_enter(self, _=None):
        sel = self.chlist.curselection()
        if sel:
            i = sel[0]
            if 0 <= i < len(self.list_items_meta):
                meta = self.list_items_meta[i]
                if meta[0] == "channel":
                    self.try_tune(meta[1])

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
        for b in (self.rec_btn, self.epg_btn, self.stop_btn):
            self.set_enabled(b, on)
        self.brand.configure(text=self.cur.strip() if on and self.cur else TITLE)
        self.set_epg(self.epg_now_next() if on else "")
        if self.rec_on:
            h, r = divmod(int(time.time() - self.rec_t0), 3600)
            self.rec_lbl.configure(text=f"● REC {h}:{r // 60:02d}:{r % 60:02d}")
        self.fit_min_height()

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
        
        date_heading = "Dată" if self.lang == "Română" else ("Date" if self.lang == "English" else "Data")
        time_heading = "Oră" if self.lang == "Română" else ("Time" if self.lang == "English" else "Ora")
        title_heading = "Emisiune / Film" if self.lang == "Română" else ("Show / Movie" if self.lang == "English" else "Programma / Film")
        
        tree.heading("date", text=date_heading)
        tree.heading("time", text=time_heading)
        tree.heading("title", text=title_heading)

        tree.column("date", width=100, minwidth=80, anchor="w")
        tree.column("time", width=110, minwidth=90, anchor="w")
        tree.column("title", width=380, minwidth=200, anchor="w")

        sb = ttk.Scrollbar(t_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)

        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        desc_label_text = "Descriere detaliată" if self.lang == "Română" else ("Detailed description" if self.lang == "English" else "Descrizione dettagliata")
        d_frame = ttk.LabelFrame(mf, text=desc_label_text, padding=8)
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
                no_desc_text = "Fără descriere disponibilă." if self.lang == "Română" else ("No description available." if self.lang == "English" else "Nessuna descrizione disponibile.")
                desc_txt.insert("end", desc if desc else no_desc_text)
                desc_txt.configure(state="disabled")

        tree.bind("<<TreeviewSelect>>", on_select)

        days_dict = {
            "Română": ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"],
            "English": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "Italiano": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        }

        def refresh():
            if not w.winfo_exists():
                return
            current_sel = tree.selection()
            selected_vals = (tree.item(current_sel[0], "values") if current_sel else None)

            for item in tree.get_children():
                tree.delete(item)
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
                wait_text = self.t("epg_wait") if self.stream else ("Niciun program disponibil." if self.lang == "Română" else ("No program available." if self.lang == "English" else "Nessun programma disponibile."))
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

    def adapter_systems(self):
        i = self.adapter.current()
        return tuple(self.adapter_items[i][2]) if self.adapter_items and i >= 0 else ()

    def adapter_data(self):
        i = self.adapter.current()
        return self.adapter_items[i][1] if self.adapter_items and i >= 0 else ""

    def update_scan_buttons(self):
        i = self.adapter.current()
        systems = self.adapter_items[i][2] if self.adapter_items and i >= 0 else None
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

    def start_scan(self, mode):
        if self.scan_active:
            return
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
        out = CONF_DIR / "channels.scan.tmp"   # lista actuală nu e atinsă dacă scanarea e anulată/eșuează
        out.unlink(missing_ok=True)
        self.stop()
        self.scan_active, self.scan_cancelled = True, False
        self.update_scan_buttons()
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_bar.start(15)
        self.set_enabled(self.cancel_btn, True)
        self.cancel_btn.pack(fill="x", pady=(0, 5))

        ad = self.adapter_data()
        warm_init = CONF_DIR / "warm-scan.conf"
        warm_init.write_text(init.read_text().split("\n\n")[0] + "\n\n")

        def has_channels():
            try: return out.exists() and bool(re.search(r"^\[", out.read_text(errors="replace"), re.M))
            except OSError: return False

        def work():
            # 1) \"bâzâit\" al tunerului (doar dacă nu a fost deja făcut) - evită scanarea de două ori
            for _ in range(100):
                if not self.warm_busy: break
                time.sleep(0.2)
            if ad not in self.warmed and not self.scan_cancelled:
                warm_up(ad, init=warm_init, maxwait=4.0)
                self.warmed.add(ad)
            warm_init.unlink(missing_ok=True)
            # 2) scanarea propriu-zisă; reîncearcă singură dacă iese goală/eșuată
            cmd = ["dvbv5-scan", "-a", a, "-f", f, "-o", str(out), str(init)]
            rc, err = -1, ""
            for attempt in range(3):
                if self.scan_cancelled:
                    break
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=get_clean_env())
                self.scan_proc = p
                if self.scan_cancelled:
                    p.terminate()
                tail = deque(maxlen=20)
                for l in p.stdout:
                    line = l.strip()
                    if line:
                        tail.append(line)
                rc = p.wait()
                if self.scan_cancelled:
                    break
                time.sleep(0.6)
                if rc == 0 and has_channels():
                    break
                err = "\n".join(tail) or f"Cod ieșire {rc}"
                if attempt < 2:
                    time.sleep(2.0)
            cancelled = self.scan_cancelled
            ok = (not cancelled) and rc == 0 and has_channels()
            if ok:
                os.replace(out, CHANNELS)
                SERVICES.unlink(missing_ok=True)
                try:   # 3) marchează canalele codate / radio (din SDT)
                    detect_services(ad, lambda: self.scan_cancelled, lambda pr: setattr(self, "scan_proc", pr))
                except Exception:
                    pass
            else:
                out.unlink(missing_ok=True)
            self.events.put(lambda: self.on_scan(ok, err, cancelled))
        threading.Thread(target=work, daemon=True).start()

    def start_ca_detect(self):
        ad = self.adapter_data()
        if self.scan_active or not ad or not (self.tv_channels or self.radio_channels):
            return
        if not zap_all_pids():
            messagebox.showwarning(TITLE, self.t("epg_na"), parent=self.root)
            return
        self.stop()
        self.scan_active, self.scan_cancelled = True, False
        self.update_scan_buttons()
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_bar.start(15)
        self.set_enabled(self.cancel_btn, True)
        self.cancel_btn.pack(fill="x", pady=(0, 5))

        def work():
            for _ in range(100):
                if not self.warm_busy: break
                time.sleep(0.2)
            err = ""
            try: detect_services(ad, lambda: self.scan_cancelled, lambda pr: setattr(self, "scan_proc", pr))
            except Exception as e: err = str(e)
            cancelled = self.scan_cancelled
            self.events.put(lambda: self.on_ca_done(err, cancelled))
        threading.Thread(target=work, daemon=True).start()

    def on_ca_done(self, err, cancelled):
        self.scan_proc = None
        self.scan_active = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.cancel_btn.pack_forget()
        self.update_scan_buttons()
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
        self.scan_proc = None
        self.scan_active = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.cancel_btn.pack_forget()
        self.update_scan_buttons()
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
            self.root.after(200, lambda: self.tune(name, retry, wait + 1))
            return
        self.stop()
        time.sleep(0.15)
        self._retry = retry                    # NU mai tăiem spațiile: numele trebuie să fie exact ca în channels.conf
        try:
            if not self.adapter_data():
                raise RuntimeError(self.t("no_tuner"))
            all_dict = {c: sid for c, sid in self.tv_channels + self.radio_channels}
            self.stream = Streamer(self.adapter_data(), name, all_dict.get(name, 0),
                                   {"volume": self.volume, "mute": self.muted},
                                   lambda k, v: self.events.put(lambda: self.on_mpv_prop(k, v)),
                                   get_lang_func=lambda: self.lang)
            self.cur = self.last_channel = name
            self.select_current()
        except Exception as e:
            messagebox.showerror(self.t("play_err"), str(e), parent=self.root)

    def stop(self):
        self.set_recording(False)
        if self.stream:
            self.stream.stop()
        self.stream = self.cur = None

    def set_recording(self, on):
        if on == self.rec_on or (on and not self.stream):
            return
        try:
            if on:
                self.rec_dir.mkdir(parents=True, exist_ok=True)
                self.stream.start_rec(self.rec_dir / f"{(self.cur or 'canal').replace('/', '_')}_{datetime.now():%Y%m%d_%H%M%S}.ts")
            elif self.stream:
                self.stream.stop_rec()
        except OSError as e:
            messagebox.showerror(self.t("rec_dir"), str(e), parent=self.root)
            return
        self.rec_on = on
        if on:
            self.rec_t0 = time.time()
            self.rec_lbl.configure(text=f"● REC 0:00:00")
            self.rec_lbl.pack(after=self.top, fill="x", pady=(0, 5))
        else:
            self.rec_lbl.pack_forget()
        self.rec_btn.configure(text=self.t("rec_on" if on else "rec_off"))
        self.root.after_idle(self.fit_min_height)

    def on_close(self):
        filtered = not self._ph_active and bool(self.search_var.get())
        save_settings({
            "lang": self.lang,
            "muted": self.muted,
            "volume": self.volume,
            "last_channel": self.cur or self.last_channel,
            "search_visible": bool(self.search.winfo_ismapped()),
            "geometry": self.root.geometry(),
            "adapter": self.adapter_data() or self.settings.get("adapter", ""),
            "tuner_visible": bool(self.tuner_container.winfo_ismapped()),
            "scroll_position": self.settings.get("scroll_position", 0.0) if filtered else self.chlist.yview()[0],
            "rec_dir": str(self.rec_dir),
            "favorites": list(self.favorites),
        })
        self.stop()
        self.scan_cancelled = True
        if self.scan_proc:
            self.scan_proc.kill()
        self.root.destroy()


def single_instance():
    """Doar o instanță: lacăt de fișier (eliberat automat de sistem când procesul se termină)."""
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

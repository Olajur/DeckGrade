import asyncio
import json
import os
import shutil
import struct
import subprocess
from typing import Optional

import decky

LUT_SIZE = 32
ATOM_WIDENESS = "GAMESCOPE_COLOR_SDR_GAMUT_WIDENESS"
ATOM_LOOK_G22 = "GAMESCOPE_COLOR_LOOK_G22"
ATOM_FOCUSED_GFX = "GAMESCOPE_FOCUSED_APP_GFX"
ATOM_FOCUSED_APP = "GAMESCOPE_FOCUSED_APP"
XPROP_TIMEOUT = 5
WATCHDOG_INTERVAL = 5.0
APPLY_DEBOUNCE = 0.15
CANDIDATE_DISPLAYS = (":0", ":1")
APP_STEAM_UI = 769
STATE_CHANGED_EVENT = "deckgrade_state_changed"

FIVE = ("saturation", "contrast", "shadows", "highlights", "vibrance")

DEFAULT_SETTINGS = {
    "enabled": True,
    "saturation": 100,
    "contrast": 100,
    "shadows": 0,
    "highlights": 0,
    "vibrance": 50,
}
NEUTRAL = {key: DEFAULT_SETTINGS[key] for key in FIVE}
BOUNDS = {
    "saturation": (0, 200),
    "contrast": (0, 200),
    "shadows": (-100, 100),
    "highlights": (-100, 100),
    "vibrance": (0, 100),
}


def clamp_value(key: str, value) -> int:
    lo, hi = BOUNDS[key]
    return max(lo, min(hi, int(value)))


def sanitize_profile(raw, fallback) -> dict:
    profile = dict(fallback)
    if isinstance(raw, dict):
        for key in FIVE:
            val = raw.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                profile[key] = clamp_value(key, val)
    return profile


def global_profile(settings: dict) -> dict:
    return {key: settings[key] for key in FIVE}


def resolve_profile(settings: dict, appid) -> tuple:
    if appid is not None:
        games = settings.get("games") or {}
        raw = games.get(appid)
        if isinstance(raw, dict):
            return sanitize_profile(raw, NEUTRAL), "game"
    return global_profile(settings), "global"


def active_appid_from_props(props: dict):
    for key in ("focused_gfx", "focused_app"):
        val = props.get(key)
        if isinstance(val, int) and val != 0 and val != APP_STEAM_UI:
            return str(val)
    return None


def float_to_u32(value: float) -> int:
    return struct.unpack("!I", struct.pack("!f", value))[0]


def u32_to_float(value: int) -> float:
    return struct.unpack("!f", struct.pack("!I", value & 0xFFFFFFFF))[0]


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def tone_shade(value: float, shadows: float, highlights: float) -> float:
    if shadows != 0.0:
        value += shadows * value * (1.0 - value) * (1.0 - value)
    if highlights != 0.0:
        value += highlights * value * value * (1.0 - value)
    return value


def generate_lut(saturation: int, contrast: int, shadows: int, highlights: int) -> str:
    size = LUT_SIZE
    denom = float(size - 1)
    k = contrast / 100.0
    s = saturation / 100.0
    sh = shadows / 100.0
    hi = highlights / 100.0

    m00 = 0.213 + 0.787 * s
    m01 = 0.715 - 0.715 * s
    m02 = 0.072 - 0.072 * s
    m10 = 0.213 - 0.213 * s
    m11 = 0.715 + 0.285 * s
    m12 = 0.072 - 0.072 * s
    m20 = 0.213 - 0.213 * s
    m21 = 0.715 - 0.715 * s
    m22 = 0.072 + 0.928 * s

    lines = ["LUT_3D_SIZE %d" % size]
    for b in range(size):
        vb = b / denom
        for g in range(size):
            vg = g / denom
            for r in range(size):
                vr = r / denom
                cr = clamp01(tone_shade(clamp01((vr - 0.5) * k + 0.5), sh, hi))
                cg = clamp01(tone_shade(clamp01((vg - 0.5) * k + 0.5), sh, hi))
                cb = clamp01(tone_shade(clamp01((vb - 0.5) * k + 0.5), sh, hi))
                outr = clamp01(m00 * cr + m01 * cg + m02 * cb)
                outg = clamp01(m10 * cr + m11 * cg + m12 * cb)
                outb = clamp01(m20 * cr + m21 * cg + m22 * cb)
                lines.append("%.6f %.6f %.6f" % (outr, outg, outb))
    return "\n".join(lines) + "\n"


class Plugin:
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self.xprop = shutil.which("xprop")
        self.settings_file = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "deckgrade.json")
        self.lut_path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "deckgrade_g22.cube")
        self.settings = self._load_settings()
        self._display: Optional[str] = None
        self._detect_warned = False
        self._lut_signature = None
        self._active_app = None
        self._profile_active = "global"
        self._apply_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        decky.logger.info(
            "DeckGrade starting (saturation=%d contrast=%d shadows=%d highlights=%d vibrance=%d enabled=%s)"
            % (
                self.settings["saturation"],
                self.settings["contrast"],
                self.settings["shadows"],
                self.settings["highlights"],
                self.settings["vibrance"],
                self.settings["enabled"],
            )
        )
        if self.xprop is None:
            decky.logger.error("xprop not found, display control unavailable")
        self._detect_display(verbose=True)
        await self._apply()
        self._watchdog_task = self.loop.create_task(self._watchdog())

    async def _unload(self):
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self._apply_task is not None:
            self._apply_task.cancel()
            self._apply_task = None
        decky.logger.info("DeckGrade unloaded")

    async def _uninstall(self):
        await self._unload()
        try:
            disp = self._detect_display()
            if disp is not None and self.xprop is not None:
                if self._xprop_get_string(disp, ATOM_LOOK_G22) is not None:
                    self._xprop_remove(disp, ATOM_LOOK_G22)
                self._xprop_set_cardinal(disp, ATOM_WIDENESS, DEFAULT_SETTINGS["vibrance"] / 100.0)
        except Exception as e:
            decky.logger.error("Failed to reset display state: %s" % e)
        for path in (self.settings_file, self.lut_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                decky.logger.error("Failed to remove %s: %s" % (path, e))
        decky.logger.info("DeckGrade uninstalled")

    async def get_state(self) -> dict:
        disp = self._detect_display(verbose=True)
        appid = None
        profile_name = "global"
        if disp is not None:
            props = self._read_root(disp)
            if props is not None:
                appid = active_appid_from_props(props)
                _, profile_name = resolve_profile(self.settings, appid)
        return {
            "enabled": self.settings["enabled"],
            "global": global_profile(self.settings),
            "games": self.settings.get("games", {}),
            "app": appid,
            "active_profile": profile_name,
            "gamescope": disp is not None,
            "display": disp,
            "xprop": self.xprop is not None,
        }

    async def set_enabled(self, enabled: bool):
        self.settings["enabled"] = bool(enabled)
        self._save_settings()
        self._schedule_apply()

    async def set_value(self, target: str, key: str, value: int):
        if key not in BOUNDS:
            raise ValueError("Unknown setting: %s" % key)
        profile = self._resolve_target(target)
        profile[key] = clamp_value(key, value)
        self._save_settings()
        self._schedule_apply()

    async def reset_profile(self, target: str):
        profile = self._resolve_target(target)
        for key in FIVE:
            profile[key] = NEUTRAL[key]
        if target == "global":
            self.settings["enabled"] = True
        self._save_settings()
        self._schedule_apply()

    async def copy_global_to(self, target: str):
        if target != "current":
            raise ValueError("copy_global_to requires target 'current'")
        appid = self._detect_active_app()
        if appid is None:
            raise ValueError("No game is running; nothing to target")
        self.settings.setdefault("games", {})[appid] = global_profile(self.settings)
        self._save_settings()
        self._schedule_apply()

    def _resolve_target(self, target: str) -> dict:
        if target == "global":
            return self.settings
        if target != "current":
            raise ValueError("Unknown profile target: %s" % target)
        appid = self._detect_active_app()
        if appid is None:
            raise ValueError("No game is running; nothing to target")
        games = self.settings.setdefault("games", {})
        if appid not in games:
            games[appid] = global_profile(self.settings)
        return games[appid]

    def _load_settings(self) -> dict:
        settings = {"enabled": DEFAULT_SETTINGS["enabled"]}
        settings.update(NEUTRAL)
        settings["games"] = {}
        try:
            with open(self.settings_file, "r") as f:
                loaded = json.load(f)
        except (OSError, ValueError):
            return settings
        if not isinstance(loaded, dict):
            return settings
        if "enabled" in loaded:
            settings["enabled"] = bool(loaded["enabled"])
        for key in FIVE:
            val = loaded.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                settings[key] = clamp_value(key, val)
        games = loaded.get("games")
        if isinstance(games, dict):
            for appid, raw in games.items():
                if isinstance(raw, dict):
                    settings["games"][str(appid)] = sanitize_profile(raw, NEUTRAL)
        return settings

    def _save_settings(self):
        try:
            os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
            tmp = self.settings_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.settings, f, indent=2)
            os.replace(tmp, self.settings_file)
        except OSError as e:
            decky.logger.error("Failed to save settings: %s" % e)

    def _schedule_apply(self):
        if self._apply_task is not None and not self._apply_task.done():
            self._apply_task.cancel()
        self._apply_task = self.loop.create_task(self._debounced_apply())

    async def _debounced_apply(self):
        await asyncio.sleep(APPLY_DEBOUNCE)
        await self._apply(force=True)

    async def _watchdog(self):
        last_identity = None
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            try:
                await self._apply()
            except Exception as e:
                decky.logger.error("Watchdog apply failed: %s" % e)
            identity = (self._active_app, self._profile_active)
            if identity != last_identity:
                last_identity = identity
                try:
                    await decky.emit(STATE_CHANGED_EVENT, await self.get_state())
                except Exception as e:
                    decky.logger.error("Watchdog state emit failed: %s" % e)

    def _read_root(self, display: str):
        out = self._xprop([], display)
        if out is None:
            return None
        return {
            "gamescope": "GAMESCOPE_" in out,
            "wideness": self._parse_cardinal(out, ATOM_WIDENESS),
            "look_path": self._parse_string(out, ATOM_LOOK_G22),
            "focused_gfx": self._parse_int(out, ATOM_FOCUSED_GFX),
            "focused_app": self._parse_int(out, ATOM_FOCUSED_APP),
        }

    @staticmethod
    def _dump_value(out: str, atom: str):
        for line in out.splitlines():
            if line.lstrip().startswith(atom + "("):
                return line.split("=", 1)[1].strip()
        return None

    def _parse_int(self, out: str, atom: str):
        value = self._dump_value(out, atom)
        if value is None:
            return None
        try:
            return int(value.split()[0])
        except (ValueError, IndexError):
            return None

    def _parse_cardinal(self, out: str, atom: str):
        value = self._parse_int(out, atom)
        if value is None:
            return None
        return u32_to_float(value)

    def _parse_string(self, out: str, atom: str):
        value = self._dump_value(out, atom)
        if value is None:
            return None
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        return value

    def _probe_display(self, display: str):
        props = self._read_root(display)
        if props is None:
            return False, "xprop failed (see log)"
        if props["gamescope"]:
            return True, "ok"
        return False, "X server reachable but no GAMESCOPE_ root properties"

    def _detect_active_app(self):
        disp = self._detect_display()
        if disp is None:
            return None
        props = self._read_root(disp)
        if props is None:
            return None
        return active_appid_from_props(props)

    def _detect_display(self, verbose: bool = False) -> Optional[str]:
        if self.xprop is None:
            return None
        candidates = []
        env_display = os.environ.get("DISPLAY")
        if env_display:
            candidates.append(env_display)
        for d in CANDIDATE_DISPLAYS:
            if d not in candidates:
                candidates.append(d)
        if self._display is not None:
            ok, detail = self._probe_display(self._display)
            if ok:
                return self._display
            if verbose:
                decky.logger.info("Cached display %s no longer detected (%s), re-scanning" % (self._display, detail))
            self._display = None
        details = []
        for d in candidates:
            ok, detail = self._probe_display(d)
            if ok:
                self._display = d
                self._detect_warned = False
                decky.logger.info("Detected gamescope on display %s" % d)
                return d
            details.append("%s %s" % (d, detail))
        if verbose or not self._detect_warned:
            decky.logger.info("Gamescope not detected (%s); will keep retrying" % "; ".join(details))
            self._detect_warned = True
        return None

    def _xprop(self, args, display: str) -> Optional[str]:
        try:
            completed = subprocess.run(
                [self.xprop, "-display", display, "-root"] + args,
                capture_output=True,
                timeout=XPROP_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            decky.logger.error("xprop %s on %s failed: %s" % (args, display, e))
            return None
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            decky.logger.error("xprop %s on %s failed (rc %d): %s" % (args, display, completed.returncode, stderr))
            return None
        return completed.stdout.decode("utf-8", errors="replace")

    def _xprop_query(self, display: str, atom: str) -> Optional[str]:
        out = self._xprop([atom], display)
        if out is None or "=" not in out:
            return None
        return out.split("=", 1)[1].strip()

    def _xprop_get_string(self, display: str, atom: str) -> Optional[str]:
        value = self._xprop_query(display, atom)
        if value is None:
            return None
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        return value

    def _xprop_set_cardinal(self, display: str, atom: str, value: float):
        self._xprop(["-f", atom, "32c", "-set", atom, str(float_to_u32(value))], display)

    def _xprop_set_string(self, display: str, atom: str, value: str):
        self._xprop(["-f", atom, "8s", "-set", atom, value], display)

    def _xprop_remove(self, display: str, atom: str):
        self._xprop(["-remove", atom], display)

    async def _apply(self, force: bool = False):
        if self.xprop is None:
            return
        s = self.settings
        if not s["enabled"] and not force:
            return
        disp = self._detect_display()
        if disp is None:
            return
        props = self._read_root(disp)
        if props is None:
            return
        enabled = s["enabled"]
        appid = active_appid_from_props(props)
        profile, profile_name = resolve_profile(s, appid)
        self._active_app = appid
        self._profile_active = profile_name

        wideness = (profile["vibrance"] if enabled else DEFAULT_SETTINGS["vibrance"]) / 100.0
        current = props["wideness"]
        if current is None or abs(current - wideness) > 0.001:
            self._xprop_set_cardinal(disp, ATOM_WIDENESS, wideness)
            decky.logger.info("Set %s to %.2f (%s profile)" % (ATOM_WIDENESS, wideness, profile_name))

        needs_lut = enabled and (
            profile["saturation"] != 100
            or profile["contrast"] != 100
            or profile["shadows"] != 0
            or profile["highlights"] != 0
        )
        if needs_lut:
            signature = (profile["saturation"], profile["contrast"], profile["shadows"], profile["highlights"])
            lut_changed = False
            if self._lut_signature != signature or not os.path.isfile(self.lut_path):
                content = await self.loop.run_in_executor(
                    None,
                    generate_lut,
                    profile["saturation"],
                    profile["contrast"],
                    profile["shadows"],
                    profile["highlights"],
                )
                os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
                with open(self.lut_path, "w") as f:
                    f.write(content)
                self._lut_signature = signature
                lut_changed = True
                decky.logger.info(
                    "Generated %s LUT (saturation=%d contrast=%d shadows=%d highlights=%d) at %s"
                    % (
                        profile_name,
                        profile["saturation"],
                        profile["contrast"],
                        profile["shadows"],
                        profile["highlights"],
                        self.lut_path,
                    )
                )
            # Re-set the property whenever the file changed so gamescope reloads it,
            # even though the path itself is unchanged.
            if lut_changed or props["look_path"] != self.lut_path:
                self._xprop_set_string(disp, ATOM_LOOK_G22, self.lut_path)
                decky.logger.info("Set %s to %s" % (ATOM_LOOK_G22, self.lut_path))
        else:
            if props["look_path"] is not None:
                self._xprop_remove(disp, ATOM_LOOK_G22)
                decky.logger.info("Removed %s" % ATOM_LOOK_G22)

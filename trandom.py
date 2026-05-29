#!/usr/bin/env python3
"""
True Random Number Generator - multi-source entropy harvester.

Collects entropy from:
  - System CSPRNG (os.urandom)
  - CPU jitter (instruction timing variations)
  - Disk access timing fluctuations
  - Memory allocation addresses
  - Thread scheduler race conditions
  - Network timing jitter
  - Performance counters
  - Mouse movements (optional: --mouse)
  - Keyboard presses (optional: --keyboard)
  - Hardware sensors (optional: --sensors)

Usage examples:
  python trandom.py --int
  python trandom.py --bytes 32
  python trandom.py --float -n 5
  python trandom.py --mouse --int --duration 10
  python trandom.py --mouse --bytes 64 --verbose
  python trandom.py --choice apple banana cherry
  echo -e "foo\\nbar\\nbaz" | python trandom.py --shuffle
"""

VERSION = 0.2
AUTHOR = "igor.brzezek@gmail.com"
GITHUB = "https://github.com/IgorBrzezek/trandom"

import argparse
import hashlib
import os
import struct
import sys
import threading
import time
from typing import Optional, List, Tuple


# ======================================================================
#  UTILITY: progress bar
# ======================================================================

def _progress_bar(current: int, total: int, prefix: str = "", bar_len: int = 30, file=sys.stdout):
    """Print an in-place progress bar with percentage and #-symbols."""
    if total == 0:
        return
    pct = current / total
    filled = int(bar_len * pct)
    bar = "#" * filled + "." * (bar_len - filled)
    file.write(f"\r{prefix}  {pct*100:5.1f}% [{bar}]  {current}/{total}")
    file.flush()
    if current >= total:
        file.write("\n")
        file.flush()


# ======================================================================
#  UTILITY: hex viewer
# ======================================================================

def _hex_view(data: bytes, width: int = 16) -> str:
    """Format bytes as a classic hex viewer table (like hexdump -C)."""
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        # offset
        line = f"{offset:08x}  "
        # hex bytes — two groups of 8, separated by double space
        hex_groups = []
        for g in range(0, width, 8):
            group = chunk[g:g + 8]
            hex_groups.append(" ".join(f"{b:02x}" for b in group))
            # pad incomplete last group
            pad = 8 - len(group)
            if pad:
                hex_groups[-1] += "   " * pad
        line += "  ".join(hex_groups)
        # ASCII representation
        ascii_chars = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        line += f"  |{ascii_chars}|"
        lines.append(line)
    return "\n".join(lines)


# ======================================================================
#  TRUE RANDOM GENERATOR CORE
# ======================================================================

class TrueRandom:
    """Multi-source true random number generator."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._mouse_data: List[bytes] = []
        self._keyboard_data: List[bytes] = []
        self._sensor_data: List[bytes] = []

    # -- entropy sources ------------------------------------------------

    def _jitter_entropy(self, samples: int = 30) -> bytes:
        """CPU instruction timing jitter."""
        deltas = []
        for _ in range(samples):
            t1 = time.perf_counter_ns()
            _ = [i ** 2 for i in range(30)]
            t2 = time.perf_counter_ns()
            deltas.append(t2 - t1)
        raw = struct.pack(f"{samples}Q", *deltas)
        return hashlib.sha256(raw).digest()

    def _disk_timing_entropy(self, path: Optional[str] = None, samples: int = 5) -> bytes:
        """Disk access timing fluctuations."""
        if path is None:
            path = os.path.abspath(__file__)
        deltas = []
        try:
            size = min(os.path.getsize(path), 65536)
            for _ in range(samples):
                t1 = time.perf_counter_ns()
                with open(path, "rb") as f:
                    f.read(size)
                t2 = time.perf_counter_ns()
                deltas.append(t2 - t1)
        except Exception:
            deltas = [time.perf_counter_ns() for _ in range(samples)]
        raw = struct.pack(f"{len(deltas)}Q", *deltas)
        return hashlib.sha256(raw).digest()

    def _system_entropy(self) -> bytes:
        """OS entropy pool (driver noise, interrupts, mouse, keyboard, …)."""
        return os.urandom(64)

    def _memory_entropy(self) -> bytes:
        """Object allocation address entropy."""
        addrs = b"".join(str(id(object())).encode() for _ in range(200))
        return hashlib.sha256(addrs).digest()

    def _thread_entropy(self, threads: int = 4, iters: int = 100) -> bytes:
        """Thread scheduler race-condition entropy."""
        results = []
        lock = threading.Lock()

        def worker():
            local = 0
            for i in range(iters):
                t1 = time.perf_counter_ns()
                _ = i * i * i
                t2 = time.perf_counter_ns()
                local ^= t2 - t1
            with lock:
                results.append(local)

        ts = [threading.Thread(target=worker) for _ in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        raw = struct.pack(f"{threads}Q", *results)
        return hashlib.sha256(raw).digest()

    def _network_entropy(self) -> bytes:
        """Network timing jitter."""
        try:
            import socket
            t1 = time.perf_counter_ns()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.001)
            sock.sendto(b"", ("8.8.8.8", 53))
            sock.close()
            t2 = time.perf_counter_ns()
        except Exception:
            t1 = time.perf_counter_ns()
            t2 = time.perf_counter_ns()
        return hashlib.sha256(struct.pack("QQ", t1, t2)).digest()

    def _counter_entropy(self) -> bytes:
        """Performance counter timing."""
        raw = b"".join(struct.pack("Q", time.perf_counter_ns()) for _ in range(50))
        return hashlib.sha256(raw).digest()

    # -- mouse entropy --------------------------------------------------

    def _feed_mouse_entropy(self, data: bytes):
        """Feed a mouse-sample chunk into the pool."""
        self._mouse_data.append(data)

    def _collect_mouse_entropy_windows(self, duration: Optional[float], samples_target: int) -> int:
        """
        Collect mouse-position entropy via Windows API (ctypes).
        duration=None means no time limit.
        Returns the number of samples actually collected.
        """
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        GetCursorPos = user32.GetCursorPos

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        collected = 0
        prev_x, prev_y = None, None
        deadline = (time.time() + duration) if duration is not None else None

        _progress_bar(0, samples_target, "Mouse entropy")

        while (deadline is None or time.time() < deadline) and collected < samples_target:
            pt = POINT()
            GetCursorPos(ctypes.byref(pt))
            now_ns = time.perf_counter_ns()
            if prev_x is not None and (pt.x != prev_x or pt.y != prev_y):
                dx = pt.x - prev_x
                dy = pt.y - prev_y
                chunk = struct.pack("iiQq", dx, dy, now_ns, id(object()))
                self._feed_mouse_entropy(hashlib.sha256(chunk).digest())
                collected += 1
                if collected % 5 == 0 or collected == samples_target:
                    _progress_bar(collected, samples_target, "Mouse entropy")
            prev_x, prev_y = pt.x, pt.y
            time.sleep(0.010)

        return collected

    def _collect_mouse_entropy_pynput(self, duration: Optional[float], samples_target: int) -> int:
        """Collect mouse entropy via pynput (cross-platform fallback)."""
        from pynput import mouse

        collected = 0
        prev_x, prev_y = None, None
        start = time.time()
        deadline = (start + duration) if duration is not None else None

        _progress_bar(0, samples_target, "Mouse entropy")

        def on_move(x, y):
            nonlocal collected, prev_x, prev_y
            if (deadline is not None and time.time() > deadline) or collected >= samples_target:
                return False
            now_ns = time.perf_counter_ns()
            if prev_x is not None and (x != prev_x or y != prev_y):
                dx = x - prev_x
                dy = y - prev_y
                chunk = struct.pack("iiQq", dx, dy, now_ns, id(object()))
                self._feed_mouse_entropy(hashlib.sha256(chunk).digest())
                collected += 1
                if collected % 5 == 0 or collected == samples_target:
                    _progress_bar(collected, samples_target, "Mouse entropy")
            prev_x, prev_y = x, y

        sleep_sec = samples_target * 0.05
        if duration is not None:
            sleep_sec = min(sleep_sec, duration)
        listener = mouse.Listener(on_move=on_move)
        listener.start()
        time.sleep(sleep_sec)
        listener.stop()
        return collected

    def collect_mouse_entropy(self, duration: Optional[float], samples: int = 250):
        """Collect mouse-movement entropy.  duration=None = no time limit."""
        if self.verbose:
            dur_str = f"{duration}s" if duration is not None else "unlimited"
            print(f"[*] Collecting mouse entropy (timeout: {dur_str}, target: {samples} samples)")
            print("    Move your mouse around now!\n")

        try:
            # Windows: use ctypes (no dependencies)
            if os.name == "nt":
                count = self._collect_mouse_entropy_windows(duration, samples)
            else:
                count = self._collect_mouse_entropy_pynput(duration, samples)
        except Exception as exc:
            print(f"\n[!] Mouse entropy collection failed: {exc}")
            print("    On Linux/macOS install:  pip install pynput")
            return

        if self.verbose:
            print(f"[+] Collected {count} mouse entropy samples")

    # -- keyboard entropy -----------------------------------------------

    def _feed_keyboard_entropy(self, data: bytes):
        self._keyboard_data.append(data)

    def _collect_keyboard_entropy_windows(self, duration: Optional[float], samples_target: int) -> int:
        """Collect keyboard-press entropy via msvcrt (Windows built-in)."""
        import msvcrt
        collected = 0
        deadline = (time.time() + duration) if duration is not None else None

        if self.verbose:
            print("    Press keys (any keys) on the keyboard now!\n")

        _progress_bar(0, samples_target, "Keyboard entropy")

        while (deadline is None or time.time() < deadline) and collected < samples_target:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                now_ns = time.perf_counter_ns()
                chunk = struct.pack("BQq", key[0] if isinstance(key, bytes) else ord(key), now_ns, id(object()))
                self._feed_keyboard_entropy(hashlib.sha256(chunk).digest())
                collected += 1
                if collected % 5 == 0 or collected == samples_target:
                    _progress_bar(collected, samples_target, "Keyboard entropy")
            time.sleep(0.010)

        return collected

    def _collect_keyboard_entropy_poll(self, duration: Optional[float], samples_target: int) -> int:
        """Collect keyboard-press entropy via stdin polling (Unix fallback)."""
        import select
        collected = 0
        deadline = (time.time() + duration) if duration is not None else None

        if self.verbose:
            print("    Press keys (any keys) on the keyboard now!\n")

        _progress_bar(0, samples_target, "Keyboard entropy")

        while (deadline is None or time.time() < deadline) and collected < samples_target:
            if select.select([sys.stdin], [], [], 0.01)[0]:
                key = sys.stdin.read(1)
                now_ns = time.perf_counter_ns()
                chunk = struct.pack("BQq", ord(key) if key else 0, now_ns, id(object()))
                self._feed_keyboard_entropy(hashlib.sha256(chunk).digest())
                collected += 1
                if collected % 5 == 0 or collected == samples_target:
                    _progress_bar(collected, samples_target, "Keyboard entropy")

        return collected

    def collect_keyboard_entropy(self, duration: Optional[float], samples: int = 250):
        """Collect keyboard-press entropy.  duration=None = no time limit."""
        if self.verbose:
            dur_str = f"{duration}s" if duration is not None else "unlimited"
            print(f"[*] Collecting keyboard entropy (timeout: {dur_str}, target: {samples} samples)")

        try:
            if os.name == "nt":
                count = self._collect_keyboard_entropy_windows(duration, samples)
            else:
                count = self._collect_keyboard_entropy_poll(duration, samples)
        except Exception as exc:
            print(f"\n[!] Keyboard entropy collection failed: {exc}")
            return

        if self.verbose:
            print(f"[+] Collected {count} keyboard entropy samples")

    # -- sensor entropy -------------------------------------------------

    def _feed_sensor_entropy(self, data: bytes):
        self._sensor_data.append(data)

    def _sensor_entropy_psutil(self) -> bytes:
        """Read hardware sensor data via psutil (CPU temp, fans, battery)."""
        raw = b""
        try:
            import psutil
            temps = psutil.sensors_temperatures()
            if temps:
                raw += str(temps).encode()
            fans = psutil.sensors_fans()
            if fans:
                raw += str(fans).encode()
            batt = psutil.sensors_battery()
            if batt:
                raw += str(batt).encode()
        except (ImportError, AttributeError, Exception):
            pass
        return raw

    def _sensor_entropy_wmic(self) -> bytes:
        """Read hardware sensor data via wmic (Windows fallback)."""
        import subprocess
        raw = b""
        for cmd in [
            ["wmic", "PATH", "Win32_Fan", "get", "DesiredSpeed"],
            ["wmic", "/namespace:\\\\root\\wmi", "PATH",
             "MSAcpi_ThermalZoneTemperature", "get", "CurrentTemperature"],
            ["wmic", "PATH", "Win32_VoltageProbe", "get", "Reading"],
        ]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                raw += r.stdout.encode()
            except Exception:
                pass
        return raw

    def _collect_sensor_entropy(self, samples: int = 5):
        """Collect hardware sensor readings (CPU temp, fans, voltages, battery)."""
        if self.verbose:
            print("[*] Reading hardware sensors (CPU temp, fans, voltages, battery)")

        for i in range(samples):
            raw = b""
            t1 = time.perf_counter_ns()

            _progress_bar(i + 1, samples, "Sensor entropy")

            # try psutil first (cross-platform), fall back to wmic on Windows
            chunk = self._sensor_entropy_psutil()
            if not chunk and os.name == "nt":
                chunk = self._sensor_entropy_wmic()

            if chunk:
                raw += chunk
            else:
                self._feed_sensor_entropy(os.urandom(8))
                if self.verbose and i == 0:
                    print("    [!] No hardware sensors found, using timing jitter instead")

            # timing of the sensor query itself is also entropy
            t2 = time.perf_counter_ns()
            raw += struct.pack("QQi", t1, t2, i)
            raw += str(id(object())).encode()
            self._feed_sensor_entropy(hashlib.sha256(raw).digest())

        if self.verbose:
            print(f"[+] Collected {samples} sensor entropy samples")

    def collect_sensor_entropy(self, samples: int = 5):
        """Public wrapper to collect hardware sensor entropy."""
        self._collect_sensor_entropy(samples=samples)

    # -- gather & mix ---------------------------------------------------

    def _standard_sources(self) -> List[bytes]:
        return [
            self._jitter_entropy(),
            self._disk_timing_entropy(),
            self._system_entropy(),
            self._memory_entropy(),
            self._thread_entropy(),
            self._network_entropy(),
            self._counter_entropy(),
        ]

    def gather(self, use_mouse: bool = False, use_keyboard: bool = False, use_sensors: bool = False) -> bytes:
        """Collect from all available sources and return 32 entropy bytes."""
        sources = self._standard_sources()
        if use_mouse and self._mouse_data:
            sources.extend(self._mouse_data)
            self._mouse_data.clear()
        if use_keyboard and self._keyboard_data:
            sources.extend(self._keyboard_data)
            self._keyboard_data.clear()
        if use_sensors and self._sensor_data:
            sources.extend(self._sensor_data)
            self._sensor_data.clear()

        combined = b"".join(sources)
        mixed = hashlib.sha3_512(combined).digest()
        return hashlib.sha256(mixed).digest()

    def random_bytes(self, n: int = 32, use_mouse: bool = False, use_keyboard: bool = False, use_sensors: bool = False) -> bytes:
        """Produce n truly random bytes."""
        result = bytearray()
        while len(result) < n:
            result.extend(self.gather(use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors))
        return bytes(result[:n])

    def random_int(self, min_val: int = 0, max_val: int = 2 ** 32 - 1, use_mouse: bool = False, use_keyboard: bool = False, use_sensors: bool = False) -> int:
        """Random integer in [min_val, max_val]."""
        if min_val > max_val:
            min_val, max_val = max_val, min_val
        span = max_val - min_val + 1
        nbytes = (span.bit_length() + 7) // 8
        while True:
            r = int.from_bytes(self.random_bytes(nbytes, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors), "big")
            if r < span:
                return min_val + r

    def random_float(self, use_mouse: bool = False, use_keyboard: bool = False, use_sensors: bool = False) -> float:
        """Random float in [0.0, 1.0)."""
        return self.random_int(0, 2 ** 53 - 1, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors) / 2 ** 53

    def random_choice(self, seq, use_mouse: bool = False, use_keyboard: bool = False, use_sensors: bool = False):
        """Random element from a non-empty sequence."""
        return seq[self.random_int(0, len(seq) - 1, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)]

    def shuffle(self, seq, use_mouse: bool = False, use_keyboard: bool = False, use_sensors: bool = False):
        """Fisher-Yates shuffle in-place."""
        for i in range(len(seq) - 1, 0, -1):
            j = self.random_int(0, i, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)
            seq[i], seq[j] = seq[j], seq[i]

    def list_sources(self) -> List[str]:
        return [
            "System CSPRNG (os.urandom / CryptGenRandom)",
            "CPU jitter (instruction timing fluctuations)",
            "Disk access timing",
            "Memory allocation addresses",
            "Thread scheduler (race conditions)",
            "Network timing jitter (UDP send)",
            "Performance counters",
            "Mouse movements (--mouse)",
            "Keyboard presses (--keyboard)",
            "Hardware sensors (--sensors: CPU temp, fans, voltages, battery)",
        ]

    def probe_sources(self):
        """
        Probe and print which entropy sources are actually available
        on this system, including detected hardware sensors.
        """
        print("Entropy source probe\n")

        # -- always-active sources --
        print("  Always active (7):")
        print(f"    [OK] System CSPRNG (os.urandom)")
        print(f"    [OK] CPU jitter (instruction timing)")
        print(f"    [OK] Disk access timing")
        print(f"    [OK] Memory allocation addresses")
        print(f"    [OK] Thread scheduler (race conditions)")
        print(f"    [OK] Network timing jitter")
        print(f"    [OK] Performance counters")

        # -- mouse --
        mouse_avail = False
        if os.name == "nt":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                mouse_avail = hasattr(user32, "GetCursorPos")
            except Exception:
                pass
        else:
            try:
                from pynput import mouse
                mouse_avail = True
            except ImportError:
                pass
        if mouse_avail:
            print(f"  Optional --mouse:")
            print(f"    [OK] Mouse movements (--mouse)  [supported on this platform]")
        else:
            print(f"  Optional --mouse:")
            print(f"    [!] Mouse movements (--mouse)  [install pynput on Linux/macOS]")

        # -- keyboard --
        print(f"  Optional --keyboard:")
        print(f"    [OK] Keyboard presses (--keyboard)  [supported on this platform]")

        # -- sensors --
        print(f"  Optional --sensors:")
        psutil_temps = psutil_fans = psutil_batt = None
        try:
            import psutil
            psutil_temps = psutil.sensors_temperatures()
            psutil_fans = psutil.sensors_fans()
            psutil_batt = psutil.sensors_battery()
        except ImportError:
            print(f"    [..] psutil: not installed (pip install psutil for sensor support)")
        except Exception as e:
            print(f"    [..] psutil: {e}")

        if psutil_temps:
            for name, entries in psutil_temps.items():
                print(f"    [OK] psutil temperature '{name}': {len(entries)} sensor(s)")
                for e in entries:
                    print(f"         {e.current}{'C' if hasattr(e, 'current') else ''}")
        if psutil_fans:
            for name, entries in psutil_fans.items():
                print(f"    [OK] psutil fan '{name}': {len(entries)} sensor(s)")
        if psutil_batt:
            print(f"    [OK] psutil battery: {psutil_batt.percent}% {'plugged in' if psutil_batt.power_plugged else 'on battery'}")

        if not any([psutil_temps, psutil_fans, psutil_batt]) and os.name == "nt":
            import subprocess
            for label, cmd in [
                ("Fan speed (Win32_Fan)", ["wmic", "PATH", "Win32_Fan", "get", "DesiredSpeed"]),
                ("CPU temp (MSAcpi_ThermalZone)", ["wmic", "/namespace:\\\\root\\wmi", "PATH", "MSAcpi_ThermalZoneTemperature", "get", "CurrentTemperature"]),
                ("Voltage (Win32_VoltageProbe)", ["wmic", "PATH", "Win32_VoltageProbe", "get", "Reading"]),
            ]:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                    out = r.stdout.strip()
                    if out and len(out.splitlines()) > 1:
                        print(f"    [OK] wmic {label}: {len(out.splitlines())-1} reading(s)")
                        for line in out.splitlines()[1:3]:
                            print(f"         {line.strip()}")
                    else:
                        print(f"    [..] wmic {label}: no data")
                except FileNotFoundError:
                    print(f"    [..] wmic: not available")
                    break
                except Exception as e:
                    print(f"    [!] wmic {label}: {e}")

        elif not any([psutil_temps, psutil_fans, psutil_batt]):
            print(f"    [..] No hardware sensors detected")

        print()
        print("  All sources are mixed via SHA3-512 -> SHA-256.")


# ======================================================================
#  CLI
# ======================================================================

class _HelpAction(argparse.Action):
    """Custom action: -h prints short help, --help prints comprehensive help."""
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        if option_string == "-h":
            print("usage: python trandom.py [-h | --help] [options]\n")
            print("  -h            show this short help")
            print("  --help        show comprehensive help with examples")
            print("  --mouse       collect mouse-movement entropy")
            print("  --keyboard    collect keyboard-press entropy (mutually exclusive with --mouse)")
            print("  --sensors     collect hardware sensor entropy (CPU temp, fans, voltages)")
            print("  --int         generate a random integer")
            print("  --float       generate a random float")
            print("  --bytes N     generate N random bytes (hex output)")
            print("  --hex [N]     display N random bytes in hex viewer format (default 256)")
            print("  -n N          generate N values (default 1)")
            print("  --min N       minimum value for --int (default 0)")
            print("  --max N       maximum value for --int (default 2^32-1)")
            print("  --choice ...  pick a random item from given args")
            print("  --shuffle     shuffle lines from stdin or args")
            print("  --duration S  safety timeout (optional; no limit if omitted)")
            print("  --samples N   target mouse samples (default 250)")
            print("  --output F    write result to file instead of stdout")
            print("  --list-sources, --probe  probe and show all available entropy sources")
            print("  -v, --verbose  verbose output (shows generation progress)")
            print("  --pb, --progressbar  show progress bar during value generation")
            print("  (without --pb: a single 'Generating data - wait...' message is shown)")
            print("\n  See --help for full documentation.")
            print(f"  v{VERSION} | {AUTHOR} | {GITHUB}")
            parser.exit()

        # --help: long help
        print(
            f"""True Random Number Generator  -  multi-source entropy harvester

USAGE
    python trandom.py [OPTIONS]

GENERATION MODES (mutually exclusive, default: --int):
    --int             Generate a random integer (default).
    --float           Generate a random float in [0.0, 1.0).
    --bytes N         Generate N random bytes, output as hex string.
    --hex [N]         Display N random bytes in a formatted hex viewer
                      (default 256).  Shows offset, hex bytes, and ASCII
                      representation — similar to hexdump -C.
    --choice A B...   Pick a random element from the given arguments.
    --shuffle         Read lines from stdin (or positional args),
                      shuffle them and print to stdout.

OUTPUT OPTIONS:
    -n N              Generate N values (default 1).
    --min N           Minimum value (for --int, default 0).
    --max N           Maximum value (for --int, default 2^32-1).
    --output FILE, -o FILE   Write output to FILE instead of stdout.

MOUSE ENTROPY:
    --mouse           Enable mouse-movement entropy collection.
                      On Windows uses Win32 API (no deps).
                      On Linux/macOS requires:  pip install pynput
    --duration SEC    Optional safety timeout.  If omitted, collects
                      exactly --samples samples with no time limit.
    --samples N       Target number of mouse samples (default 250).

KEYBOARD ENTROPY:
    --keyboard        Enable keyboard-press entropy collection.
                      Mutually exclusive with --mouse.
                      On Windows uses msvcrt (no deps).
                      On Unix uses polled stdin (no deps).
    --duration SEC    Optional safety timeout.  If omitted, collects
                      exactly --samples samples with no time limit.
    --samples N       Target number of keyboard samples (default 250).

SENSOR ENTROPY:
    --sensors         Enable hardware sensor entropy collection.
                      Reads CPU temperature, fan speeds, voltages, and
                      battery status via psutil (cross-platform) or
                      wmic (Windows fallback).  If no sensors are found,
                      timing jitter of the read attempt is used instead.

VERBOSITY:
    -v, --verbose     Print detailed information about entropy sources
                      and collection / generation progress.
    --pb, --progressbar
                      Show a live progress bar (### %) during value
                      generation (e.g. when generating 10000 integers).
                      Without this flag, a single "Generating data -
                      wait..." message is displayed once instead.
    --list-sources, --probe
                      Probe and show all available entropy sources with
                      detected sensors and platform capabilities, then exit.

HELP:
    -h                This short help.
    --help            This comprehensive help.

ENTROPY SOURCES
  Always active:
    1. System CSPRNG - os.urandom() (kernel entropy from drivers,
       interrupts, mouse, keyboard timings, etc.)
    2. CPU jitter - nanosecond-scale variations in instruction timing
    3. Disk timing - fluctuations in file read latency
    4. Memory addresses - ASLR / heap allocator entropy
    5. Thread scheduler - race-condition ordering between threads
    6. Network timing - jitter in UDP packet send latency
    7. Performance counters - high-resolution timer variations

  Optional (--mouse):
    8. Mouse movements - cursor position deltas + timestamps

  Optional (--keyboard):
    9. Keyboard presses - key codes + press timestamps

  Optional (--sensors):
    10. Hardware sensors - CPU temperature, fan speeds, voltages,
        battery status (via psutil / wmic)

    All sources are mixed via SHA3-512 -> SHA-256.

EXAMPLES
    python trandom.py --int
        Generate a single random integer [0, 2^32-1].

    python trandom.py --int --min 1 --max 100 -n 5
        Generate 5 random integers in [1, 100].

    python trandom.py --float -n 3
        Generate 3 random floats.

    python trandom.py --bytes 32
        Generate 32 random bytes (256 bits) as hex.

    python trandom.py --mouse --int --duration 10
        Collect mouse entropy for 10 seconds, then output an integer.

    python trandom.py --keyboard --int
        Collect keyboard-press entropy, then output an integer.

    python trandom.py --sensors --int
        Collect hardware sensor entropy, then output an integer.

    python trandom.py --mouse --sensors --bytes 64 -v
        Combine mouse + sensor entropy, verbose output.

    python trandom.py --choice apple banana cherry
        Randomly pick one of: apple, banana, cherry.

    echo -e "alpha\\nbeta\\ngamma" | python trandom.py --shuffle
        Shuffle lines from stdin.

    python trandom.py --hex
        Display 256 random bytes in hex viewer format.
    python trandom.py --hex 64 --mouse --verbose
        Collect mouse entropy, then display 64 bytes in hex viewer.

    python trandom.py --list-sources
        Probe and show all available entropy sources with detected sensors.
    python trandom.py --probe
        Same as --list-sources.

COMPARISON WITH BUILT-INS
    Python's random module uses Mersenne Twister (PRNG).
    Python's secrets module uses os.urandom (CSPRNG).
    This tool adds multiple physical entropy sources on top of
    os.urandom, making it suitable for security-sensitive
    applications where additional entropy is desired.

    For most purposes, os.urandom() / secrets is sufficient.
    This tool is intended for demonstration and educational use.

    v{VERSION} | {AUTHOR} | {GITHUB}
"""
        )
        parser.exit()


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("-h", action=_HelpAction, help="short help")
    parser.add_argument("--help", action=_HelpAction, help="comprehensive help")

    parser.add_argument("--mouse", action="store_true", help="collect mouse-movement entropy")
    parser.add_argument("--keyboard", action="store_true", help="collect keyboard-press entropy (mutually exclusive with --mouse)")
    parser.add_argument("--sensors", action="store_true", help="collect hardware sensor entropy (CPU temp, fans, voltages)")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    parser.add_argument("--pb", "--progressbar", action="store_true", dest="progressbar", help="show progress bar during value generation")

    parser.add_argument("--int", action="store_true", dest="gen_int", help="generate random integer")
    parser.add_argument("--float", action="store_true", dest="gen_float", help="generate random float")
    parser.add_argument("--bytes", type=int, default=None, metavar="N", help="generate N random bytes (hex)")
    parser.add_argument("--hex", nargs="?", type=int, const=256, default=None, metavar="N", help="display N random bytes in hex viewer format (default 256)")
    parser.add_argument("--choice", nargs="*", default=None, help="pick random item from arguments")
    parser.add_argument("--shuffle", nargs="*", default=None, help="shuffle items")

    parser.add_argument("-n", "--number", type=int, default=1, help="number of values to generate")
    parser.add_argument("--min", type=int, default=0, help="minimum value for --int")
    parser.add_argument("--max", type=int, default=2 ** 32 - 1, help="maximum value for --int")
    parser.add_argument("--duration", type=float, default=None, help="safety timeout in seconds; if omitted, collects exactly --samples samples with no time limit")
    parser.add_argument("--samples", type=int, default=250, help="mouse target samples")
    parser.add_argument("--output", "-o", type=str, default=None, help="output file")
    parser.add_argument("--list-sources", "--probe", action="store_true", dest="list_sources", help="probe and show all available entropy sources with detected sensors, then exit")

    parsed = parser.parse_args(argv)
    return parsed


def main(argv: Optional[List[str]] = None):
    args = _parse_args(argv)

    rng = TrueRandom(verbose=args.verbose)

    # --list-sources / --probe
    if args.list_sources:
        rng.probe_sources()
        return

    # input collection: --mouse and --keyboard are mutually exclusive
    if args.mouse and args.keyboard:
        print("error: --mouse and --keyboard are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if args.mouse:
        rng.collect_mouse_entropy(duration=args.duration, samples=args.samples)
        use_mouse = True
        use_keyboard = False
    elif args.keyboard:
        rng.collect_keyboard_entropy(duration=args.duration, samples=args.samples)
        use_keyboard = True
        use_mouse = False
    else:
        use_mouse = False
        use_keyboard = False

    # sensor collection
    if args.sensors:
        rng.collect_sensor_entropy()
        use_sensors = True
    else:
        use_sensors = False

    # determine mode
    mode_int = args.gen_int
    mode_float = args.gen_float
    if args.bytes is not None and args.bytes <= 0:
        print("error: --bytes requires a positive integer", file=sys.stderr)
        sys.exit(1)
    mode_bytes = args.bytes is not None and args.bytes > 0
    if args.hex is not None and args.hex <= 0:
        print("error: --hex requires a positive integer", file=sys.stderr)
        sys.exit(1)
    mode_hex = args.hex is not None
    mode_choice = args.choice is not None
    mode_shuffle = args.shuffle is not None

    # default mode
    if not (mode_int or mode_float or mode_bytes or mode_hex or mode_choice or mode_shuffle):
        mode_int = True

    exclusive = [mode_int, mode_float, mode_bytes, mode_hex, mode_choice, mode_shuffle]
    if sum(exclusive) > 1:
        print("error: use only one mode: --int, --float, --bytes, --hex, --choice, or --shuffle", file=sys.stderr)
        sys.exit(1)

    # open output
    out = open(args.output, "w") if args.output else sys.stdout

    n = args.number

    if n > 1 and (mode_int or mode_float) and not args.progressbar:
        print("Generating data - wait...", file=sys.stderr)

    try:
        if mode_int:
            for i in range(n):
                val = rng.random_int(args.min, args.max, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)
                out.write(str(val) + "\n")
                if args.progressbar and n > 1:
                    _progress_bar(i + 1, n, "Generating integers", file=sys.stderr)
                elif args.verbose and (n == 1 or (i + 1) % 10 == 0 or i == n - 1):
                    print(f"[*] Generated {i+1}/{n} integers", file=sys.stderr)

        elif mode_float:
            for i in range(n):
                val = rng.random_float(use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)
                out.write(f"{val:.15f}\n")
                if args.progressbar and n > 1:
                    _progress_bar(i + 1, n, "Generating floats", file=sys.stderr)

        elif mode_bytes:
            data = rng.random_bytes(args.bytes, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)
            out.write(data.hex() + "\n")

        elif mode_hex:
            data = rng.random_bytes(args.hex, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)
            out.write(_hex_view(data) + "\n")

        elif mode_choice:
            items = args.choice
            if not items:
                print("error: --choice requires at least one argument", file=sys.stderr)
                sys.exit(1)
            pick = rng.random_choice(items, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)
            out.write(pick + "\n")

        elif mode_shuffle:
            items = args.shuffle
            if not items:
                # read from stdin
                items = [line.rstrip("\n") for line in sys.stdin if line.strip()]
            if not items:
                print("error: --shuffle needs items (args or stdin)", file=sys.stderr)
                sys.exit(1)
            rng.shuffle(items, use_mouse=use_mouse, use_keyboard=use_keyboard, use_sensors=use_sensors)
            for item in items:
                out.write(item + "\n")

    finally:
        if out is not sys.stdout:
            out.close()


if __name__ == "__main__":
    main()

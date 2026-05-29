# True Random Number Generator

**trandom.py** is a Python-based true random number generator that harvests entropy from multiple hardware and system sources. Unlike pseudorandom generators (Mersenne Twister, etc.), it combines unpredictable physical noise from CPU timing jitter, disk access fluctuations, thread scheduling race conditions, network timing, memory allocation addresses, system CSPRNG, and (optionally) mouse movements, keyboard presses, and hardware sensors.

All collected entropy is mixed through SHA3-512 and then SHA-256 to produce uniformly distributed random output.

**Version:** 0.1
**Author:** igor.brzezek@gmail.com
**Repository:** https://github.com/IgorBrzezek/trandom

---

## Features

- 7 always-active entropy sources (no configuration needed)
- Optional mouse-movement entropy (`--mouse`)
- Optional keyboard-press entropy (`--keyboard`) — mutually exclusive with `--mouse`
- Optional hardware sensor entropy (`--sensors`) — CPU temperature, fan speeds, voltages, battery
- Probe mode to detect which entropy sources are available on your system (`--list-sources` / `--probe`)
- Generate random integers, floats, byte sequences, or pick/shuffle from lists
- Output to file or stdout
- Verbose mode for detailed progress information
- Live progress bar during mouse, keyboard, and sensor entropy collection
- No required external dependencies on Windows

---

## Requirements

### Windows (no external dependencies)
All features except hardware sensors work without installing any additional packages. Mouse tracking uses the Win32 API via `ctypes` (built-in). Keyboard tracking uses `msvcrt` (built-in).

### Linux / macOS
- Mouse entropy (`--mouse`) requires: `pip install pynput`
- Keyboard entropy (`--keyboard`) uses `select` on stdin (built-in, no extra deps)
- Sensor entropy (`--sensors`) requires: `pip install psutil` (or falls back to other methods)

### Optional packages
- `psutil` — hardware sensor readings (CPU temperature, fans, battery) on all platforms
- `pynput` — mouse tracking on Linux/macOS

---

## Installation

```bash
# Download trandom.py
# No installation needed — it is a single-file script.

# Optional: install extras for full functionality
pip install psutil      # hardware sensor support
pip install pynput      # mouse tracking on Linux/macOS
```

---

## Usage

```
python trandom.py [OPTIONS]
```

### Generation Modes (mutually exclusive, default: `--int`)

| Option | Description |
|---|---|---|
| `--int` | Generate a random integer |
| `--float` | Generate a random float in [0.0, 1.0) |
| `--bytes N` | Generate N random bytes (N must be ≥ 1), output as hex string |
| `--hex [N]` | Display N random bytes in a formatted hex viewer (default 256). Shows offset, hex bytes, and ASCII representation — like hexdump -C. |
| `--choice A B ...` | Pick a random element from the given arguments |
| `--shuffle` | Read lines from stdin (or positional args), shuffle and print |

### Output Options

| Option | Description |
|---|---|
| `-n N`, `--number N` | Number of values to generate (default 1) |
| `--min N` | Minimum value for `--int` (default 0) |
| `--max N` | Maximum value for `--int` (default 2^32-1) |
| `-o FILE`, `--output FILE` | Write output to FILE instead of stdout |

### Entropy Source Options

| Option | Description |
|---|---|
| `--mouse` | Collect mouse-movement entropy (Windows: Win32 API; Linux/macOS: pynput) |
| `--keyboard` | Collect keyboard-press entropy (Windows: msvcrt; Unix: stdin poll). Mutually exclusive with `--mouse`. |
| `--sensors` | Collect hardware sensor entropy (psutil / wmic fallback) |
| `--duration SEC` | Optional safety timeout for mouse/keyboard collection. Omit for no time limit. |
| `--samples N` | Target number of mouse/keyboard samples (default 250) |

### Information Options

| Option | Description |
|---|---|
| `--list-sources`, `--probe` | Probe and show all available entropy sources with detected sensors, then exit |
| `-v`, `--verbose` | Show detailed information about entropy collection progress |

### Help

| Option | Description |
|---|---|
| `-h` | Short help |
| `--help` | Comprehensive help with examples |

---

## Entropy Sources

### Always Active (7 sources, no flags required)

1. **System CSPRNG** — `os.urandom()` reads from the operating system's cryptographically secure random pool, which gathers entropy from hardware interrupts, device drivers, disk timings, mouse movements, keyboard timings, and other system events.

2. **CPU Jitter** — Measures nanosecond-scale variations in instruction execution time. Each call computes `time.perf_counter_ns()` before and after a small computation (`[i**2 for i in range(30)]`); the unpredictable timing differences caused by CPU pipeline state, cache misses, and power management are captured as entropy.

3. **Disk Timing** — Reads a portion of the script file and measures the elapsed time with nanosecond precision. Variations in file read latency caused by disk caching, controller state, and mechanical (or wear-leveling) delays provide entropy.

4. **Memory Addresses** — Allocates 200 Python objects in rapid succession and records their memory addresses (`id()`). Differences in heap allocator behavior and ASLR randomization produce entropy.

5. **Thread Scheduler** — Launches 4 threads that each perform timing measurements with a shared accumulator. The non-deterministic interleaving of thread execution by the OS scheduler introduces race-condition entropy.

6. **Network Timing** — Sends a single UDP packet to 8.8.8.8:53 and measures the timing. Even if the send fails, the timing of the system call itself has jitter. The precise wall-clock time of the attempt is recorded.

7. **Performance Counters** — Collects 50 high-resolution timer readings (`time.perf_counter_ns()`) in sequence. The quantum-level variations between successive counter reads are captured.

### Optional Sources

8. **Mouse Movements** (`--mouse`) — Polls the cursor position every 10 ms and records deltas (dx, dy) along with high-resolution timestamps whenever the cursor moves. On Windows this uses the Win32 `GetCursorPos` API via `ctypes`. On Linux/macOS it requires the `pynput` package.

9. **Keyboard Presses** (`--keyboard`) — Polls for key presses every 10 ms and records the key code along with a high-resolution timestamp for each press. On Windows this uses `msvcrt.kbhit()` / `msvcrt.getch()`. On Unix it uses `select.select()` on stdin. Mutually exclusive with `--mouse`.

10. **Hardware Sensors** (`--sensors`) — Reads CPU temperature, fan speeds, voltages, and battery status. First attempts `psutil.sensors_temperatures()`, `psutil.sensors_fans()`, and `psutil.sensors_battery()`. If psutil is unavailable or returns no data on Windows, falls back to calling `wmic` for Win32_Fan, MSAcpi_ThermalZoneTemperature, and Win32_VoltageProbe. When no sensors are detected, timing jitter of the read attempt is used instead.

### Mixing

All collected entropy (from always-active sources plus any optional sources) is concatenated and processed through:

1. **SHA3-512** — first mixing pass (produces 64 bytes)
2. **SHA-256** — second mixing pass (produces final 32 bytes)

This cascading hash construction ensures that any single bit of entropy from any source influences every bit of the output.

---

## Examples

```bash
# Generate a single random integer (default)
python trandom.py

# Generate a random integer in a range
python trandom.py --int --min 1 --max 100

# Generate 5 random integers
python trandom.py --int -n 5

# Generate 3 random floats
python trandom.py --float -n 3

# Generate 32 random bytes (256 bits) as hex
python trandom.py --bytes 32

# Generate 512 random bytes with verbose output
python trandom.py --bytes 512 -v

# Collect mouse entropy for 10 seconds, then output an integer
python trandom.py --mouse --int --duration 10

# Collect 200 mouse movement samples, then output 64 bytes
python trandom.py --mouse --samples 200 --bytes 64

# Collect keyboard-press entropy, no time limit
python trandom.py --keyboard --int

# Collect keyboard entropy with a 30-second safety timeout
python trandom.py --keyboard --int --duration 30

# Combine keyboard + sensor entropy
python trandom.py --keyboard --sensors --bytes 64 -v

# Combine mouse + sensor entropy, verbose
python trandom.py --mouse --sensors --bytes 64 -v

# Random choice from arguments
python trandom.py --choice apple banana cherry date

# Shuffle items from arguments
python trandom.py --shuffle one two three four five

# Shuffle lines from stdin
echo -e "alpha\nbeta\ngamma" | python trandom.py --shuffle

# Display 256 random bytes in hex viewer format
python trandom.py --hex

# Display 64 random bytes in hex viewer (with mouse entropy)
python trandom.py --hex 64 --mouse --verbose

# Write output to a file
python trandom.py --bytes 32 -o random.hex

# Probe available entropy sources on this system
python trandom.py --list-sources
python trandom.py --probe
```

---

## Comparison with Python Built-in Modules

| Module | Type | Entropy Source | Suitable For |
|---|---|---|---|
| `random` | PRNG | Mersenne Twister (deterministic) | Simulations, games, testing |
| `secrets` | CSPRNG | `os.urandom()` (system entropy) | Security tokens, passwords |
| `os.urandom` | CSPRNG | Kernel entropy pool | Cryptography |
| **trandom.py** | **Multi-source TRNG** | **7+ physical sources mixed via SHA3-512+SHA256** | **Demonstration, education, multi-source entropy** |

**Important:** For most real-world cryptographic applications, `os.urandom()` and the `secrets` module are sufficient. This tool is primarily intended for demonstration, educational, and experimental purposes where combining multiple independent entropy sources is desired.

---

## How It Works

### Entropy Collection Flow

1. **Initialize** — The `TrueRandom` class is instantiated. Data buffers for mouse, keyboard, and sensor entropy are prepared.

2. **Optional Collection** (if requested):
   - Mouse/keyboard collection polls at 10 ms intervals, recording movement events or key presses with nanosecond-precision timestamps and a progress bar.
   - Sensor collection reads hardware sensors 5 times, each reading separated by timing jitter from the query itself.

3. **Gather** — On each call to `gather()`:
   - All 7 always-active sources are sampled fresh.
   - If mouse/keyboard/sensor data was pre-collected, it is mixed in.
   - All data is concatenated, hashed with SHA3-512, then hashed with SHA-256.
   - The resulting 32 bytes are returned.

4. **Output Generation** — For `--int`, rejection sampling is used to produce uniformly distributed integers in any range. For `--float`, a 53-bit integer is divided by 2^53 to produce a value in [0.0, 1.0). For `--bytes`, raw hash output is returned directly.

### Entropy Quality Notes

- All physical sources (jitter, disk timing, etc.) are sampled fresh on every `gather()` call, ensuring that repeated calls do not produce identical data.
- The SHA3-512 + SHA-256 cascade provides strong diffusion and prevents any single source from dominating the output.
- Mouse and keyboard entropy include `id(object())` in each sample, adding memory-layout jitter to every event.
- Sensor entropy includes the timing of the sensor query itself (`t1`, `t2`) as an additional jitter source.
- When no hardware sensors are available, `os.urandom(8)` is substituted so the data pipeline remains active.

---

## Technical Details

### Files

| File | Description |
|---|---|
| `trandom.py` | The main script (single file, zero-install) |
| `README_trandom.md` | This documentation |

### Class Structure

- **`TrueRandom`** — Main class implementing all entropy collection and mixing.
  - `_standard_sources()` — Returns fresh entropy from all 7 always-active sources.
  - `gather()` — Combines standard sources with optional collected data and returns 32 bytes.
  - `random_bytes(n)` — Returns `n` random bytes.
  - `random_int(min, max)` — Returns a random integer in `[min, max]`.
  - `random_float()` — Returns a random float in `[0.0, 1.0)`.
  - `random_choice(seq)` — Returns a random element from a sequence.
  - `shuffle(seq)` — Fisher-Yates shuffle in-place.
  - `probe_sources()` — Detects and prints available platform entropy sources.
  - `collect_mouse_entropy()` / `collect_keyboard_entropy()` / `collect_sensor_entropy()` — Public collection methods.

### CLI

- `_HelpAction` — Custom argparse action implementing `-h` (short) and `--help` (comprehensive).
- `_parse_args()` — Argument parsing with mutual exclusion between `--mouse` and `--keyboard`.
- `main()` — Entry point coordinating collection and generation.

---

## License

This project is provided for educational and demonstration purposes.

---

## Author

- **Author:** igor.brzezek@gmail.com
- **GitHub:** https://github.com/IgorBrzezek/trandom

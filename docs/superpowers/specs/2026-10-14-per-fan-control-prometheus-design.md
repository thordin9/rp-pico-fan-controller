# Per-fan PWM control + Prometheus exporter

> **Historical.** This spec was written before Basic Auth, the BMP280 sensors, the OLED, the pressure loop, and sensor-fault handling. The fan pin map (GP15–GP18 PWM, GP14–GP11 tach, 25 kHz, 10 kΩ tach pull-ups to 3V3) is still the wiring. Current behaviour is the [README](../../../README.md), [how it works](../../how-it-works.md), and the [API reference](../../api.md).

**Date:** 2026-10-14  
**Status:** Superseded. Kept as the implementation record for the first per-fan firmware.  
**Hardware:** Raspberry Pi Pico W, up to four 4-pin 12 V PWM fans

## Goal

Replace the shared-PWM design with **individual fan PWM control** (thermal auto or per-fan manual override from the web UI), and expose a **Prometheus-compatible `/metrics`** endpoint alongside the existing status page.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| PWM wiring | Per-fan PWM (rewire; no shared tee) |
| Override model | Per-fan manual; other fans stay on thermal curve |
| Web UI | Full control on `/` (sliders + auto/manual) |
| Metrics | Richer set (temp, duty, RPM, mode/override, uptime, Wi-Fi, HTTP counters) |
| Override persistence | Survive reboot via flash file |
| Fail-safe vs file | Ctrl+C / exception → all fans 100% now; **do not** rewrite overrides file |
| Code layout | Split modules (`fan.py`, `web.py`, `metrics.py`, thin `main.py`) |
| Auth | None (LAN assumption, same as today) |
| Tach pull-ups | **10 kΩ** each tach → Pico 3V3 |

## Pin map

| Fan | PWM GPIO | Tach GPIO |
|-----|----------|-----------|
| 1 | GP15 | GP14 |
| 2 | GP16 | GP13 |
| 3 | GP17 | GP12 |
| 4 | GP18 | GP11 |

- PWM frequency remains **25 kHz** on each channel.
- Tach: rising IRQ, internal pull-up + external **10 kΩ** to 3V3; do not parallel tach lines.
- Power/safety rules unchanged: external 12 V for fans, ~5 V → VSYS for Pico, common GND, never power fans from the Pico.

## Architecture

```text
config.py     Wi-Fi / HTTP_PORT (secrets placeholders)
fan.py        PWM[:4], tach IRQs, thermal curve, modes, RPM, persist I/O, fail-safe
web.py        Non-blocking HTTP: UI, JSON, control POSTs, request counters
metrics.py    Prometheus text exposition from fan + web state
main.py       Boot, Wi-Fi, start HTTP, sample loop + poll_http
overrides.json  Runtime file on Pico flash (not committed to git)
```

### Per-fan runtime state

For each fan `i` in `0..FAN_COUNT-1`:

- `mode`: `"auto"` | `"manual"`
- `duty`: float 0.0–1.0 (applied PWM fraction)
- `rpm`: EMA-smoothed RPM (read-only from tach)

Shared:

- `die_c`: RP2040 die temperature via ADC(4)
- Thermal curve (unchanged defaults): ≤35 °C → 18% floor; linear to 100% at ≥55 °C

**Auto:** each sample sets `duty = temp_to_duty(die_c)` and applies PWM.  
**Manual:** sample loop leaves duty as last set; web may change it.  
**Boot:** spin-up all fans → load `overrides.json` if valid (else all auto) → apply: manual fans use stored duty; auto fans take `temp_to_duty(die)` immediately (stored duty for auto is ignored on load).

### Persistence (`overrides.json`)

Example:

```json
{"fans":[{"mode":"auto","duty":0.0},{"mode":"manual","duty":0.45},{"mode":"auto","duty":0.0},{"mode":"auto","duty":0.0}]}
```

- Write after any successful validated control change (`POST /api/fans/<id>` or `POST /api/fans/<id>/auto`).
- Invalid / missing file → all fans auto (safe default).
- Persist write failure → keep RAM state; log warning (lost only on reboot).
- Fail-safe path does not mutate the file.

## HTTP API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Control UI: live stats, per-fan duty slider, auto/manual |
| `GET` | `/status.json` | JSON: die_c, uptime, wifi/ip/ssid, fans[{id,mode,duty,rpm}] |
| `POST` | `/api/fans/<id>` | JSON body `{"mode":"auto"|"manual","duty":0.0–1.0}`; `id` is 1–4. For `manual`, `duty` required. For `auto`, duty optional/ignored (curve takes over). |
| `POST` | `/api/fans/<id>/auto` | Clear override (mode=auto) for one fan |
| `GET` | `/metrics` | Prometheus text (Content-Type: `text/plain; version=0.0.4`) |

Errors: unknown fan → 404; bad JSON / invalid mode / duty out of range → 400 (no state change, no persist). Non-GET/POST where unsupported → 405.

### UI behaviour

- Inline CSS/JS on `/` (no external assets).
- Poll `/status.json` about every 2 s.
- On slider release or mode toggle: `POST` then refresh from response or next poll.
- Show die temp, per-fan duty %, mode, RPM, Wi-Fi/IP, link to `/metrics` and `/status.json`.

## Prometheus metrics

Locked metric names (`pico_fan_` prefix):

| Metric | Type | Labels / notes |
|--------|------|----------------|
| `pico_fan_die_temp_celsius` | gauge | Die °C |
| `pico_fan_duty_ratio` | gauge | `fan="1"`, `mode="auto\|manual"` — duty 0–1 |
| `pico_fan_rpm` | gauge | `fan="1"` |
| `pico_fan_override` | gauge | `fan="1"` — 1 if manual, else 0 |
| `pico_fan_uptime_seconds` | gauge | |
| `pico_fan_wifi_up` | gauge | 1 if connected, else 0 |
| `pico_fan_http_requests_total` | counter | `path` (coarse: `/`, `/status.json`, `/metrics`, `/api/fans`, `other`), `code` |

No auth; scrape over LAN like the status page.

## Main loop

1. Non-blocking `poll_http` every ~50 ms.
2. Every ~1 s: read die temp; for each fan apply auto curve or keep manual duty; write PWM; snapshot tach pulses → RPM EMA; update shared status used by JSON/metrics.
3. Boot: connect Wi-Fi (optional) → start HTTP → spin-up burst (~60% / 1.5 s all fans) → load overrides → apply per-fan duties → enter loop.
4. Ctrl+C / uncaught exception: fail-safe all PWM 100%, LED on; overrides file unchanged.

## Documentation & deploy

- Update README pin map, wiring diagram (four separate PWM lines; tach pull-ups specified as **10 kΩ**), API table, `/metrics` scrape example, flash list (`main.py`, `fan.py`, `web.py`, `metrics.py`, `config.py`).
- Add `overrides.json` to `.gitignore` if not already covering runtime files on-device only (file lives on Pico; not in repo).
- Keep `config.py` placeholder secrets pattern.

## Out of scope

- Authentication / HTTPS
- Ambient temperature sensors
- Per-fan thermal curves (all auto fans share one die curve)
- Changing fan count beyond four without a follow-up change

## Success criteria

1. Each fan PWM GPIO can run a different duty; tach still reports independent RPM.
2. Web UI can set one fan to manual and leave others on auto; reboot restores those settings from `overrides.json`.
3. `GET /metrics` scrapes cleanly in Prometheus (or `curl` shows valid exposition text).
4. Fail-safe still forces full speed without wiping persisted overrides.
5. README matches the new wiring and flash file set.

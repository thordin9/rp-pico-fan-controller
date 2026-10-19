# HTTP API and metrics

Basic Auth, when `HTTP_USER` and `HTTP_PASSWORD` are both set, applies to every path. A missing or wrong password is **401** with `WWW-Authenticate: Basic realm="pico-fan"`. There is no TLS.

The control page polls `/status.json` every 2 seconds. Its buttons send `Content-Type: application/json`.

## Endpoints

| Method | Path | What it does |
|--------|------|----------------|
| `GET` | `/` and `/index.html` | Control page: die and control temperature, sensor rows, fault badges, per-fan slider, auto and manual |
| `GET` | `/status.json`, `/api`, `/api/status` | JSON status |
| `POST` | `/api/fans/<id>` | Set one fan. `id` is 1–4. Body `{"mode":"manual","duty":0.4}` or `{"mode":"auto"}`. Duty is required for manual and must be from 0.0 to 1.0 |
| `POST` | `/api/fans/<id>/auto` | Same as mode `auto` for that fan. Body `{}` is fine |
| `GET` | `/metrics` | Prometheus text, `text/plain; version=0.0.4` |

`Content-Type` must be `application/json` on both POSTs. Other content types are **400**.

| Code | When |
|------|------|
| 400 | Bad JSON, duty missing, duty outside 0–1, or duty not a number. State does not change |
| 401 | Auth is on and the password does not match |
| 404 | Unknown path, or a fan id that is not 1–4 |
| 405 | Method other than GET or POST |
| 413 | Header or body larger than the limit (1536 byte headers, 512 byte body) |
| 500 | The handler raised. The fan loop keeps running |

```bash
curl -u pico:change-me http://PICO_IP/status.json
curl -u pico:change-me -X POST http://PICO_IP/api/fans/2 \
  -H 'Content-Type: application/json' \
  -d '{"mode":"manual","duty":0.4}'
curl -u pico:change-me -X POST http://PICO_IP/api/fans/2/auto \
  -H 'Content-Type: application/json' -d '{}'
curl -u pico:change-me http://PICO_IP/metrics
```

A successful control POST writes `overrides.json` by renaming a temp file into place and keeping the previous file as `overrides.json.bak`. A corrupt primary file loads the backup. Fail-safe does not rewrite the file.

## Status JSON

| Field | Meaning |
|-------|---------|
| `die_c` | RP2040 die temperature, or the last trusted value |
| `control_c` | Temperature driving auto fans |
| `temp_source` | `internal` or `die` |
| `pressure_delta_pa` | Internal pascals minus external pascals, or `null` |
| `pressure_loop_enabled` | The config flag |
| `pressure_loop_active` | True only on a sample that applied the trim |
| `uptime_s` | Seconds since boot, as a Python integer so it survives the tick wrap |
| `wifi` | `connected`, `connecting`, `timeout`, `offline`, `disabled`, or `unsupported` |
| `ip` | Station address, or empty |
| `ssid` | Configured network name |
| `sensors.internal`, `sensors.external` | `enabled`, `ok`, `chip_id`, `temp_c`, `pressure_pa`, `error`, `fault`, `fault_reason` |
| `oled` | `enabled`, `ok`, `error` |
| `faults` | Latched faults: `sensor`, `location`, `reason`, `label`, `short`, `short_reason` |
| `fault_counts` | How many times each reason has latched: `sensor`, `location`, `reason`, `count` |
| `fans[]` | `id` 1–4, `mode`, `duty` 0–1, `rpm`, `stall`, `role` |

`chip_id` 88 is register `0x58`. `error` is `starting` after a good init until the first sample, then empty while `ok` is true. A rejected sample clears `temp_c` and `pressure_pa` so the bad number is not published. While the fault is latched, `error` is the badge sentence.

`fans[].rpm` is smoothed. The stall decision uses the latest 1 second sample, so the displayed RPM can still be falling when `stall` first becomes true.

## Metrics

`pico_fan_duty_ratio` is labelled only with `fan`. Mode would split the time series; manual versus auto is `pico_fan_override` (1 = manual).

| Metric | Type | Labels and meaning |
|--------|------|--------------------|
| `pico_fan_die_temp_celsius` | gauge | Die °C. Omitted if the value is not finite |
| `pico_fan_duty_ratio` | gauge | `fan`. Duty 0–1 |
| `pico_fan_rpm` | gauge | `fan`. Smoothed RPM |
| `pico_fan_override` | gauge | `fan`. 1 if manual |
| `pico_fan_stall` | gauge | `fan`. 1 if stalled |
| `pico_fan_uptime_seconds` | gauge | Seconds since boot |
| `pico_fan_wifi_up` | gauge | 1 only while `wifi` is `connected` |
| `pico_fan_control_temp_celsius` | gauge | Curve input |
| `pico_fan_temp_source_info` | gauge | `source="internal"` or `"die"`. 1 on the active source |
| `pico_fan_bmp280_up` | gauge | `location="internal"` or `"external"`. 1 when that read is ok |
| `pico_fan_bmp280_temperature_celsius` | gauge | `location`. Omitted while that sensor is not ok |
| `pico_fan_bmp280_pressure_pascals` | gauge | `location`. Omitted while that sensor is not ok |
| `pico_fan_pressure_delta_pascals` | gauge | Present only when the delta is a finite number |
| `pico_fan_pressure_loop_enabled` | gauge | 1 if the trim is enabled in config |
| `pico_fan_pressure_loop_active` | gauge | 1 if this sample applied the trim |
| `pico_fan_intake` | gauge | `fan`. 1 intake, 0 exhaust |
| `pico_fan_oled_up` | gauge | 1 when the OLED is enabled and the last update worked |
| `pico_fan_sensor_fault` | gauge | `sensor`, `location`, `reason`. Present only while that fault is latched |
| `pico_fan_sensor_fault_total` | counter | Same labels. Increments when that reason latches |
| `pico_fan_http_requests_total` | counter | `path` is `/`, `/status.json`, `/metrics`, `/api/fans`, or `other`. `code` is the HTTP status |

Fault labels are a closed set. `sensor` is `bmp280`, `die`, `tach`, or `pressure`. `location` is `internal`, `external`, `die`, `delta`, or `1`–`4`. `reason` is `temp_out_of_range`, `pressure_out_of_range`, `temp_jump`, `pressure_jump`, `stuck`, `stale`, `read_failed`, `die_out_of_range`, `die_jump`, `rpm_high`, `rpm_at_zero_duty`, or `pressure_delta`.

## Prometheus

```yaml
scrape_configs:
  - job_name: pico_fan
    metrics_path: /metrics
    scrape_interval: 15s
    basic_auth:
      username: pico
      password: change-me
    static_configs:
      - targets: ["192.168.1.50:80"]
```

If you set `METRICS_REQUIRE_AUTH = False`, omit `basic_auth`. The control page still requires the password when `HTTP_USER` and `HTTP_PASSWORD` are set.

Useful queries:

```promql
pico_fan_control_temp_celsius
pico_fan_duty_ratio
pico_fan_rpm
pico_fan_stall
pico_fan_pressure_delta_pascals
pico_fan_pressure_loop_active
max by (location, reason) (pico_fan_sensor_fault)
```

## Grafana

Add a Prometheus data source, then import this dashboard. Change the job if you did not use `pico_fan`.

```json
{
  "title": "Pico fan controller",
  "timezone": "browser",
  "schemaVersion": 39,
  "panels": [
    {
      "type": "timeseries",
      "title": "Control temperature",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "targets": [{"expr": "pico_fan_control_temp_celsius", "refId": "A"}]
    },
    {
      "type": "timeseries",
      "title": "Duty",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "targets": [{"expr": "pico_fan_duty_ratio", "legendFormat": "fan {{fan}}", "refId": "A"}]
    },
    {
      "type": "timeseries",
      "title": "RPM",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
      "targets": [{"expr": "pico_fan_rpm", "legendFormat": "fan {{fan}}", "refId": "A"}]
    },
    {
      "type": "stat",
      "title": "Stall or sensor fault",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
      "targets": [
        {"expr": "max(pico_fan_stall) or vector(0)", "refId": "A"},
        {"expr": "count(pico_fan_sensor_fault) or vector(0)", "refId": "B"}
      ]
    }
  ]
}
```

"""Non-blocking HTTP status/control server and Prometheus scrape endpoint."""

import binascii
import time

try:
    import errno
except ImportError:
    errno = None

# One accepted client is held across poll() calls. Each call only uses data
# already buffered by the stack, so a slow peer cannot stall the 1 s fan loop.
CLIENT_BUDGET_MS = 750
MAX_HEADER_BYTES = 1536
MAX_BODY_BYTES = 512

_BLOCK_ERRNOS = set()
if errno is not None:
    for _name in ("EAGAIN", "EWOULDBLOCK"):
        _value = getattr(errno, _name, None)
        if _value is not None:
            _BLOCK_ERRNOS.add(_value)
if not _BLOCK_ERRNOS:
    _BLOCK_ERRNOS.add(11)

AUTH_DISABLED_WARNING = (
    "WARNING: HTTP basic auth is disabled; "
    "set HTTP_USER and HTTP_PASSWORD in config.py"
)
_BASIC_REALM = 'Basic realm="pico-fan"'

# MicroPython ticks_ms wraps every 2**30 ms. Same arithmetic as wifi.py.
_TICKS_MASK = 0x3FFFFFFF
_TICKS_PERIOD = 0x40000000
_TICKS_HALF = 0x20000000


def ticks_diff(ticks1, ticks2):
    diff = (int(ticks1) - int(ticks2)) & _TICKS_MASK
    if diff >= _TICKS_HALF:
        diff -= _TICKS_PERIOD
    return diff


def ticks_add(ticks, delta):
    return (int(ticks) + int(delta)) & _TICKS_MASK


def path_bucket(path):
    if path in ("/", "/index.html"):
        return "/"
    if path in ("/status.json", "/api", "/api/status"):
        return "/status.json"
    if path == "/metrics":
        return "/metrics"
    if path.startswith("/api/fans"):
        return "/api/fans"
    return "other"


def parse_request_line(line):
    parts = line.split()
    method = parts[0].decode() if parts else "GET"
    path = parts[1].decode() if len(parts) > 1 else "/"
    if "?" in path:
        path = path.split("?", 1)[0]
    return method, path


def parse_fan_path(path):
    prefix = "/api/fans/"
    if not path.startswith(prefix):
        return None, None
    rest = path[len(prefix) :]
    bits = rest.split("/")
    try:
        fan_id = int(bits[0])
    except ValueError:
        return None, None
    if len(bits) == 1:
        return fan_id, "set"
    if len(bits) == 2 and bits[1] == "auto":
        return fan_id, "auto"
    return None, None


def parse_json_body(body):
    try:
        import json
    except ImportError:
        import ujson as json
    try:
        data = json.loads(body.decode() if isinstance(body, bytes) else body)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def resolve_auth(user, password):
    """Return (user, password) or None when either credential is empty.

    Empty credentials disable auth. Callers should print AUTH_DISABLED_WARNING.
    """
    if user is None or password is None:
        return None
    user = str(user)
    password = str(password)
    if user == "" or password == "":
        return None
    return (user, password)


def _const_eq(a, b):
    """Compare bytes without returning early on the first mismatch."""
    if not isinstance(a, (bytes, bytearray)):
        a = b"" if a is None else str(a).encode()
    if not isinstance(b, (bytes, bytearray)):
        b = b"" if b is None else str(b).encode()
    diff = len(a) ^ len(b)
    n = len(a) if len(a) >= len(b) else len(b)
    for i in range(n):
        ca = a[i] if i < len(a) else 0
        cb = b[i] if i < len(b) else 0
        diff |= ca ^ cb
    return diff == 0


def basic_credentials(header_value):
    """Return (user_bytes, password_bytes) or None."""
    if header_value is None:
        return None
    if isinstance(header_value, str):
        header_value = header_value.encode()
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != b"basic":
        return None
    token = parts[1].strip()
    # Some stacks omit "=" padding. MicroPython's a2b_base64 wants it.
    pad = (-len(token)) % 4
    if pad:
        token += b"=" * pad
    try:
        decoded = binascii.a2b_base64(token)
    except Exception:
        return None
    if b":" not in decoded:
        return None
    user, password = decoded.split(b":", 1)
    return user, password


def credentials_match(header_value, user, password):
    expect_u = user.encode() if isinstance(user, str) else user
    expect_p = password.encode() if isinstance(password, str) else password
    got = basic_credentials(header_value)
    if got is None:
        _const_eq(b"", expect_u)
        _const_eq(b"", expect_p)
        return False
    # Always compare both fields so a wrong username does not skip the password.
    ok_user = _const_eq(got[0], expect_u)
    ok_pass = _const_eq(got[1], expect_p)
    return ok_user and ok_pass


def _normalize_headers(headers):
    out = {}
    if not headers:
        return out
    for key, value in headers.items():
        if isinstance(key, str):
            key = key.encode()
        if isinstance(value, str):
            value = value.encode()
        if key is None or value is None:
            continue
        out[key.strip().lower()] = value.strip()
    return out


def _is_json_content_type(value):
    if value is None:
        return False
    if isinstance(value, str):
        value = value.encode()
    value = value.strip().lower()
    prefix = b"application/json"
    if not value.startswith(prefix):
        return False
    if len(value) == len(prefix):
        return True
    return value[len(prefix) : len(prefix) + 1] in (b";", b" ", b"\t")


def _would_block(exc):
    if isinstance(exc, BlockingIOError):
        return True
    return getattr(exc, "errno", None) in _BLOCK_ERRNOS


def request_progress(buf, max_header=MAX_HEADER_BYTES, max_body=MAX_BODY_BYTES):
    """Classify a partial HTTP/1.0 request.

    Returns ('need-data', None), ('oversize', None), ('bad', None),
    or ('ready', (method, path, headers, body)).
    """
    if isinstance(buf, bytearray):
        buf = bytes(buf)
    elif not isinstance(buf, bytes):
        return "bad", None
    header_end = buf.find(b"\r\n\r\n")
    if header_end < 0:
        if len(buf) > max_header:
            return "oversize", None
        return "need-data", None
    if header_end > max_header:
        return "oversize", None
    head = buf[:header_end]
    body = buf[header_end + 4 :]
    lines = head.split(b"\r\n")
    headers = {}
    for hl in lines[1:]:
        if b":" not in hl:
            continue
        key, value = hl.split(b":", 1)
        headers[key.strip().lower()] = value.strip()
    content_length = 0
    if b"content-length" in headers:
        try:
            content_length = int(headers[b"content-length"])
        except ValueError:
            return "bad", None
    if content_length < 0:
        return "bad", None
    if content_length > max_body:
        return "oversize", None
    if len(body) < content_length:
        return "need-data", None
    try:
        method, path = parse_request_line(lines[0] if lines else b"")
    except Exception:
        return "bad", None
    return "ready", (method, path, headers, body[:content_length])


def _fmt_num(value, spec):
    if value is None:
        return "—"
    try:
        return spec.format(float(value))
    except (TypeError, ValueError):
        return "—"


def _loop_label(status):
    if status.get("pressure_loop_active"):
        return "active"
    if status.get("pressure_loop_enabled"):
        return "idle"
    return "off"


def _sensor_label(item):
    if not item or not item.get("enabled"):
        return "disabled"
    if item.get("ok"):
        return "ok"
    err = item.get("error") or ""
    if err in ("", "starting"):
        return "starting"
    return err


def _html_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _http_response(body, content_type="text/html; charset=utf-8", code=200):
    reason = {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        404: "Not Found",
        405: "Method Not Allowed",
        413: "Payload Too Large",
    }.get(code, "OK")
    if isinstance(body, str):
        body = body.encode()
    extra = ""
    if code == 401:
        extra = "WWW-Authenticate: {}\r\n".format(_BASIC_REALM)
    header = (
        "HTTP/1.0 {} {}\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "{}"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ).format(code, reason, content_type, len(body), extra)
    return header.encode() + body


class HttpServer:
    def __init__(self, fan_ctrl, metrics_module, auth=None, metrics_require_auth=True):
        self.fan_ctrl = fan_ctrl
        self.metrics_module = metrics_module
        self.auth = auth
        self.metrics_require_auth = bool(metrics_require_auth)
        self.http_counts = {}
        self._sock = None
        self._client = None
        self._buf = bytearray()
        self._out = b""
        self._phase = None
        self._deadline = 0

    def is_listening(self):
        return self._sock is not None

    def close_listen(self):
        """Drop the listen socket and any in-flight client."""
        sock = self._sock
        self._sock = None
        self._close_client()
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def _bump(self, bucket, code):
        codes = self.http_counts.setdefault(bucket, {})
        key = str(code)
        codes[key] = codes.get(key, 0) + 1

    def _auth_required(self, path):
        if self.auth is None:
            return False
        if path == "/metrics" and not self.metrics_require_auth:
            return False
        return True

    def format_status_json(self):
        try:
            import json
        except ImportError:
            import ujson as json
        return json.dumps(self.fan_ctrl.status_dict())

    def _format_html(self):
        d = self.fan_ctrl.status_dict()
        rows = []
        for f in d["fans"]:
            fid = f["id"]
            duty_pct = int(round(float(f["duty"]) * 100))
            stall = "STALL" if f.get("stall") else ""
            role = f.get("role") or ""
            rows.append(
                "<tr data-fan='{id}'>"
                "<td>Fan {id}</td>"
                "<td id='role{id}'>{role}</td>"
                "<td class='num' id='rpm{id}'>{rpm:.0f}</td>"
                "<td class='num'><span id='duty{id}'>{duty}</span>%</td>"
                "<td id='mode{id}'>{mode}</td>"
                "<td id='stall{id}'>{stall}</td>"
                "<td><input type='range' min='0' max='100' value='{duty}' "
                "id='sl{id}' onchange='setManual({id},this.value)'></td>"
                "<td>"
                "<button type='button' onclick='setAuto({id})'>Auto</button> "
                "<button type='button' onclick='setManual({id},document.getElementById(\"sl{id}\").value)'>Manual</button>"
                "</td>"
                "</tr>".format(
                    id=fid,
                    rpm=float(f["rpm"]),
                    duty=duty_pct,
                    mode=_html_escape(f["mode"]),
                    stall=_html_escape(stall),
                    role=_html_escape(role),
                )
            )
        sensors = d.get("sensors") or {}
        internal = sensors.get("internal") or {}
        external = sensors.get("external") or {}
        oled = d.get("oled") or {}
        return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pico Fan Controller</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 1.5rem; line-height: 1.4; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 0.75rem; }}
  table {{ border-collapse: collapse; width: min(42rem, 100%); }}
  th, td {{ text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid #8884; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ opacity: 0.7; font-size: 0.9rem; }}
  #err {{ color: #b00020; min-height: 1.2em; }}
  input[type=range] {{ width: 6rem; }}
  button {{ margin: 0 0.1rem; }}
</style>
</head>
<body>
<h1>Pico W fan controller</h1>
<p class="muted">Die or internal BMP280 · per-fan PWM · poll 2s ·
  <a href="/status.json">JSON</a> · <a href="/metrics">metrics</a></p>
<p id="err"></p>
<table>
  <tr><th>Metric</th><th class="num">Value</th></tr>
  <tr><td>Die temp</td><td class="num"><span id="die">{:.1f}</span> °C</td></tr>
  <tr><td>Control temp</td><td class="num"><span id="ctl">{}</span></td></tr>
  <tr><td>Temperature source</td><td class="num" id="tsrc">{}</td></tr>
  <tr><td>Internal temp</td><td class="num" id="itemp">{}</td></tr>
  <tr><td>Internal pressure</td><td class="num" id="ipress">{}</td></tr>
  <tr><td>Internal BMP280</td><td class="num" id="istat">{}</td></tr>
  <tr><td>External temp</td><td class="num" id="etemp">{}</td></tr>
  <tr><td>External pressure</td><td class="num" id="epress">{}</td></tr>
  <tr><td>External BMP280</td><td class="num" id="estat">{}</td></tr>
  <tr><td>Pressure delta</td><td class="num" id="dp">{}</td></tr>
  <tr><td>Pressure loop</td><td class="num" id="loop">{}</td></tr>
  <tr><td>OLED</td><td class="num" id="oled">{}</td></tr>
  <tr><td>Uptime</td><td class="num"><span id="up">{}</span> s</td></tr>
  <tr><td>Wi-Fi</td><td class="num" id="wifi">{}</td></tr>
  <tr><td>IP</td><td class="num" id="ip">{}</td></tr>
</table>
<table style="margin-top:1rem">
  <tr><th>Fan</th><th>Role</th><th class="num">RPM</th><th class="num">Duty</th><th>Mode</th><th>Stall</th><th>Set</th><th>Control</th></tr>
  {}
</table>
<script>
function showErr(msg){{
  var el=document.getElementById('err');
  if(el) el.textContent=msg||'';
}}
function handle(r){{
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}}
function setManual(id,pct){{
  var d=(Number(pct)/100);
  showErr('');
  fetch('/api/fans/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{mode:'manual',duty:d}})}})
    .then(handle).then(apply)
    .catch(function(){{showErr('Control request failed');}});
}}
function setAuto(id){{
  showErr('');
  fetch('/api/fans/'+id+'/auto',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}})
    .then(handle).then(apply)
    .catch(function(){{showErr('Control request failed');}});
}}
function text(id,v){{var el=document.getElementById(id); if(el) el.textContent=v;}}
function num(v,digits,unit){{
  if(v===null||v===undefined||v!==v) return '—';
  return Number(v).toFixed(digits)+(unit||'');
}}
function sensorLabel(item){{
  if(!item||!item.enabled) return 'disabled';
  if(item.ok) return 'ok';
  if(!item.error||item.error==='starting') return 'starting';
  return item.error;
}}
function apply(s){{
  if(!s||!s.fans)return;
  showErr('');
  document.getElementById('die').textContent=s.die_c.toFixed(1);
  text('ctl', num(s.control_c,1,' °C'));
  text('tsrc', s.temp_source||'die');
  var sensors=s.sensors||{{}};
  var inn=sensors.internal||{{}};
  var ext=sensors.external||{{}};
  text('itemp', num(inn.temp_c,1,' °C'));
  text('ipress', num(inn.pressure_pa,0,' Pa'));
  text('istat', sensorLabel(inn));
  text('etemp', num(ext.temp_c,1,' °C'));
  text('epress', num(ext.pressure_pa,0,' Pa'));
  text('estat', sensorLabel(ext));
  text('dp', num(s.pressure_delta_pa,0,' Pa'));
  text('loop', s.pressure_loop_active?'active':(s.pressure_loop_enabled?'idle':'off'));
  var oled=s.oled||{{}};
  text('oled', !oled.enabled?'disabled':(oled.ok?'ok':(oled.error||'fail')));
  document.getElementById('up').textContent=s.uptime_s;
  document.getElementById('wifi').textContent=s.wifi;
  document.getElementById('ip').textContent=s.ip||'—';
  s.fans.forEach(function(f){{
    document.getElementById('rpm'+f.id).textContent=Math.round(f.rpm);
    var pct=Math.round(f.duty*100);
    document.getElementById('duty'+f.id).textContent=pct;
    document.getElementById('mode'+f.id).textContent=f.mode;
    var role=document.getElementById('role'+f.id);
    if(role) role.textContent=f.role||'';
    var st=document.getElementById('stall'+f.id);
    if(st) st.textContent=f.stall?'STALL':'';
    var sl=document.getElementById('sl'+f.id);
    if(document.activeElement!==sl)sl.value=pct;
  }});
}}
function poll(){{
  fetch('/status.json').then(handle).then(apply)
    .catch(function(){{showErr('Status refresh failed');}});
}}
setInterval(poll,2000);
</script>
</body>
</html>
""".format(
            float(d["die_c"]),
            _html_escape(_fmt_num(d.get("control_c"), "{:.1f} °C")),
            _html_escape(d.get("temp_source") or "die"),
            _html_escape(_fmt_num(internal.get("temp_c"), "{:.1f} °C")),
            _html_escape(_fmt_num(internal.get("pressure_pa"), "{:.0f} Pa")),
            _html_escape(_sensor_label(internal)),
            _html_escape(_fmt_num(external.get("temp_c"), "{:.1f} °C")),
            _html_escape(_fmt_num(external.get("pressure_pa"), "{:.0f} Pa")),
            _html_escape(_sensor_label(external)),
            _html_escape(_fmt_num(d.get("pressure_delta_pa"), "{:.0f} Pa")),
            _html_escape(_loop_label(d)),
            _html_escape(_sensor_label(oled) if oled.get("enabled") else "disabled"),
            int(d["uptime_s"]),
            _html_escape(d["wifi"]),
            _html_escape(d["ip"] or "—"),
            "".join(rows),
        )

    def dispatch(self, method, path, body, headers=None):
        """Return (code, body_bytes, content_type). Used by tests and poll()."""
        headers = _normalize_headers(headers)
        bucket = path_bucket(path)

        if self._auth_required(path):
            user, password = self.auth
            if not credentials_match(headers.get(b"authorization"), user, password):
                self._bump(bucket, 401)
                return 401, b"Unauthorized", "text/plain"

        if method == "GET" and path in ("/", "/index.html"):
            code, out, ctype = 200, self._format_html(), "text/html; charset=utf-8"
        elif method == "GET" and path in ("/status.json", "/api", "/api/status"):
            code, out, ctype = 200, self.format_status_json(), "application/json"
        elif method == "GET" and path == "/metrics":
            text = self.metrics_module.format_metrics(
                self.fan_ctrl.status_dict(), self.http_counts
            )
            code, out, ctype = (
                200,
                text,
                "text/plain; version=0.0.4; charset=utf-8",
            )
        elif method == "POST" and path.startswith("/api/fans"):
            if not _is_json_content_type(headers.get(b"content-type")):
                code, out, ctype = (
                    400,
                    "content-type must be application/json",
                    "text/plain",
                )
            else:
                fan_id, action = parse_fan_path(path)
                if fan_id is None or action is None:
                    code, out, ctype = 404, "Not Found", "text/plain"
                elif action == "auto":
                    ok, code, msg = self.fan_ctrl.set_auto(fan_id)
                    if ok:
                        out, ctype = self.format_status_json(), "application/json"
                    else:
                        out, ctype = msg, "text/plain"
                elif action == "set":
                    data = parse_json_body(body or b"")
                    if data is None:
                        code, out, ctype = 400, "bad json", "text/plain"
                    else:
                        mode = data.get("mode")
                        duty = data.get("duty", None)
                        ok, code, msg = self.fan_ctrl.apply_control(fan_id, mode, duty)
                        if ok:
                            out, ctype = self.format_status_json(), "application/json"
                        else:
                            out, ctype = msg, "text/plain"
                else:
                    code, out, ctype = 404, "Not Found", "text/plain"
        elif method not in ("GET", "POST"):
            code, out, ctype = 405, "Method Not Allowed", "text/plain"
        else:
            code, out, ctype = 404, "Not Found", "text/plain"

        self._bump(bucket, code)
        if isinstance(out, str):
            out = out.encode()
        return code, out, ctype

    def start(self, port):
        try:
            import socket
        except ImportError:
            return False
        sock = socket.socket()
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(2)
            sock.setblocking(False)
        except OSError as exc:
            print("HTTP: bind failed:", exc)
            try:
                sock.close()
            except Exception:
                pass
            return False
        self._sock = sock
        print("HTTP: listening on port {}".format(port))
        return True

    def poll(self, now_ms=None):
        """Accept or continue one client without blocking the caller."""
        if self._sock is None:
            return
        if now_ms is None:
            now_ms = time.ticks_ms()
        try:
            if self._client is None:
                self._accept(now_ms)
                if self._client is None:
                    return
            if ticks_diff(self._deadline, now_ms) <= 0:
                self._close_client()
                return
            if self._phase == "read":
                self._read_client()
            if self._client is not None and self._phase == "write":
                self._write_client()
        except Exception as exc:
            print("HTTP: request error:", exc)
            self._close_client()

    def _accept(self, now_ms):
        try:
            conn, _addr = self._sock.accept()
        except OSError as exc:
            if _would_block(exc):
                return
            # A hard error (stale socket after a Wi-Fi drop) must not spin
            # the main loop. Close the listener; main reopens it with backoff.
            print("HTTP: accept failed:", exc)
            self.close_listen()
            return
        try:
            conn.setblocking(False)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return
        self._client = conn
        self._buf = bytearray()
        self._out = b""
        self._phase = "read"
        self._deadline = ticks_add(now_ms, CLIENT_BUDGET_MS)

    def _read_client(self):
        while self._client is not None and self._phase == "read":
            try:
                chunk = self._client.recv(256)
            except OSError as exc:
                if _would_block(exc):
                    return
                raise
            if not chunk:
                self._close_client()
                return
            if len(self._buf) + len(chunk) > MAX_HEADER_BYTES + MAX_BODY_BYTES + 64:
                self._queue_response(413, b"Payload Too Large", "text/plain")
                return
            self._buf.extend(chunk)
            status, parsed = request_progress(self._buf)
            if status == "need-data":
                continue
            if status == "oversize":
                self._queue_response(413, b"Payload Too Large", "text/plain")
                return
            if status == "bad":
                self._queue_response(400, b"Bad Request", "text/plain")
                return
            method, path, headers, body = parsed
            code, out, ctype = self.dispatch(method, path, body, headers)
            self._queue_response(code, out, ctype)
            return

    def _queue_response(self, code, out, ctype):
        if isinstance(out, str):
            out = out.encode()
        # Bytes, not a memoryview: some MicroPython sockets reject memoryview.
        self._out = _http_response(out, ctype, code)
        self._phase = "write"
        self._buf = bytearray()

    def _write_client(self):
        while self._client is not None and self._out:
            try:
                n = self._client.send(self._out)
            except OSError as exc:
                if _would_block(exc):
                    return
                raise
            if not n:
                self._close_client()
                return
            if n < len(self._out):
                self._out = self._out[n:]
            else:
                self._close_client()
                return

    def _close_client(self):
        conn = self._client
        self._client = None
        self._buf = bytearray()
        self._out = b""
        self._phase = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

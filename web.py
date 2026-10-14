"""Non-blocking HTTP status/control server and Prometheus scrape endpoint."""


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
        404: "Not Found",
        405: "Method Not Allowed",
    }.get(code, "OK")
    if isinstance(body, str):
        body = body.encode()
    header = (
        "HTTP/1.0 {} {}\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ).format(code, reason, content_type, len(body))
    return header.encode() + body


class HttpServer:
    def __init__(self, fan_ctrl, metrics_module):
        self.fan_ctrl = fan_ctrl
        self.metrics_module = metrics_module
        self.http_counts = {}
        self._sock = None

    def _bump(self, bucket, code):
        codes = self.http_counts.setdefault(bucket, {})
        key = str(code)
        codes[key] = codes.get(key, 0) + 1

    def format_status_json(self):
        d = self.fan_ctrl.status_dict()
        fans_parts = []
        for f in d["fans"]:
            fans_parts.append(
                '{{"id":{},"mode":"{}","duty":{:.3f},"rpm":{:.0f}}}'.format(
                    f["id"], f["mode"], float(f["duty"]), float(f["rpm"])
                )
            )
        return (
            '{{"die_c":{:.1f},"uptime_s":{},"wifi":"{}","ip":"{}","ssid":"{}","fans":[{}]}}'
        ).format(
            float(d["die_c"]),
            int(d["uptime_s"]),
            d["wifi"],
            d["ip"],
            _html_escape(d["ssid"]).replace("\\", ""),
            ",".join(fans_parts),
        )

    def _format_html(self):
        d = self.fan_ctrl.status_dict()
        rows = []
        for f in d["fans"]:
            fid = f["id"]
            duty_pct = int(round(float(f["duty"]) * 100))
            rows.append(
                "<tr data-fan='{id}'>"
                "<td>Fan {id}</td>"
                "<td class='num' id='rpm{id}'>{rpm:.0f}</td>"
                "<td class='num'><span id='duty{id}'>{duty}</span>%</td>"
                "<td id='mode{id}'>{mode}</td>"
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
                )
            )
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
  table {{ border-collapse: collapse; width: min(40rem, 100%); }}
  th, td {{ text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid #8884; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ opacity: 0.7; font-size: 0.9rem; }}
  input[type=range] {{ width: 6rem; }}
  button {{ margin: 0 0.1rem; }}
</style>
</head>
<body>
<h1>Pico W fan controller</h1>
<p class="muted">Die ADC4 · per-fan PWM · poll 2s ·
  <a href="/status.json">JSON</a> · <a href="/metrics">metrics</a></p>
<table>
  <tr><th>Metric</th><th class="num">Value</th></tr>
  <tr><td>Die temp</td><td class="num"><span id="die">{:.1f}</span> °C</td></tr>
  <tr><td>Uptime</td><td class="num"><span id="up">{}</span> s</td></tr>
  <tr><td>Wi-Fi</td><td class="num" id="wifi">{}</td></tr>
  <tr><td>IP</td><td class="num" id="ip">{}</td></tr>
</table>
<table style="margin-top:1rem">
  <tr><th>Fan</th><th class="num">RPM</th><th class="num">Duty</th><th>Mode</th><th>Set</th><th>Control</th></tr>
  {}
</table>
<script>
function setManual(id,pct){{
  var d=(Number(pct)/100);
  fetch('/api/fans/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{mode:'manual',duty:d}})}}).then(function(r){{return r.json();}}).then(apply);
}}
function setAuto(id){{
  fetch('/api/fans/'+id+'/auto',{{method:'POST'}}).then(function(r){{return r.json();}}).then(apply);
}}
function apply(s){{
  if(!s||!s.fans)return;
  document.getElementById('die').textContent=s.die_c.toFixed(1);
  document.getElementById('up').textContent=s.uptime_s;
  document.getElementById('wifi').textContent=s.wifi;
  document.getElementById('ip').textContent=s.ip||'—';
  s.fans.forEach(function(f){{
    document.getElementById('rpm'+f.id).textContent=Math.round(f.rpm);
    var pct=Math.round(f.duty*100);
    document.getElementById('duty'+f.id).textContent=pct;
    document.getElementById('mode'+f.id).textContent=f.mode;
    var sl=document.getElementById('sl'+f.id);
    if(document.activeElement!==sl)sl.value=pct;
  }});
}}
function poll(){{fetch('/status.json').then(function(r){{return r.json();}}).then(apply);}}
setInterval(poll,2000);
</script>
</body>
</html>
""".format(
            float(d["die_c"]),
            int(d["uptime_s"]),
            _html_escape(d["wifi"]),
            _html_escape(d["ip"] or "—"),
            "".join(rows),
        )

    def dispatch(self, method, path, body):
        """Return (code, body_bytes, content_type). Used by tests and poll()."""
        bucket = path_bucket(path)

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
                data = parse_json_body(body or b"{}")
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

    def poll(self):
        if self._sock is None:
            return
        try:
            conn, _addr = self._sock.accept()
        except OSError:
            return

        try:
            conn.settimeout(1.0)
            req = b""
            while b"\r\n\r\n" not in req and len(req) < 1536:
                chunk = conn.recv(256)
                if not chunk:
                    break
                req += chunk

            header_end = req.find(b"\r\n\r\n")
            head = req[:header_end] if header_end >= 0 else req
            rest = req[header_end + 4 :] if header_end >= 0 else b""

            lines = head.split(b"\r\n")
            method, path = parse_request_line(lines[0] if lines else b"")

            content_length = 0
            for hl in lines[1:]:
                low = hl.lower()
                if low.startswith(b"content-length:"):
                    try:
                        content_length = int(low.split(b":", 1)[1].strip())
                    except ValueError:
                        content_length = 0
                    break
            if content_length > 512:
                content_length = 512
            body = rest
            while len(body) < content_length:
                chunk = conn.recv(256)
                if not chunk:
                    break
                body += chunk
            body = body[:content_length]

            code, out, ctype = self.dispatch(method, path, body)
            conn.sendall(_http_response(out, ctype, code))
        except Exception as exc:
            print("HTTP: request error:", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

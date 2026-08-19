import gc
import time
import socket
import network
import camera

from secrets import WIFI_MODE, NETWORKS

CURRENT_NETWORK = NETWORKS[WIFI_MODE]

# ---------------------------------------------------------------------------
# Runtime camera settings. These are the *defaults* used at boot; the web UI
# below can change them live by calling camera.framesize()/camera.quality()
# again, and we keep these two globals in sync so the HTML page always shows
# the resolution/quality that's actually active.
# ---------------------------------------------------------------------------
FRAMESIZES = {
    # name shown in the dropdown -> constant understood by the camera driver
    "QVGA": camera.FRAME_QVGA,    # 320x240  - fastest, lowest bandwidth
    "VGA": camera.FRAME_VGA,      # 640x480  - good default
    "SVGA": camera.FRAME_SVGA,    # 800x600
    "XGA": camera.FRAME_XGA,      # 1024x768
    "SXGA": camera.FRAME_SXGA,    # 1280x1024
    "UXGA": camera.FRAME_UXGA,    # 1600x1200 - slowest, most memory/bandwidth
}
current_framesize_name = "VGA"
current_quality = 12  # 10-63, LOWER number = HIGHER quality (bigger JPEGs)


def build_index_html():
    # Rebuilt on every request (not cached) so the resolution/quality dropdowns
    # always reflect whatever is currently active on the camera.
    options_html = "".join(
        '<option value="%s"%s>%s</option>'
        % (name, " selected" if name == current_framesize_name else "", name)
        for name in FRAMESIZES
    )
    return """<!DOCTYPE html>
<html>
<head>
<title>ESP32-CAM Live View</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ background:#111; color:#eee; font-family:sans-serif; text-align:center; margin:0; padding:20px; }}
  img {{ max-width:100%; border:2px solid #444; border-radius:8px; }}
  h1 {{ font-weight:400; }}
  a {{ color:#6cf; }}
  form {{ margin:16px 0; }}
  select, input, button {{ font-size:1em; padding:4px 8px; margin:0 4px; }}
</style>
</head>
<body>
  <h1>ESP32-CAM Live Stream</h1>
  <img src="/stream">
  <p><a href="/capture">Single snapshot (full quality JPEG)</a></p>

  <form action="/settings" method="get">
    <label>Resolution
      <select name="framesize">{options}</select>
    </label>
    <label>Quality (10=best, 63=worst)
      <input type="number" name="quality" min="10" max="63" value="{quality}">
    </label>
    <button type="submit">Apply</button>
  </form>
</body>
</html>""".format(options=options_html, quality=current_quality)


# ---------------------------------------------------------------------------
# WiFi
# ---------------------------------------------------------------------------
def connect_wifi():
    # STA_IF = "station interface", i.e. join an existing WiFi network
    # (as opposed to AP_IF, which would make the ESP32 broadcast its own network).
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    try_connect_wifi(sta)
    return sta


def try_connect_wifi(sta):
    # Kicks off a connection attempt and waits up to ~10s for it to succeed.
    # Safe to call repeatedly: if we're already connected this is a no-op,
    # and if we're mid-attempt, re-issuing connect() just restarts it.
    if sta.isconnected():
        return
    static_ip = CURRENT_NETWORK.get("static_ip")
    if static_ip:
        # Setting ifconfig before connect() disables DHCP and pins the
        # address, so the device is always reachable at the same IP
        # (phone hotspots don't offer a way to look up a device's DHCP IP).
        sta.ifconfig(static_ip)
    print("Connecting to WiFi (%s):" % WIFI_MODE, CURRENT_NETWORK["ssid"])
    sta.connect(CURRENT_NETWORK["ssid"], CURRENT_NETWORK["password"])
    attempts = 10
    while not sta.isconnected() and attempts > 0:
        time.sleep(1)
        attempts -= 1
    if sta.isconnected():
        print("WiFi connected, IP:", sta.ifconfig()[0])
    else:
        print("WiFi not connected yet, will keep retrying in the background")


def ensure_wifi_connected(sta):
    # Called periodically from the server loop (see serve()) so that if the
    # router drops us, or we boot up out of range, the board keeps trying to
    # reconnect on its own instead of needing a manual power cycle.
    if not sta.isconnected():
        try_connect_wifi(sta)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
# Pin mapping for the Freenove ESP32-WROVER CAM board (ESP-WROVER-KIT camera
# pinout). NOTE: this is different from the AI-Thinker ESP32-CAM default pins
# that most online tutorials assume - if you swap boards, this dict is the
# thing to change.
CAMERA_PINS = dict(
    d0=4, d1=5, d2=18, d3=19, d4=36, d5=39, d6=34, d7=35,
    href=23, vsync=25, reset=-1, pwdn=-1,
    sioc=27, siod=26, xclk=21, pclk=22,
)


def init_camera():
    camera.deinit()  # harmless no-op if the camera was never initialized
    ok = camera.init(
        0,
        format=camera.JPEG,
        framesize=FRAMESIZES[current_framesize_name],
        fb_location=camera.PSRAM,  # frame buffer lives in PSRAM, not scarce main RAM
        **CAMERA_PINS
    )
    if not ok:
        raise RuntimeError("Camera init failed")
    camera.quality(current_quality)


# ---------------------------------------------------------------------------
# Tiny hand-rolled HTTP server. No frameworks - just enough HTTP to serve a
# page, a single JPEG, an MJPEG stream, and a settings endpoint.
# ---------------------------------------------------------------------------
def send_index(conn):
    body = build_index_html().encode()
    conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body))
    conn.send(body)


def send_capture(conn):
    # One-shot JPEG snapshot at the currently configured resolution/quality.
    buf = camera.capture()
    conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(buf))
    conn.send(buf)


def send_stream(conn):
    # MJPEG streaming: an HTTP response that never "ends" - instead each frame
    # is sent as its own little multipart chunk. Browsers understand this
    # content type natively and just keep repainting the <img> tag with each
    # new chunk, which is what makes the page update live with no JS at all.
    conn.send(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
        b"Cache-Control: no-cache\r\n"
        b"Connection: close\r\n\r\n"
    )
    try:
        while True:
            buf = camera.capture()
            if not buf:
                continue
            conn.send(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(buf))
            conn.send(buf)
            conn.send(b"\r\n")
            gc.collect()  # each frame allocates a fresh JPEG buffer; keep the heap tidy
    except OSError:
        pass  # client closed the tab / lost connection - not an error, just stop


def parse_query_params(path):
    # Very small "?key=value&key2=value2" parser - no percent-decoding, since
    # the values we expect (resolution names, numbers) never need it.
    if b"?" not in path:
        return {}
    query = path.split(b"?", 1)[1]
    params = {}
    for pair in query.split(b"&"):
        if b"=" in pair:
            key, value = pair.split(b"=", 1)
            params[key.decode()] = value.decode()
    return params


def handle_settings(conn, path):
    global current_framesize_name, current_quality

    params = parse_query_params(path)

    framesize_name = params.get("framesize")
    if framesize_name in FRAMESIZES:
        camera.framesize(FRAMESIZES[framesize_name])
        current_framesize_name = framesize_name
        print("Resolution changed to", framesize_name)

    quality_str = params.get("quality")
    if quality_str is not None:
        try:
            quality = int(quality_str)
        except ValueError:
            quality = None
        if quality is not None:
            quality = max(10, min(63, quality))  # clamp to the sensor's valid range
            camera.quality(quality)
            current_quality = quality
            print("Quality changed to", quality)

    # 303 See Other + Location sends the browser back to "/", which re-renders
    # the form with the new values already selected/filled in.
    conn.send(b"HTTP/1.1 303 See Other\r\nLocation: /\r\nConnection: close\r\n\r\n")


def serve(sta):
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    # A timeout on the *listening* socket means accept() gives up and raises
    # OSError every 5s when nobody's connecting, instead of blocking forever.
    # We use that gap to check on the WiFi link (see ensure_wifi_connected).
    s.settimeout(5)
    print("Server listening on port 80")

    while True:
        try:
            conn, client_addr = s.accept()
        except OSError:
            # Nobody connected within the timeout window - a normal, expected
            # event, not a real error. Use the idle moment to check WiFi.
            ensure_wifi_connected(sta)
            continue

        conn.settimeout(15)  # don't let one slow/dead client hang the server forever
        print("Client connected:", client_addr)
        try:
            request = conn.recv(1024)
            request_line = request.split(b"\r\n", 1)[0]
            path = request_line.split(b" ")[1] if b" " in request_line else b"/"

            if path.startswith(b"/stream"):
                send_stream(conn)
            elif path.startswith(b"/capture"):
                send_capture(conn)
            elif path.startswith(b"/settings"):
                handle_settings(conn, path)
            else:
                send_index(conn)
        except Exception as e:
            print("Request error:", e)
        finally:
            try:
                conn.close()
            except OSError:
                pass


def main():
    sta = connect_wifi()
    init_camera()
    serve(sta)  # never returns - this is the whole program from here on


if __name__ == "__main__":
    main()

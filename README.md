# gioesp32cam

MicroPython project for a **Freenove ESP32-WROVER CAM** board (OV2640 sensor). The main program connects the board to WiFi and serves a live camera feed as a webpage, viewable from any browser on the same network — no app required.

## What's in this repo

- **[camstream/](camstream/)** — the main project: WiFi + camera + web server. This is what actually runs on the device.
- **[blinktest/](blinktest/)** — a minimal "blink the onboard LED" script, useful as a sanity check that a board is alive and flashable before doing anything camera-related.

## Hardware requirements

- Freenove ESP32-WROVER CAM (ESP32-D0WD-V3, OV2640 camera, PSRAM)
- USB-to-serial connection (the board shows up as `/dev/ttyUSB0` on Linux, via a CH340 USB adapter)

## One-time setup

### 1. Flash camera-enabled MicroPython firmware

Stock/official MicroPython builds for ESP32 **do not include a `camera` module**. You need a custom build with the OV2640 driver compiled in, such as [lemariva/micropython-camera-driver](https://github.com/lemariva/micropython-camera-driver).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install esptool mpremote

# download micropython_v1.21.0_camera_no_ble.bin from the repo above, then:
esptool.py --chip esp32 --port /dev/ttyUSB0 erase_flash
esptool.py --chip esp32 --port /dev/ttyUSB0 write_flash -z 0x1000 micropython_camera_no_ble.bin
```

⚠️ `erase_flash` wipes everything currently on the board's flash. Back up any files you care about first (`mpremote connect /dev/ttyUSB0 fs cp :main.py ./backup_main.py`).

### 2. Configure WiFi credentials

Copy [camstream/secrets.example.py](camstream/secrets.example.py) to `camstream/secrets.py` and fill in your network(s):

```python
WIFI_MODE = "home"  # "home" or "travel" - switch before flashing/rebooting

NETWORKS = {
    "home": {
        "ssid": "your-network-name",
        "password": "your-network-password",
    },
    "travel": {
        # e.g. a phone hotspot - static_ip is optional; include it to give the
        # device a fixed, predictable IP instead of whatever DHCP hands out.
        "ssid": "your-hotspot-name",
        "password": "your-hotspot-password",
        "static_ip": ("172.20.10.5", "255.255.255.240", "172.20.10.1", "172.20.10.1"),
    },
}
```

`WIFI_MODE` picks which entry in `NETWORKS` the board connects to at boot. `static_ip` is optional (`(ip, subnet, gateway, dns)`) — set it when the network won't reliably show you the device's DHCP-assigned address, like a phone hotspot; the values above are the iPhone Personal Hotspot defaults (`172.20.10.0/28`, gateway `172.20.10.1`), with `.5` chosen to sit outside the DHCP range iOS hands out (`.2`–`.14`).

This file holds plaintext passwords — keep it out of version control (it's already in `.gitignore`).

### 3. Upload the project to the board

```bash
source .venv/bin/activate
mpremote connect /dev/ttyUSB0 fs cp camstream/secrets.py :secrets.py
mpremote connect /dev/ttyUSB0 fs cp camstream/main.py :main.py
mpremote connect /dev/ttyUSB0 reset
```

The board runs `main.py` automatically on every boot from here on.

### VSCode setup (alternative to the CLI above)

This project has [.vscode/settings.json](.vscode/settings.json) pre-configured for the **MicroPico** extension (`paulober.pico-w-go`), pointed at `/dev/ttyUSB0`. Install it, then use the MicroPico sidebar to connect, browse files on the device, and run/upload directly from the editor.

Only one program can hold the serial port at a time — disconnect Thonny, VSCode/MicroPico, or any open `mpremote`/`esptool` session before starting another.

## Using it

Once running, the board prints its IP address over serial (e.g. via `mpremote connect /dev/ttyUSB0` or Thonny's Shell) — or, in `travel` mode with `static_ip` set, it's always the fixed address from `secrets.py`. Open that IP in a browser on the same WiFi network:

| URL | What it does |
|---|---|
| `http://<esp32-ip>/` | Live viewer page — MJPEG stream plus a form to change resolution/quality |
| `http://<esp32-ip>/stream` | Raw MJPEG stream (what the viewer page embeds) |
| `http://<esp32-ip>/capture` | One-shot JPEG snapshot at the current settings |
| `http://<esp32-ip>/settings?framesize=SVGA&quality=15` | Change resolution (`QVGA`/`VGA`/`SVGA`/`XGA`/`SXGA`/`UXGA`) and/or JPEG quality (`10`=best, `63`=worst) |

If the board loses WiFi, it automatically retries reconnecting in the background — no manual reset needed.

## Notes for this specific board

The Freenove ESP32-WROVER CAM uses the **ESP-WROVER-KIT camera pinout**, not the AI-Thinker ESP32-CAM default pinout most tutorials assume. If you swap to a different board, the `CAMERA_PINS` dict near the top of [camstream/main.py](camstream/main.py) is what needs to change.

[camstream/main.py](camstream/main.py) is commented throughout to explain each part (WiFi connection/reconnect, camera init, the hand-rolled HTTP server, MJPEG streaming, and the settings endpoint) if you want to explore or extend it.

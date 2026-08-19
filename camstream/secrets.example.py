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

"""Local network probes."""
import re
import socket
import urllib.request

import psutil

PRIVATE_LAN = re.compile(r"192\.168\.|172\.(1[6-9]|2\d|3[01])\.")


def http_ok(port, path, timeout=1.5):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def lan_ip():
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family == socket.AF_INET and PRIVATE_LAN.match(a.address):
                return a.address
    return None

"""UDP-based worker discovery on the local network."""
DISCOVERY_PORT = 9555
BEACON_PREFIX = "YOLO_WORKER|"


def parse_beacon(data: bytes) -> int | None:
    """Parse 'YOLO_WORKER|9001\\n' -> 9001. Returns None if invalid."""
    try:
        s = data.decode("utf-8").strip()
        if not s.startswith(BEACON_PREFIX):
            return None
        return int(s[len(BEACON_PREFIX) :])
    except Exception:
        return None

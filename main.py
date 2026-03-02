"""FastAPI app: upload video, auto-discover or use WORKER_URLS, WebSocket dashboard."""
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from queue import Queue

import httpx
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from pipeline.camera import capture_frames
from pipeline.discovery import DISCOVERY_PORT, parse_beacon
from pipeline.extract import extract_frames

# Workers are added by discovery only (UDP beacon). No manual worker URLs.

INPUT_QUEUE_MAXSIZE = 64
BROADCAST_INTERVAL = 0.1
MAX_FRAME_IDS_PER_WORKER = 30
DISCOVERY_STALE_SEC = 10
DISCOVERY_CLEANUP_INTERVAL = 5

app = FastAPI(title="Video processing pipeline")

sync_input_queue: Queue = None
in_queue: asyncio.Queue = None
out_queue: asyncio.Queue = None
discovered_workers: dict = None  # url -> last_seen (time)
workers_stats: dict = None  # url -> { frames_processed, last_latency_ms, errors, frame_ids }
discovery_lock: asyncio.Lock = None
stats_lock: asyncio.Lock = None
latest_broadcast: dict = None
broadcast_lock: asyncio.Lock = None
ws_connections: list = None
loop: asyncio.AbstractEventLoop = None
discovery_socket: socket.socket = None
round_robin_index: int = 0
camera_running: bool = False
# Worker nodes started from this orchestrator (port -> subprocess.Popen)
worker_processes: dict = None
worker_processes_lock: threading.Lock = None


def get_active_urls():
    """Return sorted list of worker URLs that are not stale (call under discovery_lock)."""
    now = time.time()
    return sorted(
        url for url, last in discovered_workers.items()
        if last > now - DISCOVERY_STALE_SEC
    )


def ensure_stats(url: str):
    """Ensure workers_stats[url] exists (call under stats_lock)."""
    if url not in workers_stats:
        workers_stats[url] = {
            "frames_processed": 0,
            "last_latency_ms": 0.0,
            "errors": 0,
            "frame_ids": [],
        }


def snapshot_workers_stats():
    """Return list of worker dicts for JSON; only active workers (call under discovery_lock + stats_lock)."""
    urls = get_active_urls()
    out = []
    for i, url in enumerate(urls):
        s = workers_stats.get(url)
        if not s:
            continue
        out.append({
            "worker_id": i + 1,
            "worker_url": url,
            "frames_processed": s["frames_processed"],
            "last_latency_ms": s["last_latency_ms"],
            "errors": s["errors"],
            "frame_ids": list(s["frame_ids"]),
        })
    return out


def _bridge_thread():
    """Thread: move items from sync_input_queue to asyncio in_queue."""
    while True:
        try:
            item = sync_input_queue.get()
            if loop and in_queue is not None:
                asyncio.run_coroutine_threadsafe(in_queue.put(item), loop).result()
        except Exception:
            pass


def _handle_discovery_packet(data: bytes, peer: tuple):
    """Called when UDP packet received. Parse beacon and add worker URL."""
    port = parse_beacon(data)
    if port is None:
        return
    ip = peer[0]
    url = f"http://{ip}:{port}"
    asyncio.run_coroutine_threadsafe(_discovery_seen(url), loop).result()


async def _discovery_seen(url: str):
    """Record that we saw this worker (discovery listener or manual seed)."""
    async with discovery_lock:
        discovered_workers[url] = time.time()
    async with stats_lock:
        ensure_stats(url)


def _discovery_reader():
    """Sync callback for asyncio add_reader: read one UDP packet and handle it."""
    try:
        data, peer = discovery_socket.recvfrom(256)
        _handle_discovery_packet(data, peer)
    except Exception:
        pass


async def discovery_cleanup_task():
    """Remove workers not seen for DISCOVERY_STALE_SEC."""
    while True:
        await asyncio.sleep(DISCOVERY_CLEANUP_INTERVAL)
        now = time.time()
        async with discovery_lock:
            stale = [url for url, last in discovered_workers.items() if last <= now - DISCOVERY_STALE_SEC]
            for url in stale:
                discovered_workers.pop(url, None)


async def dispatcher():
    """Single dispatcher: take from in_queue, round-robin POST to discovered workers, put result on out_queue."""
    global round_robin_index
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                frame_index, jpeg_bytes = await in_queue.get()
            except Exception:
                break
            async with discovery_lock:
                urls = get_active_urls()
            if not urls:
                await asyncio.sleep(0.3)
                continue
            worker_url = urls[round_robin_index % len(urls)]
            round_robin_index += 1
            try:
                r = await client.post(
                    f"{worker_url.rstrip('/')}/process",
                    content=jpeg_bytes,
                    headers={"X-Frame-Index": str(frame_index), "Content-Type": "application/octet-stream"},
                )
                if r.status_code != 200:
                    async with stats_lock:
                        ensure_stats(worker_url)
                        workers_stats[worker_url]["errors"] += 1
                    continue
                data = r.json()
                image_b64 = data.get("image_b64", "")
                latency_ms = data.get("latency_ms", 0)
            except Exception:
                async with stats_lock:
                    ensure_stats(worker_url)
                    workers_stats[worker_url]["errors"] += 1
                continue
            async with stats_lock:
                ensure_stats(worker_url)
                workers_stats[worker_url]["frames_processed"] += 1
                workers_stats[worker_url]["last_latency_ms"] = latency_ms
                ids = workers_stats[worker_url]["frame_ids"]
                ids.append(frame_index)
                while len(ids) > MAX_FRAME_IDS_PER_WORKER:
                    ids.pop(0)
            await out_queue.put((frame_index, image_b64, latency_ms))


async def output_consumer():
    """Read from out_queue, update latest_broadcast (frame + stats)."""
    global latest_broadcast
    while True:
        try:
            frame_index, image_b64, latency_ms = await out_queue.get()
            async with discovery_lock:
                async with stats_lock:
                    workers = snapshot_workers_stats()
            async with broadcast_lock:
                latest_broadcast["frame_index"] = frame_index
                latest_broadcast["image_b64"] = image_b64
                latest_broadcast["workers"] = workers
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.05)


async def broadcaster():
    """Periodically send latest_broadcast to all WebSocket clients (stats + discovery count even when no frame)."""
    while True:
        await asyncio.sleep(BROADCAST_INTERVAL)
        async with broadcast_lock:
            msg = dict(latest_broadcast)
        # Always send current worker list so dashboard shows discovery count
        async with discovery_lock:
            async with stats_lock:
                msg["workers"] = snapshot_workers_stats()
        if not ws_connections:
            continue
        dead = []
        for ws in list(ws_connections):
            try:
                await ws.send_json(msg)  # send even without image so discovery count updates
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in ws_connections:
                ws_connections.remove(ws)


def feed_video_to_queue(video_path: str):
    """Run in thread: extract frames and put on sync_input_queue."""
    try:
        for frame_index, jpeg_bytes in extract_frames(video_path):
            sync_input_queue.put((frame_index, jpeg_bytes))
    finally:
        Path(video_path).unlink(missing_ok=True)


def feed_camera_to_queue(device: int = 0):
    """Run in thread: capture from camera and put frames on sync_input_queue."""
    global camera_running
    camera_running = True
    try:
        for frame_index, jpeg_bytes in capture_frames(
            device=device, stop_flag=lambda: not camera_running
        ):
            try:
                sync_input_queue.put((frame_index, jpeg_bytes), timeout=0.5)
            except Exception:
                pass
    finally:
        camera_running = False


@app.on_event("startup")
async def startup():
    global sync_input_queue, in_queue, out_queue, discovered_workers, workers_stats
    global discovery_lock, stats_lock, latest_broadcast, broadcast_lock, ws_connections, loop
    global discovery_socket, worker_processes, worker_processes_lock
    loop = asyncio.get_running_loop()
    worker_processes = {}
    worker_processes_lock = threading.Lock()
    sync_input_queue = Queue(maxsize=INPUT_QUEUE_MAXSIZE)
    in_queue = asyncio.Queue()
    out_queue = asyncio.Queue()
    discovery_lock = asyncio.Lock()
    stats_lock = asyncio.Lock()
    broadcast_lock = asyncio.Lock()
    ws_connections = []
    discovered_workers = {}
    workers_stats = {}

    # Discovery only: listen for UDP beacons from workers on the LAN
    discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    discovery_socket.setblocking(False)
    try:
        discovery_socket.bind(("", DISCOVERY_PORT))
    except OSError:
        discovery_socket.close()
        discovery_socket = None
    if discovery_socket:
        loop.add_reader(discovery_socket.fileno(), _discovery_reader)
        asyncio.create_task(discovery_cleanup_task())

    latest_broadcast = {
        "frame_index": 0,
        "image_b64": "",
        "workers": [],
    }

    threading.Thread(target=_bridge_thread, daemon=True).start()
    asyncio.create_task(dispatcher())
    asyncio.create_task(output_consumer())
    asyncio.create_task(broadcaster())


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/upload")
async def upload(video: UploadFile = File(...)):
    """Save uploaded video and feed frames into the pipeline."""
    suffix = Path(video.filename or "video").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(await video.read())
        path = f.name
    threading.Thread(target=feed_video_to_queue, args=(path,), daemon=True).start()
    return {"status": "processing", "file": video.filename}


@app.post("/camera/start")
def camera_start(device: int = 0):
    """Start feeding camera (device index, default 0) into the pipeline."""
    global camera_running
    if camera_running:
        return {"status": "already_running"}
    threading.Thread(target=feed_camera_to_queue, args=(device,), daemon=True).start()
    return {"status": "started", "device": device}


@app.post("/camera/stop")
def camera_stop():
    """Stop camera capture."""
    global camera_running
    camera_running = False
    return {"status": "stopped"}


@app.get("/camera/status")
def camera_status():
    """Return whether camera is currently feeding."""
    return {"camera_running": camera_running}


@app.get("/discovery/status")
def discovery_status():
    """Return whether discovery is listening (UDP port). For dashboard and troubleshooting."""
    listening = discovery_socket is not None
    return {"enabled": listening, "udp_port": DISCOVERY_PORT}


def _start_worker_process(port: int) -> bool:
    """Start worker server as subprocess. Returns True if started."""
    cwd = Path(__file__).resolve().parent
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pipeline.worker_server", str(port)],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with worker_processes_lock:
            worker_processes[port] = proc
        return True
    except Exception:
        return False


@app.post("/workers/start")
def workers_start(port: int = 9001):
    """Start a worker node on this device on the given port."""
    with worker_processes_lock:
        if port in worker_processes and worker_processes[port].poll() is None:
            return {"status": "already_running", "port": port}
    if _start_worker_process(port):
        return {"status": "started", "port": port}
    return {"status": "error", "port": port}


@app.post("/workers/stop")
def workers_stop(port: int = 9001):
    """Stop a worker node on the given port."""
    with worker_processes_lock:
        proc = worker_processes.pop(port, None)
    if proc is None:
        return {"status": "not_found", "port": port}
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return {"status": "stopped", "port": port}


@app.get("/workers")
def workers_list():
    """List worker nodes started from this orchestrator (port -> running)."""
    with worker_processes_lock:
        result = []
        dead = []
        for port, proc in list(worker_processes.items()):
            alive = proc.poll() is None
            if not alive:
                dead.append(port)
            result.append({"port": port, "running": alive})
        for port in dead:
            worker_processes.pop(port, None)
    return {"workers": sorted(result, key=lambda x: x["port"])}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_connections.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in ws_connections:
            ws_connections.remove(ws)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

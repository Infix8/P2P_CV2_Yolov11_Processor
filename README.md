# Video processing pipeline with network YOLO workers

Lightweight pipeline: upload a video → frames at 640×480 JPEG → sent to **network workers** (IP:port) → real-time dashboard with bounding boxes and per-worker stats. Workers can run on the same machine (different ports) or on any device on the local network.

## How to use it

- **Desktop (dashboard):** Run the app **without** setting `WORKER_URLS`. It auto-discovers workers on the LAN.
  ```bash
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
  ```
- **Laptop (workers):** Run 4 workers, each on a different port (e.g. 9001 … 9004).
  ```bash
  python -m pipeline.worker_server 9001
  python -m pipeline.worker_server 9002
  python -m pipeline.worker_server 9003
  python -m pipeline.worker_server 9004
  ```
- **Both on the same LAN.** Within a few seconds the dashboard shows **“Discovered 4 worker(s)”** and lists each worker’s URL. No manual IP or URL configuration.

Open **http://localhost:8000** on the desktop and upload a video to process. You can also use **Start camera** for live capture (same pipeline, 640×480 @ 10 fps); **Stop camera** to end.

## Setup

```bash
cd d:\fakedemo
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

## Run workers (lightweight, bind to IP:port)

Workers are standalone and can run on **any device** on your local network. Each worker listens on a host:port.

**Worker-only install (e.g. on laptop):** use the smaller dependency set so you don’t need `httpx` or `python-multipart`:

```bash
pip install -r requirements-worker.txt
```

**Same-machine testing (4 workers, different ports):**

```bash
# Terminal 1 – worker on port 9001
python -m pipeline.worker_server 9001

# Terminal 2 – worker on port 9002
python -m pipeline.worker_server 9002

# Terminal 3 – worker on port 9003
python -m pipeline.worker_server 9003

# Terminal 4 – worker on port 9004
python -m pipeline.worker_server 9004
```

By default workers bind to `0.0.0.0`, so they accept connections from other machines. To bind to a specific IP:

```bash
python -m pipeline.worker_server 9001 --host 192.168.1.10
```

## Run the orchestrator (dashboard + upload)

On the machine where you want the dashboard (e.g. your desktop):

**Workers are auto-discovered** on the local network. Start the app with no config; it listens for UDP beacons from workers and adds them automatically. The dashboard shows “Discovered N worker(s)” and each worker’s URL.

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. Start workers on the laptop (or same PC); they will appear within a few seconds. No manual IP setup needed.

**Optional – manual worker URLs** (disables discovery):

```bash
set WORKER_URLS=http://192.168.0.107:9001,http://192.168.0.107:9002,http://192.168.0.107:9003,http://192.168.0.107:9004
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in a browser. Upload a video; the dashboard shows live inference and stats for each worker.

---

## Testing: Laptop (workers) + Desktop (dashboard)

Use the **laptop** for workers and the **desktop** for the dashboard. With **auto-discovery you don’t set WORKER_URLS** — the dashboard finds workers on the network.

### 1. On the laptop (workers)

- Copy the project onto the laptop. Install deps: `pip install -r requirements-worker.txt`
- Start 4 workers in 4 terminals. Each broadcasts a beacon so the dashboard can discover them:

```bash
python -m pipeline.worker_server 9001
python -m pipeline.worker_server 9002
python -m pipeline.worker_server 9003
python -m pipeline.worker_server 9004
```

- If the desktop can’t connect, allow the worker ports through the laptop’s firewall (e.g. Windows: allow inbound TCP 9001–9004).

### 2. On the desktop (dashboard)

- Install the project and deps: `pip install -r requirements.txt`
- Start the app **without** setting WORKER_URLS (workers are auto-discovered):

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- In a browser on the desktop, open **http://localhost:8000**. You should see “Discovered 4 worker(s)” once the laptop’s workers are on the same network. Upload a video to process.

## Optional: sample video

Use any short MP4/AVI for testing. YOLOv8n (nano) runs on CPU or GPU if available.

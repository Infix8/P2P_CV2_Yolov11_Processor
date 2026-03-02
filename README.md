# Video processing pipeline with network YOLO workers

Lightweight pipeline: upload a video or use a **camera** → frames at 640×480 JPEG → sent to **network workers** (auto-discovered) → real-time dashboard with bounding boxes and per-worker stats.

**Dashboard:** One page with two tabs — **Orchestrator start** (upload, camera, worker stats, video output) and **Worker nodes creator** (commands to run workers). Any device can run both the orchestrator and workers.

---

## Quick start

1. **Setup** (orchestrator machine, e.g. desktop):
   ```bash
   git clone https://github.com/Infix8/P2P_CV2_Yolov11_Processor.git
   cd P2P_CV2_Yolov11_Processor
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```

2. **Start orchestrator:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Start workers** (same machine or another on the LAN). Use the **Worker nodes creator** tab on the dashboard, or run in separate terminals:
   ```bash
   pip install -r requirements-worker.txt   # worker machine only
   python -m pipeline.worker_server 9001
   python -m pipeline.worker_server 9002
   python -m pipeline.worker_server 9003
   python -m pipeline.worker_server 9004
   ```

4. Open **http://localhost:8000**. Tab **Orchestrator start**: upload a video or click **Start camera** for live YOLO inference. Workers are auto-discovered; no manual IP config.

---

## Setup (orchestrator)

```bash
pip install -r requirements.txt
```

Requires: FastAPI, uvicorn, opencv, ultralytics, httpx, python-multipart.

---

## Workers (lightweight)

Workers run on any device on the local network. Each broadcasts a beacon; the orchestrator discovers them automatically.

**Worker-only install** (no httpx/multipart):

```bash
pip install -r requirements-worker.txt
```

**Run workers** (one per terminal):

```bash
python -m pipeline.worker_server 9001
python -m pipeline.worker_server 9002
python -m pipeline.worker_server 9003
python -m pipeline.worker_server 9004
```

Workers bind to `0.0.0.0` by default. Optional: `python -m pipeline.worker_server 9001 --host 192.168.1.10`

---

## Optional: manual worker URLs

To disable auto-discovery and fix worker URLs (e.g. for a known laptop IP):

```bash
set WORKER_URLS=http://192.168.0.107:9001,http://192.168.0.107:9002,http://192.168.0.107:9003,http://192.168.0.107:9004
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## Laptop (workers) + Desktop (dashboard)

- **Laptop:** Clone repo, `pip install -r requirements-worker.txt`, start the four workers (see above). Allow firewall for TCP 9001–9004 if needed.
- **Desktop:** Clone repo, `pip install -r requirements.txt`, run `uvicorn main:app --reload --host 0.0.0.0 --port 8000`. Open http://localhost:8000 — workers appear as “Discovered 4 worker(s)” with no WORKER_URLS.

---

## Notes

- **Camera:** In the Orchestrator tab, use **Start camera** for live 640×480 @ 10 fps; **Stop camera** to end. Camera runs on the machine where uvicorn is running.
- **Model:** YOLOv8n (nano) is used; runs on CPU or GPU if available. Use any short MP4/AVI or live camera for testing.

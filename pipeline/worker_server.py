"""
Lightweight YOLO worker server. Run on any device, bind to IP:port for local network.

  python -m pipeline.worker_server 9001
  python -m pipeline.worker_server 9002 --host 0.0.0.0

Dashboard auto-discovers workers via UDP broadcast; no manual WORKER_URLS needed.
"""
import base64
import socket
import sys
import threading
import time
import cv2
import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ultralytics import YOLO

from pipeline.discovery import BEACON_PREFIX, DISCOVERY_PORT

app = FastAPI(title="YOLO worker", docs_url=None, redoc_url=None)
model = None


def _beacon_loop(port: int):
    """Broadcast 'YOLO_WORKER|port' to local network so the dashboard can discover this worker."""
    msg = f"{BEACON_PREFIX}{port}\n".encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        try:
            sock.sendto(msg, ("255.255.255.255", DISCOVERY_PORT))
        except Exception:
            pass
        time.sleep(2)


@app.on_event("startup")
def load_model():
    global model
    model = YOLO("yolov8n.pt")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process")
async def process(request: Request):
    """Accept raw JPEG body, optional header X-Frame-Index. Return JSON { image_b64, latency_ms }."""
    global model
    frame_index = request.headers.get("X-Frame-Index", "")
    body = await request.body()
    if not body:
        return JSONResponse({"error": "empty body"}, status_code=400)
    t0 = time.perf_counter()
    try:
        arr = np.frombuffer(body, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return JSONResponse({"error": "invalid image"}, status_code=400)
        results = model.predict(img, verbose=False)
        out_img = results[0].plot()
        _, out_jpeg = cv2.imencode(".jpg", out_img)
        latency_ms = (time.perf_counter() - t0) * 1000
        image_b64 = base64.b64encode(out_jpeg.tobytes()).decode("ascii")
        return {"image_b64": image_b64, "latency_ms": round(latency_ms, 2), "frame_index": frame_index}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def main():
    port = 9001
    host = "0.0.0.0"
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    if "--host" in sys.argv:
        i = sys.argv.index("--host")
        if i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
    # Start discovery beacon so dashboard can find this worker
    t = threading.Thread(target=_beacon_loop, args=(port,), daemon=True)
    t.start()
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

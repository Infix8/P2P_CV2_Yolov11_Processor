"""Single YOLO worker: dequeue frame -> predict -> draw boxes -> enqueue result + update stats."""
import time
import cv2
import numpy as np
from ultralytics import YOLO

from pipeline.stats import MAX_FRAME_IDS_PER_WORKER


def run_worker(
    worker_id: int,
    input_queue,
    output_queue,
    worker_stats: dict,
    model_name: str = "yolov8n.pt",
):
    """Run in a separate process. Load YOLO once, then loop on input_queue."""
    model = YOLO(model_name)
    while True:
        try:
            item = input_queue.get()
            if item is None:
                break
            frame_index, jpeg_bytes = item
        except Exception as e:
            worker_stats["errors"] = worker_stats.get("errors", 0) + 1
            continue
        t0 = time.perf_counter()
        try:
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                worker_stats["errors"] = worker_stats.get("errors", 0) + 1
                continue
            results = model.predict(img, verbose=False)
            # Draw boxes on image
            out_img = results[0].plot()
            _, out_jpeg = cv2.imencode(".jpg", out_img)
            latency_ms = (time.perf_counter() - t0) * 1000
            output_queue.put((frame_index, out_jpeg.tobytes(), latency_ms))
            worker_stats["frames_processed"] = worker_stats.get("frames_processed", 0) + 1
            worker_stats["last_latency_ms"] = round(latency_ms, 2)
            frame_ids = worker_stats.get("frame_ids")
            if frame_ids is not None:
                frame_ids.append(frame_index)
                while len(frame_ids) > MAX_FRAME_IDS_PER_WORKER:
                    frame_ids.pop(0)
        except Exception as e:
            worker_stats["errors"] = worker_stats.get("errors", 0) + 1

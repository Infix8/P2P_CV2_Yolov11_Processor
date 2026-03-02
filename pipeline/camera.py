"""Lightweight camera capture: 640x480 JPEG frames at capped FPS (same format as file pipeline)."""
import time
import cv2

FRAME_SIZE = (640, 480)
CAMERA_FPS_CAP = 10


def capture_frames(device: int = 0, fps_cap: int = CAMERA_FPS_CAP, stop_flag=None):
    """
    Yield (frame_index, jpeg_bytes) from the default camera.
    stop_flag() should return True to stop (e.g. lambda: not camera_running).
    """
    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        raise ValueError(f"Cannot open camera device {device}")
    try:
        frame_index = 0
        interval = 1.0 / fps_cap if fps_cap > 0 else 0
        while True:
            if stop_flag and stop_flag():
                break
            ret, frame = cap.read()
            if not ret:
                break
            resized = cv2.resize(frame, FRAME_SIZE)
            _, jpeg_bytes = cv2.imencode(".jpg", resized)
            yield frame_index, jpeg_bytes.tobytes()
            frame_index += 1
            if interval > 0:
                time.sleep(interval)
    finally:
        cap.release()

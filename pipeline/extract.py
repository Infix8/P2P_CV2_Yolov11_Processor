"""Extract 640x480 JPEG frames from a video file."""
import cv2

FRAME_SIZE = (640, 480)
DEFAULT_FPS_CAP = 10  # limit frames per second to keep pipeline responsive


def extract_frames(video_path: str, fps_cap: int = DEFAULT_FPS_CAP):
    """
    Yield (frame_index, jpeg_bytes) for each frame.
    Resizes to 640x480 and encodes as JPEG.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    try:
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        interval = max(1, int(round(video_fps / fps_cap)))
        frame_index = 0
        read_index = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if read_index % interval == 0:
                resized = cv2.resize(frame, FRAME_SIZE)
                _, jpeg_bytes = cv2.imencode(".jpg", resized)
                yield frame_index, jpeg_bytes.tobytes()
                frame_index += 1
            read_index += 1
    finally:
        cap.release()

import subprocess
import numpy as np
import cv2
from ultralytics import YOLO

WIDTH, HEIGHT = 1280, 960

def start_ffmpeg():
    cmd = [
        "ffmpeg",
        "-protocol_whitelist", "file,udp,rtp",
        "-i", "stream.sdp",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "pipe:1"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=10**8)

def main():
    print("Loading YOLO model...")
    model = YOLO("yolov8n.pt")  # auto-downloads on first run

    proc = start_ffmpeg()
    frame_size = WIDTH * HEIGHT * 3

    print("Reading camera stream... press 'q' in the window to quit")

    try:
        while True:
            raw_frame = proc.stdout.read(frame_size)
            if len(raw_frame) != frame_size:
                print(f"Got {len(raw_frame)} bytes, expected {frame_size}")
                stderr_output = proc.stderr.read(2000)
                print("ffmpeg says:", stderr_output.decode(errors="ignore"))
                break

            frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3)).copy()

            # run YOLO detection on this frame
            results = model(frame, verbose=False)
            annotated_frame = results[0].plot()  # draws boxes + labels automatically

            # print what was detected, if anything
            if len(results[0].boxes) > 0:
                names = [model.names[int(cls)] for cls in results[0].boxes.cls]
                print("Detected:", names)

            cv2.imshow("Drone Camera - YOLO", annotated_frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    except Exception as e:
        print("Python error:", e)
    finally:
        proc.terminate()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
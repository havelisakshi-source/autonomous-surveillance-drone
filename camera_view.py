import subprocess
import numpy as np
import cv2

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

            frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
            cv2.imshow("Drone Camera", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    except Exception as e:
        print("Python error:", e)
    finally:
        proc.terminate()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
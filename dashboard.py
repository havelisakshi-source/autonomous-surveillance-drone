import asyncio
import subprocess
import threading
import time
from datetime import datetime
import numpy as np
import cv2
from ultralytics import YOLO
from mavsdk import System
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
import uvicorn

WIDTH, HEIGHT = 1280, 960
ALERT_LOG_FILE = "detections.csv"

drone_state = {"lat": None, "lon": None, "alt": None}
latest_frame = {"jpeg": None}
stop_camera = threading.Event()

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html>
    <head>
        <title>Drone Dashboard</title>
        <style>
            body { font-family: sans-serif; background: #111; color: #eee; text-align: center; }
            img { max-width: 90%; border: 2px solid #444; margin-top: 20px; }
            table { margin: 20px auto; border-collapse: collapse; }
            td, th { border: 1px solid #444; padding: 6px 12px; }
        </style>
    </head>
    <body>
        <h1>Autonomous Surveillance Drone - Live Feed</h1>
        <img src="/video">
        <h2>Recent Alerts</h2>
        <table id="alerts">
            <tr><th>Time</th><th>Label</th><th>Confidence</th><th>Lat</th><th>Lon</th><th>Alt</th></tr>
        </table>
        <script>
            async function loadAlerts() {
                const res = await fetch('/alerts');
                const data = await res.json();
                const table = document.getElementById('alerts');
                table.innerHTML = "<tr><th>Time</th><th>Label</th><th>Confidence</th><th>Lat</th><th>Lon</th><th>Alt</th></tr>";
                data.reverse().forEach(row => {
                    table.innerHTML += `<tr><td>${row[0]}</td><td>${row[1]}</td><td>${row[2]}</td><td>${row[3]}</td><td>${row[4]}</td><td>${row[5]}</td></tr>`;
                });
            }
            setInterval(loadAlerts, 2000);
            loadAlerts();
        </script>
    </body>
    </html>
    """


def mjpeg_generator():
    while True:
        if latest_frame["jpeg"] is not None:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + latest_frame["jpeg"] + b"\r\n")
        time.sleep(0.05)


@app.get("/video")
def video():
    return StreamingResponse(mjpeg_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/alerts")
def alerts():
    try:
        with open(ALERT_LOG_FILE, "r") as f:
            lines = f.readlines()[-10:]
        rows = [line.strip().split(",") for line in lines]
        return JSONResponse(rows)
    except FileNotFoundError:
        return JSONResponse([])


def start_ffmpeg():
    cmd = [
        "ffmpeg",
        "-protocol_whitelist", "file,udp,rtp",
        "-i", "stream.sdp",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "pipe:1"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)


def log_alert(label, confidence):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lat = drone_state["lat"]
    lon = drone_state["lon"]
    alt = drone_state["alt"]
    line = f"{now},{label},{confidence:.2f},{lat},{lon},{alt}\n"
    with open(ALERT_LOG_FILE, "a") as f:
        f.write(line)
    print(f"-- ALERT: {label} detected (conf {confidence:.2f}) at lat={lat}, lon={lon}, alt={alt}")


def camera_detection_loop():
    print("-- Loading YOLO model...")
    model = YOLO("yolov8n.pt")
    proc = start_ffmpeg()
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter('demo_recording.mp4', fourcc, 20.0, (WIDTH, HEIGHT))
    frame_size = WIDTH * HEIGHT * 3

    was_detected = False

    print("-- Camera detection thread started")

    while not stop_camera.is_set():
        raw_frame = proc.stdout.read(frame_size)
        if len(raw_frame) != frame_size:
            continue

        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3)).copy()
        results = model(frame, verbose=False)
        boxes = results[0].boxes

        person_found = False
        for box in boxes:
            label = model.names[int(box.cls)]
            confidence = float(box.conf)
            if label == "person":
                person_found = True
                if not was_detected:
                    log_alert(label, confidence)

        was_detected = person_found

        annotated_frame = results[0].plot()
        video_writer.write(annotated_frame)
        success, jpeg = cv2.imencode(".jpg", annotated_frame)
        if success:
            latest_frame["jpeg"] = jpeg.tobytes()

    proc.terminate()
    video_writer.release()
    print("-- Camera detection thread stopped")


def run_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


async def print_position(drone):
    async for position in drone.telemetry.position():
        drone_state["lat"] = round(position.latitude_deg, 6)
        drone_state["lon"] = round(position.longitude_deg, 6)
        drone_state["alt"] = round(position.relative_altitude_m, 1)


async def run():
    camera_thread = threading.Thread(target=camera_detection_loop, daemon=True)
    camera_thread.start()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print("-- Dashboard running at http://localhost:8000")

    drone = System()
    await drone.connect(system_address="udpin://0.0.0.0:14540")

    print("Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("-- Connected to drone!")
            break

    print("-- Waiting for drone to be ready to arm")
    async for health in drone.telemetry.health():
        if health.is_armable:
            print("-- Drone is ready to arm")
            break
        await asyncio.sleep(1)

    print("-- Reading home altitude")
    async for position in drone.telemetry.position():
        home_abs_alt = position.absolute_altitude_m
        break

    print("-- Arming")
    for attempt in range(10):
        try:
            await drone.action.arm()
            print("-- Armed successfully")
            break
        except Exception as e:
            print(f"Arm attempt {attempt+1} failed: {e}")
            await asyncio.sleep(2)

    position_task = asyncio.ensure_future(print_position(drone))

    try:
        print("-- Setting takeoff altitude")
        await drone.action.set_takeoff_altitude(5)

        print("-- Taking off")
        await drone.action.takeoff()
        await asyncio.sleep(8)

        waypoints = [
            (47.3980, 8.5460),
            (47.3982, 8.5462),
            (47.3980, 8.5464),
            (47.3978, 8.5462),
        ]
        target_alt = home_abs_alt + 10
        yaw = 0

        for i, (lat, lon) in enumerate(waypoints, start=1):
            print(f"-- Flying to waypoint {i}: {lat}, {lon}")
            await drone.action.goto_location(lat, lon, target_alt, yaw)
            await asyncio.sleep(12)

        print("-- Patrol complete, returning to launch")
        await drone.action.return_to_launch()

        async for is_armed in drone.telemetry.armed():
            if not is_armed:
                print("-- Landed and disarmed at home")
                break
            await asyncio.sleep(2)

    except Exception as e:
        print(f"-- Error during flight: {e}")
        await drone.action.return_to_launch()

    finally:
        position_task.cancel()
        # keep the dashboard running after landing so you can still browse it
        print("-- Flight complete. Dashboard still running at http://localhost:8000 — press Ctrl+C to stop everything.")
        while True:
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())
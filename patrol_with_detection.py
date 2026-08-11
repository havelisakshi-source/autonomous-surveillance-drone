import asyncio
import subprocess
import threading
import time
from datetime import datetime
import numpy as np
import cv2
from ultralytics import YOLO
from mavsdk import System

WIDTH, HEIGHT = 1280, 960
ALERT_LOG_FILE = "detections.csv"

# shared state between the flight loop and the camera thread
drone_state = {"lat": None, "lon": None, "alt": None}
stop_camera = threading.Event()


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
    frame_size = WIDTH * HEIGHT * 3

    was_detected = False  # tracks previous frame, to avoid duplicate alerts

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
                if not was_detected:  # only alert on NEW sighting
                    log_alert(label, confidence)

        was_detected = person_found

        annotated_frame = results[0].plot()
        cv2.imshow("Drone Camera - YOLO", annotated_frame)
        cv2.waitKey(1)

    proc.terminate()
    cv2.destroyAllWindows()
    print("-- Camera detection thread stopped")


async def print_position(drone):
    async for position in drone.telemetry.position():
        drone_state["lat"] = round(position.latitude_deg, 6)
        drone_state["lon"] = round(position.longitude_deg, 6)
        drone_state["alt"] = round(position.relative_altitude_m, 1)


async def run():
    # start the camera+YOLO thread in the background
    camera_thread = threading.Thread(target=camera_detection_loop, daemon=True)
    camera_thread.start()

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
        stop_camera.set()  # tell the camera thread to stop
        camera_thread.join(timeout=5)


asyncio.run(run())
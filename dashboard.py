import asyncio
import subprocess
import threading
import time
from datetime import datetime
import numpy as np
import cv2
from ultralytics import YOLO
from mavsdk import System
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
import uvicorn

WIDTH, HEIGHT = 1280, 960
ALERT_LOG_FILE = "detections.csv"

drone_state = {"lat": None, "lon": None, "alt": None}
mission_status = {"text": "Not started"}
alert_count = {"total": 0}
latest_frame = {"jpeg": None}
stop_camera = threading.Event()

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html>
    <head>
        <title>Drone Dashboard</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            body { font-family: sans-serif; background: #111; color: #eee; text-align: center; }
            img { max-width: 90%; border: 2px solid #444; margin-top: 20px; }
            table { margin: 20px auto; border-collapse: collapse; }
            td, th { border: 1px solid #444; padding: 6px 12px; }
        </style>
    </head>
    <body>
        <h1>Autonomous Surveillance Drone - Live Feed</h1>
        <h2 id="status">Status: Loading...</h2>
        <h2 id="alert_count">Total Alerts: 0</h2>
        <div id="map" style="height: 400px; width: 80%; margin: 20px auto;"></div>
        <button onclick="startMission()" style="padding: 10px 20px; font-size: 16px; margin-bottom: 20px;">Start Mission</button>
        <img src="/video">
        <h2>Recent Alerts</h2>
        <table id="alerts">
            <tr><th>Time</th><th>Label</th><th>Confidence</th><th>Lat</th><th>Lon</th><th>Alt</th></tr>
        </table>
        <script>
            var map = L.map('map').setView([47.397971, 8.546163], 17);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);
            L.marker([47.397971, 8.546163]).addTo(map).bindPopup("Home");
            L.rectangle([
                [47.397971 - 0.01, 8.546163 - 0.01],
                [47.397971 + 0.01, 8.546163 + 0.01]
            ], {color: "orange", weight: 2, fillOpacity: 0.05}).addTo(map).bindPopup("Safe zone boundary");
            var clickedWaypoints = [];

            var droneMarker = null;

            async function updateDronePosition() {
                const res = await fetch('/drone_position');
                const data = await res.json();
                if (data.lat !== null && data.lon !== null) {
                    if (droneMarker === null) {
                        droneMarker = L.marker([data.lat, data.lon], {
                            title: "Drone"
                        }).addTo(map).bindPopup("Drone");
                    } else {
                        droneMarker.setLatLng([data.lat, data.lon]);
                    }
                }
            }

            map.on('click', function(e) {
                var lat = e.latlng.lat.toFixed(6);
                var lon = e.latlng.lng.toFixed(6);
                clickedWaypoints.push([lat, lon]);
                L.marker([lat, lon]).addTo(map).bindPopup("Waypoint " + clickedWaypoints.length);
                console.log("Waypoints so far:", clickedWaypoints);

                if (flightPathLine !== null) {
                    map.removeLayer(flightPathLine);
                }
                if (clickedWaypoints.length > 1) {
                    flightPathLine = L.polyline(clickedWaypoints, {color: "cyan", weight: 3}).addTo(map);
                }
            });  

            var flightPathLine = null;

            async function startMission() {
                const response = await fetch('/set_waypoints', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({waypoints: clickedWaypoints})
                });
                const result = await response.json();
                alert("Mission sent: " + result.message);
            }

            async function loadAlerts() {
                const res = await fetch('/alerts');
                const data = await res.json();
                const table = document.getElementById('alerts');
                table.innerHTML = "<tr><th>Time</th><th>Label</th><th>Confidence</th><th>Lat</th><th>Lon</th><th>Alt</th></tr>";
                data.reverse().forEach(row => {
                    table.innerHTML += `<tr><td>${row[0]}</td><td>${row[1]}</td><td>${row[2]}</td><td>${row[3]}</td><td>${row[4]}</td><td>${row[5]}</td></tr>`;
                });
            }
            async function loadStatus() {
                const res = await fetch('/status');
                const data = await res.json();
                document.getElementById('status').innerText = "Status: " + data.text;
            }
            async function loadAlertCount() {
                const res = await fetch('/alert_count');
                const data = await res.json();
                document.getElementById('alert_count').innerText = "Total Alerts: " + data.total;
            }
            setInterval(loadAlerts, 2000);
            setInterval(loadStatus, 2000);
            setInterval(loadAlertCount, 2000);
            setInterval(updateDronePosition, 2000);
            loadAlerts();
            loadStatus();
            loadAlertCount();
            updateDronePosition();
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


mission_waypoints = {"list": []}


@app.get("/status")
def status():
    return {"text": mission_status["text"]}

@app.get("/drone_position")
def drone_position():
    return {"lat": drone_state["lat"], "lon": drone_state["lon"], "alt": drone_state["alt"]}


@app.get("/alert_count")
def get_alert_count():
    return {"total": alert_count["total"]}


@app.post("/set_waypoints")
async def set_waypoints(request: Request):
    data = await request.json()
    mission_waypoints["list"] = data["waypoints"]
    return {"message": f"Received {len(data['waypoints'])} waypoints"}


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
    if drone_state["lat"] is None:
        return
    alert_count["total"] += 1    
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
    fire_model = YOLO("fire_smoke.pt")
    proc = start_ffmpeg()
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter('demo_recording.mp4', fourcc, 6.0, (WIDTH, HEIGHT))
    frame_size = WIDTH * HEIGHT * 3

    was_detected = False
    was_fire_detected = False

    print("-- Camera detection thread started")

    while not stop_camera.is_set():
        raw_frame = proc.stdout.read(frame_size)
        if len(raw_frame) != frame_size:
            continue

        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3)).copy()
        results = model(frame, verbose=False)
        boxes = results[0].boxes

        all_labels = [model.names[int(box.cls)] for box in boxes]
        print("Frame sees:", all_labels)

        person_found = False
        for box in boxes:
            label = model.names[int(box.cls)]
            confidence = float(box.conf)
            if label == "person":
                person_found = True
                if not was_detected:
                    log_alert(label, confidence)

        fire_results = fire_model(frame, verbose=False)
        fire_boxes = fire_results[0].boxes
        fire_or_smoke_found = False
        for box in fire_boxes:
            label = fire_model.names[int(box.cls)]
            confidence = float(box.conf)
            if confidence > 0.5:
                fire_or_smoke_found = True
                if not was_fire_detected:
                    log_alert(label, confidence)                        

        was_detected = person_found
        
        was_fire_detected = fire_or_smoke_found

        annotated_frame = results[0].plot()
        annotated_frame = fire_results[0].plot(img=annotated_frame)
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

LOW_BATTERY_THRESHOLD = 20  # percent

async def monitor_battery(drone):
    async for battery in drone.telemetry.battery():
        percent = battery.remaining_percent * 100
        if percent < LOW_BATTERY_THRESHOLD:
            print(f"-- SAFETY: battery low ({percent:.0f}%), triggering return to launch")
            await drone.action.return_to_launch()
            break
        await asyncio.sleep(2)        

async def monitor_health(drone):
    async for health in drone.telemetry.health():
        if not health.is_local_position_ok or not health.is_global_position_ok:
            print("-- SAFETY: lost reliable position mid-flight, triggering return to launch")
            try:
                await drone.action.return_to_launch()
            except Exception as e:
                print(f"-- SAFETY: return_to_launch failed: {e}")
            break
        await asyncio.sleep(2)

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
    battery_task = asyncio.ensure_future(monitor_battery(drone))
    health_task = asyncio.ensure_future(monitor_health(drone))

    try:
        print("-- Setting takeoff altitude")
        await drone.action.set_takeoff_altitude(5)

        print("-- Taking off")
        await drone.action.takeoff()
        mission_status["text"] = "Taking off"
        await asyncio.sleep(15)  

        print("-- Waiting for you to click waypoints on the map and press Start Mission...")
        while len(mission_waypoints["list"]) == 0:
            await asyncio.sleep(1)

        waypoints = [(float(lat), float(lon)) for lat, lon in mission_waypoints["list"]]
        print(f"-- Received {len(waypoints)} waypoints from the map, starting mission")
        target_alt = home_abs_alt + 12
        yaw = 0

        # define a safe zone around home (roughly ±0.01 degrees, a few hundred meters)
        home_lat, home_lon = 47.397971, 8.546163
        GEOFENCE_RADIUS = 0.01

        for i, (lat, lon) in enumerate(waypoints, start=1):
            if abs(lat - home_lat) > GEOFENCE_RADIUS or abs(lon - home_lon) > GEOFENCE_RADIUS:
                print(f"-- SAFETY: waypoint {i} ({lat}, {lon}) is outside the geofence, skipping")
                continue
            print(f"-- Flying to waypoint {i}: {lat}, {lon}")
            await drone.action.goto_location(lat, lon, target_alt, yaw)
            await asyncio.sleep(12)

        print("-- Patrol complete, returning to launch")
        mission_status["text"] = "Returning to launch"
        await drone.action.return_to_launch()

        async for is_armed in drone.telemetry.armed():
            if not is_armed:
                print("-- Landed and disarmed at home")
                mission_status["text"] = "Landed"
                break
            await asyncio.sleep(2)

    except Exception as e:
        print(f"-- Error during flight: {e}")
        await drone.action.return_to_launch()

    finally:
        position_task.cancel()
        battery_task.cancel()
        health_task.cancel()
        # keep the dashboard running after landing so you can still browse it
        print("-- Flight complete. Dashboard still running at http://localhost:8000 — press Ctrl+C to stop everything.")
        while True:
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("-- Stopping...")
    finally:
        stop_camera.set()
        time.sleep(1)
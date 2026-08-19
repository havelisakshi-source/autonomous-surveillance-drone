# Autonomous Surveillance Drone

AI-powered multi-purpose autonomous drone project — built and tested entirely in simulation using PX4 SITL, Gazebo, and MAVSDK-Python before moving to real hardware.

## Current status
- PX4 SITL running via Docker (px4io/px4-sitl)
- Python script (MAVSDK) that connects to the simulated drone, waits for health checks, arms with automatic retries, takes off, flies a multi-waypoint patrol route, and automatically returns to launch and lands
- Built and tested on Ubuntu 26.04

## Stack
- PX4 Autopilot (SITL)
- Docker
- MAVSDK-Python
- Python 3.14

## Next steps
- Add camera feed via Gazebo simulation
- Integrate YOLO for object/person detection

## Verified working
- Confirmed autonomous flight: takeoff, multi-waypoint patrol, return-to-launch, clean landing
- Confirmed live camera feed from Gazebo (RTP video via ffmpeg)
- Confirmed YOLOv8 person detection on a spawned Gazebo model, correctly identified with high confidence

## Project Summary

Built and debugged an end-to-end autonomous drone system in simulation: PX4 flight control (Docker-based SITL), MAVSDK-Python for autonomous multi-waypoint patrol with automatic return-to-home, a live camera feed streamed from Gazebo via RTP/ffmpeg, real-time YOLOv8 person detection, GPS-tagged alert logging, and a FastAPI web dashboard showing the live feed and recent alerts.

Along the way, debugged real infrastructure issues rather than following a fixed tutorial: Docker port-binding conflicts between the container's proxy and the local script, PX4 preflight/arming-check failures requiring a proper health-check retry loop, RTP video stream decoding via ffmpeg subprocess piping (no GStreamer dependency), and coordinating an async flight loop with a background video-processing thread sharing live GPS state.

## Update (Aug 13)
- Fixed a bug where alerts logged before the drone's first GPS fix showed None for coordinates — now guarded so alerts only log once real position data is available
- Fixed fire/smoke detection spamming low-confidence false positives — added a confidence threshold (>0.5) and deduplication, matching the person-detection logic
- Fixed video recording corruption caused by abrupt shutdown on Ctrl+C — the camera thread now closes and finalizes the video file properly before exit
- Fixed video playback lag by correcting the declared frame rate to match actual capture speed
- Diagnosed and resolved a host-level network issue (Docker multicast traffic being rejected) that was silently blocking PX4 from becoming armable — required a full system restart to clear

## Update (Aug 14)
- Added a live mission status indicator to the dashboard (Not started / Taking off / Returning to launch / Landed), polled every 2 seconds alongside the alerts table
- Added geofencing, low-battery return-to-home, and health-based safety monitoring to the flight logic

## Update (Aug 19)
- Added an interactive mission-planner map (Leaflet.js) to the dashboard — click anywhere on the map to set waypoints, then press "Start Mission" to send them to the drone in real time, replacing the previous hardcoded waypoint list
- Fixed two structural bugs during development: a Python scoping issue where routes were accidentally nested inside another function, and a matching JavaScript issue where the map setup and mission button were nested inside a function that ran on a timer, silently breaking both

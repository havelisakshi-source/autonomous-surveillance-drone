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

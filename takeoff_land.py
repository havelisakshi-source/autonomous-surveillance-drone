import asyncio
from mavsdk import System

async def print_position(drone):
    async for position in drone.telemetry.position():
        print(f"lat: {position.latitude_deg:.6f}, lon: {position.longitude_deg:.6f}, alt: {position.relative_altitude_m:.1f}m")

async def run():
    drone = System()
    await drone.connect(system_address="udpin://0.0.0.0:14540")

    print("Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("-- Connected to drone!")
            break

    print("-- Waiting for drone to be ready to arm")
    async for health in drone.telemetry.health():
        print("global_position_ok:", health.is_global_position_ok,
              "home_position_ok:", health.is_home_position_ok,
              "local_position_ok:", health.is_local_position_ok,
              "armable:", health.is_armable)
        if health.is_armable:
            print("-- Drone is ready to arm")
            break
        await asyncio.sleep(1)

    print("-- Reading home altitude")
    async for position in drone.telemetry.position():
        home_abs_alt = position.absolute_altitude_m
        print(f"Home absolute altitude: {home_abs_alt:.1f}m AMSL")
        break

    print("-- Arming")
    armed = False
    for attempt in range(10):
        try:
            await drone.action.arm()
            print("-- Armed successfully")
            armed = True
            break
        except Exception as e:
            print(f"Arm attempt {attempt+1} failed: {e}")
            await asyncio.sleep(2)

    if not armed:
        print("-- Could not arm after multiple attempts, exiting")
        return

    position_task = None

    try:
        print("-- Setting takeoff altitude")
        await drone.action.set_takeoff_altitude(5)

        print("-- Taking off")
        await drone.action.takeoff()
        await asyncio.sleep(8)

        position_task = asyncio.ensure_future(print_position(drone))

        # patrol route: small offsets from home, forming a simple loop
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
            await asyncio.sleep(12)  # give it time to arrive before the next leg

        print("-- Patrol complete, returning to launch")
        await drone.action.return_to_launch()

        # wait until it's actually landed and disarmed before ending the script
        async for is_armed in drone.telemetry.armed():
            if not is_armed:
                print("-- Landed and disarmed at home")
                break
            await asyncio.sleep(2)

    except Exception as e:
        print(f"-- Error during flight: {e}")
        print("-- Triggering emergency return to launch")
        await drone.action.return_to_launch()

    finally:
        if position_task:
            position_task.cancel()

asyncio.run(run())
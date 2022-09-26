#!/usr/bin/env python

###############################################
# Copyright (c) Shiv Patel, 2022
# BC, Canada.
# The University of British Columbia, Okanagan
###############################################

import multiprocessing
import psutil
import time
import os
import sys
import glob

try:
    sys.path.append(glob.glob('..\\carla\\dist\\carla-0.9.13-py*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

import carla
import utils
import logging
from numpy import random
import TTS
def get_actor_blueprints(world, filter, generation):
    bps = world.get_blueprint_library().filter(filter)

    if generation.lower() == "all":
        return bps

    # If the filter returns only one bp, we assume that this one needed
    # and therefore, we ignore the generation
    if len(bps) == 1:
        return bps

    try:
        int_generation = int(generation)
        # Check if generation is in available generations
        if int_generation in [1, 2]:
            bps = [x for x in bps if int(x.get_attribute('generation')) == int_generation]
            return bps
        else:
            print("   Warning! Actor Generation is not valid. No actor will be spawned.")
            return []
    except:
        print("   Warning! Actor Generation is not valid. No actor will be spawned.")
        return []


def run(CONTENT_FOLDER_PATH):

    ################## Signal Reading and software logging ##################
    SIGNAL_FILE_PATH = "{}{}".format(CONTENT_FOLDER_PATH, "/ConfigFiles/SignalFile.txt")
    DATA_FOLDER_PATH = "{}{}".format(CONTENT_FOLDER_PATH, "/DataFiles")
    CONFIG_FILE_PATH = "{}{}".format(CONTENT_FOLDER_PATH, "/ConfigFiles/config.txt")
    RSVP_STREAM_FILE = "{}{}".format(CONTENT_FOLDER_PATH, "/ConfigFiles/TTSStreamFile.txt")

    configurations = utils.read_config_file(CONFIG_FILE_PATH)
    print("Extracted settings: " + str(configurations))
    #########################################################################

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    vehicles_list = []
    client = carla.Client('127.0.0.1', 2000)
    client.set_timeout(10.0)
    synchronous_master = False

    try:
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)
        world = client.get_world()
        world.set_weather(carla.WeatherParameters.MidRainyNoon)

        traffic_manager = client.get_trafficmanager()
        traffic_manager.set_global_distance_to_leading_vehicle(2)
        settings = world.get_settings()
        traffic_manager.set_synchronous_mode(True)
        if not settings.synchronous_mode:   
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 1.0/80
        world.tick()

        blueprints = get_actor_blueprints(world, 'vehicle.*', 'All')
        blueprints = [bp for bp in blueprints if "dreyevr" not in bp.id and int(bp.get_attribute('number_of_wheels')) != 2]
        blueprints = sorted(blueprints, key=lambda bp: bp.id)

        #####:EDIT:#####
        number_of_vehicles = 40
        #####:EDIT:#####
        
        spawn_points = world.get_map().get_spawn_points()
        number_of_spawn_points = len(spawn_points)

        if number_of_vehicles < number_of_spawn_points:
            random.shuffle(spawn_points)
        elif number_of_vehicles > number_of_spawn_points:
            msg = 'requested %d vehicles, but could only find %d spawn points'
            logging.warning(msg, number_of_vehicles, number_of_spawn_points)
            number_of_vehicles = number_of_spawn_points

        # @todo cannot import these directly.
        SpawnActor = carla.command.SpawnActor
        SetAutopilot = carla.command.SetAutopilot
        FutureActor = carla.command.FutureActor

        # --------------
        # Spawn vehicles
        # --------------
        batch = []
        for n, transform in enumerate(spawn_points):
            if n >= number_of_vehicles:
                break
            blueprint = random.choice(blueprints)
            if blueprint.has_attribute('color'):
                color = random.choice(blueprint.get_attribute('color').recommended_values)
                blueprint.set_attribute('color', color)
            if blueprint.has_attribute('driver_id'):
                driver_id = random.choice(blueprint.get_attribute('driver_id').recommended_values)
                blueprint.set_attribute('driver_id', driver_id)

            # spawn the cars and set their autopilot and light state all together
            batch.append(SpawnActor(blueprint, transform)
                         .then(SetAutopilot(FutureActor, True, 8000)))

        for response in client.apply_batch_sync(batch, synchronous_master):
            if response.error:
                logging.error(response.error)
            else:
                vehicles_list.append(response.actor_id)

        # Set automatic vehicle lights
        all_vehicle_actors = world.get_actors(vehicles_list)
        for actor in all_vehicle_actors:
            traffic_manager.update_vehicle_lights(actor, True)

        # Increase the speed of the spawned and ego vehicle (in autopilot mode)
        traffic_manager.global_percentage_speed_difference(-500.0)

        # Enable autonomous mode for the ego-vehicle while doing the reading task.
        DReyeVR_vehicle = utils.find_ego_vehicle(world)
        traffic_manager.auto_lane_change(DReyeVR_vehicle, False)
        DReyeVR_vehicle.set_autopilot(True, traffic_manager.get_port())
        TOR_waypoint = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(1300)[0]
        print("Successfully set autopilot on ego vehicle.")

        # Give a signal to start reading comprehension task
        utils.write_signal_file(SIGNAL_FILE_PATH, 0)
        print("Starting reading comprehension task.")

       # Once the reading task starts, run the TTS process if TTS is enabled.
        try:
            string = utils.extract_text(CONTENT_FOLDER_PATH + "/ConfigFiles/" + configurations["TEXTFILE"] + ".txt")
            if int(configurations["TTS"]) == 1:
                process = multiprocessing.Process(target=TTS.speak, args=(RSVP_STREAM_FILE, string, int(configurations["WPM"]), 0, 1.0))
                process.start()
        except Exception as e:
            print("Unable to start TTS process:", str(e))

        # Disable autopilot and issue the TOR when the vehicle is close to the TOR waypoint
        while DReyeVR_vehicle.get_location().distance(TOR_waypoint.transform.location) > 100:
            world.tick()
        # Pause the TTS process if it was executed
        try:
            if int(configurations["TTS"]) == 1:
                process_ps = psutil.Process(process.pid)
                process_ps.suspend()
        except:
            print("Unable to pause process")
        print("TOR is issued.")

        # Execute TOR scenerio
        # Disable autopilot once TOR is issued
        utils.write_signal_file(SIGNAL_FILE_PATH, 1)
        DReyeVR_vehicle.set_autopilot(False, traffic_manager.get_port())
        print("Autopilot disabled")
        world.tick()

        # Generate Extreme weather conditions
        old_weather = generate_fog(world)
        print("Extreme weather set")
        world.tick()

        # Measure handover performance
        collision_data = []
        lane_offset_data = []
        # Start detecting collisions
        utils.collision_performance(carla, world, DReyeVR_vehicle, collision_data)

        target_time = time.time() + 10
        last_logged_at = -1
        while time.time() < target_time:
            lane_offset, logged_at = utils.get_lane_offset(world, DReyeVR_vehicle, last_logged_at)
            if lane_offset is not None and logged_at is not None:
                lane_offset_data.append(lane_offset)
                last_logged_at = logged_at

            world.tick()

        # Write the TOR performance data to the CSV files
        utils.write_performance_data(DATA_FOLDER_PATH, configurations, lane_offset_data, collision_data)
        
        # Revert back original conditions i.e., normal weather
        set_to_weather(world, old_weather)
        DReyeVR_vehicle.set_autopilot(True, traffic_manager.get_port())
        world.tick()

        # After n seconds, send signal "2" to continue with the NDRT Task
        utils.write_signal_file(SIGNAL_FILE_PATH, 2)
        utils.wait(world, 3)
        # Resume the TTS process if it was executed
        try:
            if int(configurations["TTS"]) == 1:
                process_ps.resume()
        except:
            print("Unable to resume the process")

        # Wait for the NDRT to complete
        utils.wait_for_NDRT(SIGNAL_FILE_PATH, world)
        utils.wait(world, 5)

        # Exit the program and disconnect the CARLA client connection
    finally:
        settings = world.get_settings()
        settings.synchronous_mode = False
        settings.no_rendering_mode = False
        settings.fixed_delta_seconds = None
        world.apply_settings(settings)

        print('\ndestroying %d non-ego vehicles' % len(vehicles_list))
        client.apply_batch([carla.command.DestroyActor(x) for x in vehicles_list])

        DReyeVR_vehicle.set_autopilot(False, traffic_manager.get_port())
        DReyeVR_vehicle.enable_constant_velocity(carla.Vector3D(0, 0, 0))
        DReyeVR_vehicle.apply_control(carla.VehicleControl(throttle=0, brake=1, manual_gear_shift=False, gear=0))
        print("Successfully set manual control on ego vehicle")

def generate_fog(world):
  old_weather = world.get_weather()
  for i in range(20, 61, 5):
    new_weather = carla.WeatherParameters(
      cloudiness=old_weather.cloudiness,
      precipitation=old_weather.precipitation,
      precipitation_deposits=old_weather.precipitation_deposits,
      wind_intensity=old_weather.wind_intensity,
      sun_azimuth_angle=old_weather.sun_azimuth_angle,
      sun_altitude_angle=old_weather.sun_altitude_angle,
      fog_density=i,
      fog_distance=old_weather.fog_distance,
      wetness=old_weather.wetness,
      fog_falloff=old_weather.fog_falloff,
      scattering_intensity=old_weather.scattering_intensity,
      mie_scattering_scale=old_weather.mie_scattering_scale,
      rayleigh_scattering_scale=old_weather.rayleigh_scattering_scale
    )
    world.set_weather(new_weather)
    utils.wait(world, 0.5)
  return old_weather

def set_to_weather(world, weather):
  world.set_weather(weather)
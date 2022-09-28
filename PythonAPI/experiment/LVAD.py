#!/usr/bin/env python

###############################################
# Copyright (c) Shiv Patel, 2022
# BC, Canada.
# The University of British Columbia, Okanagan
###############################################

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
import multiprocessing
import psutil
import TTS

import random
import logging
from numpy import random


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

    try:
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)
        world = client.get_world()
        world.set_weather(carla.WeatherParameters.MidRainyNoon)

        traffic_manager = client.get_trafficmanager()
        traffic_manager.set_global_distance_to_leading_vehicle(0.1)
        settings = world.get_settings()
        traffic_manager.set_synchronous_mode(True)
        if not settings.synchronous_mode:   
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 1.0/80
        world.tick()


        blueprints = get_actor_blueprints(world, 'vehicle.*', 'All')
        blueprints = [bp for bp in blueprints if "dreyevr" not in bp.id and int(bp.get_attribute('number_of_wheels')) != 2]
        blueprints = sorted(blueprints, key=lambda bp: bp.id)

        # Increase the speed of the spawned and ego vehicle (in autopilot mode)
        traffic_manager.global_percentage_speed_difference(-400.0)

        # Enable autonomous mode for the ego-vehicle while doing the reading task.
        DReyeVR_vehicle = utils.find_ego_vehicle(world)
        print(DReyeVR_vehicle, DReyeVR_vehicle.get_location())
        traffic_manager.auto_lane_change(DReyeVR_vehicle, False)
        DReyeVR_vehicle.set_autopilot(True, traffic_manager.get_port())
        print("Successfully set autopilot on ego vehicle.")
        
        # Spawn vehicles in adjacent lanes
        print("Spawning adjacent vehicles")
        spawn_adjacent_vehicles(world, traffic_manager, DReyeVR_vehicle, vehicles_list, blueprints)

        # Give a signal to start reading comprehension task
        utils.write_signal_file(SIGNAL_FILE_PATH, 0)
        print("Starting reading comprehension task.")

       # Once the reading task starts, run the TTS process if TTS is enabled.
        try:
            string = utils.extract_text(CONTENT_FOLDER_PATH + "/ConfigFiles/" + configurations["TEXTFILE"] + ".txt")
            if int(configurations["TTS"]) == 1:
                process = multiprocessing.Process(target=TTS.speak, args=(RSVP_STREAM_FILE, string, int(configurations["WPM"]), 25, 1.0))
                process.start()
        except Exception as e:
            print("Unable to start TTS process:", str(e))

        # Execute TOR scenerio
        print("Leading Vehicle Abrupt Deceleration scenario executing.")
        danger_vehicle_bp = world.get_blueprint_library().find('vehicle.ford.mustang')
        danger_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(1300)[0].transform
        danger_transform.location.z += 1

        danger_vehicle = world.spawn_actor(
            blueprint=danger_vehicle_bp,
            transform=danger_transform)
        print("spawned danger vehicle.")

        # Wait for the ego vehicle to come under 50 meters from the danger vehicle's spawn point
        while DReyeVR_vehicle.get_location().distance(danger_transform.location) > 50:
            world.tick()
        
        # Pause the TTS process if it was executed
        try:
            if int(configurations["TTS"]) == 1:
                process_ps = psutil.Process(process.pid)
                process_ps.suspend()
        except:
            print("Unable to pause process")
        print("TOR is issued")
        DReyeVR_vehicle.set_autopilot(False, traffic_manager.get_port())
        print("Autopilot disabled")
        world.tick()

        # Issue TOR and write to signal file
        utils.write_signal_file(SIGNAL_FILE_PATH, 1)
        DReyeVR_vehicle.set_autopilot(False, 8000)
        world.tick()
        
        # Measure handover performance
        collision_data = []
        lane_offset_data = []
        # Start detecting collisions
        utils.collision_performance(carla, world, DReyeVR_vehicle, collision_data)

        target_time = time.time() + 5
        last_logged_at = -1
        while time.time() < target_time:
            # Measure handover performance: Check for AP, and SDLP
            lane_offset, logged_at = utils.get_lane_offset(world, DReyeVR_vehicle, last_logged_at)
            if lane_offset is not None and logged_at is not None:
                lane_offset_data.append(lane_offset)
                last_logged_at = logged_at
            world.tick()

        # Write the TOR performance data to the CSV files
        utils.write_performance_data(DATA_FOLDER_PATH, configurations, lane_offset_data, collision_data, "LVAD")

        # Revert back original conditions i.e., danger_vehicle = safe_vehicle
        danger_vehicle.disable_constant_velocity()
        danger_vehicle.set_autopilot(True, traffic_manager.get_port())
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
    except Exception as e:
        print(e)
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

def spawn_adjacent_vehicles(world, traffic_manager, DReyeVR_vehicle, vehicles_list, blueprint_library):
    left_next = -50
    right_next = -50

    for i in range(0, 3, 1):
        left_next += random.randint(15, 30)
        right_next += random.randint(15, 30)
        left_next = 1 if left_next == 0 else left_next
        right_next = 1 if right_next == 0 else right_next

        vehicle_left_bp = random.choice(blueprint_library)
        vehicle_right_bp = random.choice(blueprint_library)

        if (left_next < 0):
            left_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()
                                                          ).previous(abs(left_next))[0].get_left_lane().transform
        else:
            left_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()
                                                          ).next(left_next)[0].get_left_lane().transform

        if (right_next < 0):
            right_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()
                                                           ).previous(abs(right_next))[0].get_right_lane().transform
        else:
            right_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()
                                                           ).next(right_next)[0].get_right_lane().transform

        left_transform.location.z += 1
        right_transform.location.z += 1

        world.tick()
        vehicle_left = world.spawn_actor(vehicle_left_bp, left_transform)
        world.tick()
        vehicle_right = world.spawn_actor(vehicle_right_bp, right_transform)

        if vehicle_left is not None:
            vehicle_left.set_autopilot(True, 8000)
            traffic_manager.auto_lane_change(vehicle_left, False)
            vehicles_list.append(vehicle_left)
        if vehicle_right is not None:
            vehicle_right.set_autopilot(True, 8000)
            traffic_manager.auto_lane_change(vehicle_right, False)
            vehicles_list.append(vehicle_right)
        world.tick()

#!/usr/bin/env python

###############################################
# Copyright (c) Shiv Patel, 2022
# BC, Canada.
# The University of British Columbia, Okanagan
###############################################

from asyncore import write
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
    SENTENCE_INDEX_FILE = "{}{}".format(CONTENT_FOLDER_PATH, "/ConfigFiles/SentenceIndexFile.txt")

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

        traffic_manager = client.get_trafficmanager(8000)
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

        # Increase the speed of the spawned and ego vehicle (in autopilot mode)
        traffic_manager.global_percentage_speed_difference(-400.0)

        # Enable autonomous mode for the ego-vehicle while doing the reading task.
        DReyeVR_vehicle = utils.find_ego_vehicle(world)
        traffic_manager.auto_lane_change(DReyeVR_vehicle, False)
        DReyeVR_vehicle.set_autopilot(True, traffic_manager.get_port())
        print("Successfully set autopilot on ego vehicle.")
        
        # TODO: Spawn vehicles in adjacent lanes
        print("Spawning adjacent vehicles")
        spawn_adjacent_vehicles(world, traffic_manager, DReyeVR_vehicle, vehicles_list, blueprints)

        # Give a signal to start reading comprehension task
        utils.write_signal_file(SIGNAL_FILE_PATH, 0)
        print("Starting reading comprehension task.")

       # Once the reading task starts, run the TTS process if TTS is enabled.
        try:
            string = utils.extract_text(CONTENT_FOLDER_PATH + "/ConfigFiles/" + configurations["TEXTFILE"] + ".txt")
            volume = 1.0 if int(configurations["TTS"]) == 1 else 0
            process = multiprocessing.Process(target=TTS.speak, args=(RSVP_STREAM_FILE, SENTENCE_INDEX_FILE, string, int(configurations["WPM"]), 25, volume))
            process.start()
        except Exception as e:
            print("Unable to start TTS process:", str(e))

        # Execute TOR scenerio
        animal_bp = world.get_blueprint_library().filter(("static.prop.Buffalo").lower())
        assert len(animal_bp) == 1 # you should only have one prop of this name

        # LLT: Left Lane Transform, RLT: Right Lane Transform, MLW: Middle Lane Waypoint
        mlw = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(1300)[0]
        mlw2 = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(1305)[0]
        mlw3 = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(1310)[0]

        llt = mlw.get_left_lane().transform
        rlt = mlw.get_right_lane().transform
        llt2 = mlw2.get_left_lane().transform
        rlt2 = mlw2.get_right_lane().transform
        llt3 = mlw3.get_left_lane().transform
        rlt3 = mlw3.get_right_lane().transform

        rlt.location.z = 0.1
        rlt.rotation.yaw += 180          # Warning: May need to Change
        llt.location.z = 0.1
        rlt2.location.z = 0.1
        rlt2.rotation.yaw += 180          # Warning: May need to Change
        llt2.location.z = 0.1
        rlt3.location.z = 0.1
        rlt3.rotation.yaw += 180          # Warning: May need to Change
        llt3.location.z = 0.1

        # Spawn the animals on the right lane
        animal_stationary = world.spawn_actor(animal_bp[0], rlt)
        animal_crossing_slow = world.spawn_actor(animal_bp[0], rlt2)
        animal_crossing_fast = world.spawn_actor(animal_bp[0], rlt3)

        # Disable autopilot and issue the TOR when the vehicle is close to the animal
        while DReyeVR_vehicle.get_location().distance(mlw.transform.location) > 125:
            world.tick()

        # Pause the TTS process if it was executed
        try:
            process_ps = psutil.Process(process.pid)
            if int(configurations["RSVP"]) == 1:
                process_ps.terminate()
                utils.reset_stream_file(RSVP_STREAM_FILE)
            else:
                process_ps.suspend()
        except:
            print("Unable to pause process")
        
        print("TOR is issued")

        # Issue TOR and write to signal file
        utils.write_signal_file(SIGNAL_FILE_PATH, 1)

        # Disable autopilot for the ego-vehicle
        DReyeVR_vehicle.set_autopilot(False, 8000)
        origin_point = DReyeVR_vehicle.get_location()

        # Measure handover performance
        collision_data = []
        lane_offset_data = []
        # Start detecting collisions
        utils.collision_performance(carla, world, DReyeVR_vehicle, collision_data)
        last_logged_at = -1

        # Calculate distances from the origin point
        dist_ego = origin_point.distance(DReyeVR_vehicle.get_location())
        dist_animal = origin_point.distance(mlw3.transform.location)

        # Move the animal from the left lane to the right lane
        # Number 1: Stationary animal, Number 2: slow crossing animal, Number 3: Fast crossing animal
        lane_vector2 = carla.Vector3D(llt2.location.x - rlt2.location.x, llt2.location.y - rlt2.location.y, llt2.location.z-rlt2.location.z)
        distance2 = lane_vector2.length() + 5 # Plus 5 extra meters to move out of the road
        lane_vector3 = carla.Vector3D(llt3.location.x - rlt3.location.x, llt3.location.y - rlt3.location.y, llt3.location.z-rlt3.location.z)
        distance3 = lane_vector3.length() + 5 # Plus 5 extra meters to move out of the road
        alfa_slow = 0.05
        alfa_fast = 0.1

        # Turn autopilot when (1) Animal has crossed the road,
        # or (2) Animal is far away from the car.
        while dist_ego - dist_animal <= 20:
            # Measure Handover performance for +n seconds
            lane_offset, logged_at = utils.get_lane_offset(world, DReyeVR_vehicle, last_logged_at)
            if lane_offset is not None and logged_at is not None:
                lane_offset_data.append(lane_offset)
                last_logged_at = logged_at

            # Shift the slow animal across the road by one step.
            new_location = animal_crossing_slow.get_location() + alfa_slow*lane_vector2.make_unit_vector()
            animal_crossing_slow.set_location(new_location)

            # Shift the fast animal across the road by one step.
            new_location = animal_crossing_fast.get_location() + alfa_fast*lane_vector3.make_unit_vector()
            animal_crossing_fast.set_location(new_location)

            # Update the distances
            dist_ego = origin_point.distance(DReyeVR_vehicle.get_location())
            dist_animal = origin_point.distance(mlw.transform.location)

            world.tick()

        # Write the TOR performance data to the CSV files
        utils.write_performance_data(DATA_FOLDER_PATH, configurations, lane_offset_data, collision_data, "ACR")

        # Turn on autopilot again once TOR is fulfilled.
        DReyeVR_vehicle.set_autopilot(True, 8000)
        utils.write_signal_file(SIGNAL_FILE_PATH, 2)
        utils.wait(world, 3)
        # Resume the TTS process if it was executed
        try:
            if int(configurations["RSVP"]) == 1:
                file = open(SENTENCE_INDEX_FILE, "r")
                sentence_index = int(file.read())
                new_string = string[sentence_index:]
                process = multiprocessing.Process(target=TTS.speak, args=(RSVP_STREAM_FILE, SENTENCE_INDEX_FILE, new_string, int(configurations["WPM"]), 25, volume))
                process.start()
            else:
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


def spawn_adjacent_vehicles(world, traffic_manager, DReyeVR_vehicle, vehicles_list, blueprint_library):
        left_next = -10
        right_next = -10
        for i in range(0, 2, 1):
            left_next += random.randint(15, 30)
            right_next += random.randint(15, 30)
            left_next = 1 if left_next == 0 else left_next
            right_next = 1 if right_next == 0 else right_next

            vehicle_left_bp = random.choice(blueprint_library)
            vehicle_right_bp = random.choice(blueprint_library)

            if (left_next < 0):
                left_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).previous(abs(left_next))[0].get_left_lane().transform
            else:
                left_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(left_next)[0].get_left_lane().transform

            if (right_next < 0):
                right_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).previous(abs(right_next))[0].get_right_lane().transform
            else:
                right_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(right_next)[0].get_right_lane().transform

            left_transform.location.z += 1
            right_transform.location.z += 1

            vehicle_left = world.try_spawn_actor(vehicle_left_bp, left_transform)
            vehicle_right = world.try_spawn_actor(vehicle_right_bp, right_transform)

            if vehicle_left is not None:
                vehicle_left.set_autopilot(True, 8000)
                traffic_manager.auto_lane_change(vehicle_left, False)
                vehicles_list.append(vehicle_left)
            if vehicle_right is not None:
                vehicle_right.set_autopilot(True, 8000)
                traffic_manager.auto_lane_change(vehicle_right, False)
                vehicles_list.append(vehicle_right)
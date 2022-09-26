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
import TTS

import multiprocessing
import psutil
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

        traffic_manager = client.get_trafficmanager(8000)
        traffic_manager.set_global_distance_to_leading_vehicle(2)
        traffic_manager.global_percentage_speed_difference(-400)
        settings = world.get_settings()
        traffic_manager.set_synchronous_mode(True)
        if not settings.synchronous_mode:   
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 1.0/80
        world.tick()
        
        blueprints = get_actor_blueprints(world, 'vehicle.*', 'All')
        blueprints = [bp for bp in blueprints if "dreyevr" not in bp.id and int(
            bp.get_attribute('number_of_wheels')) != 2]
        blueprints = sorted(blueprints, key=lambda bp: bp.id)

        # Enable autonomous mode for the ego-vehicle while doing the reading task.
        DReyeVR_vehicle = utils.find_ego_vehicle(world)
        traffic_manager.auto_lane_change(DReyeVR_vehicle, False)
        DReyeVR_vehicle.set_autopilot(True, 8000)
        print("Successfully set autopilot on ego vehicle.")

        # Spawn vehicles in adjacent lanes
        print("Spawning adjacent vehicles")
        left_vehicles, right_vehicles = spawn_vehicles(world, traffic_manager, DReyeVR_vehicle, vehicles_list, blueprints)

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
                

        # Execute TOR scenerio
        # Spawn lane block barriers in the non-ego vehicles lane
        lane_block_bp = world.get_blueprint_library().filter(("static.prop.LaneBlock").lower())
        assert len(lane_block_bp) == 1  # you should only have one prop of this name

        # Spawn the JCB in front of the rightmost and the leftmost barrier to make it more realistic
        jcb_bp = world.get_blueprint_library().filter(("static.prop.JCB").lower())
        assert len(jcb_bp) == 1  # you should only have one prop of this name

        barrier_waypoint = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(1300)[0]

        # Spawn all the barries to the right
        lane = barrier_waypoint
        while lane.lane_change == carla.LaneChange.Right or lane.lane_change == carla.LaneChange.Both:
            lane = lane.get_right_lane()
            lb_right_transform = lane.transform
            lb_right_transform.rotation.yaw += 90               # Warning: May need to Change
            world.spawn_actor(lane_block_bp[0], lb_right_transform)

        # Spawn JCB to the rightmost lane
        jcb_right_transform = lane.next(6)[0].transform
        jcb_right_transform.rotation.yaw += 90
        jcb_right = world.spawn_actor(jcb_bp[0], jcb_right_transform)        
        world.tick()

        # Spawn all the barries to the left
        lane = barrier_waypoint
        while lane.lane_change == carla.LaneChange.Left or lane.lane_change == carla.LaneChange.Both:
            lane = lane.get_left_lane()
            lb_left_transform = lane.transform
            lb_left_transform.rotation.yaw += 90
            world.spawn_actor(lane_block_bp[0], lb_left_transform)

        # Spawn JCB to the rightmost lane
        jcb_left_transform = lane.transform
        jcb_left_transform.rotation.yaw -= 90
        jcb_left = world.spawn_actor(jcb_bp[0], jcb_left_transform)
        world.tick()
        print("Spawned the complete construction site.")

        # Disable autopilot and issue the TOR when the vehicle is close to the construction site
        while DReyeVR_vehicle.get_location().distance(barrier_waypoint.transform.location) > 100:
            world.tick()
            stop_at_barrier(world,traffic_manager, barrier_waypoint,left_vehicles, right_vehicles)
        
        # Issue TOR and write to signal file
        utils.write_signal_file(SIGNAL_FILE_PATH, 1)
        DReyeVR_vehicle.set_autopilot(False, 8000)
        world.tick()

        # Pause the TTS process if it was executed
        try:
            if int(configurations["TTS"]) == 1:
                process_ps = psutil.Process(process.pid)
                process_ps.suspend()
        except:
            print("Unable to pause process")
        
        print("TOR is issued")

        origin_point = DReyeVR_vehicle.get_location()
        
        # Measure handover performance until the barrier passes
        collision_data = []
        lane_offset_data = []
        # Start detecting collisions
        utils.collision_performance(carla, world, DReyeVR_vehicle, collision_data)
        last_logged_at = -1

        dist_ego = origin_point.distance(DReyeVR_vehicle.get_location())
        dist_barrier = origin_point.distance(barrier_waypoint.transform.location)
        
        while dist_ego - dist_barrier <= 20:
            world.tick()
            # Measure handover performance: Check for AP, and SDLP
            lane_offset, logged_at = utils.get_lane_offset(world, DReyeVR_vehicle, last_logged_at)
            if lane_offset is not None and logged_at is not None:
                lane_offset_data.append(lane_offset)
                last_logged_at = logged_at

            # Stop the spawned vehicles at the come close to the barrier to avoid collision
            stop_at_barrier(world, traffic_manager, barrier_waypoint, left_vehicles, right_vehicles)
            
            dist_ego = origin_point.distance(DReyeVR_vehicle.get_location())
            dist_barrier = origin_point.distance(barrier_waypoint.transform.location)

        print("Ego vehicle passed the barrier.")

        # Write the handover performance to the CSV files.
        utils.write_performance_data(DATA_FOLDER_PATH, configurations,lane_offset_data, collision_data)

        # When the barrier passes the ego-vehicle, turn on the autopilot mode and send signal "2"
        DReyeVR_vehicle.set_autopilot(True, 8000)
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



def spawn_vehicles(world, traffic_manager, DReyeVR_vehicle, vehicles_list, blueprints):
    # Spawn a vehicle in front of the ego vehicles to make in more natural
    front_transform = world.get_map().get_waypoint(DReyeVR_vehicle.get_location()).next(20)[0].transform
    front_transform.location.z += 1
    vehicle_front_bp = world.get_blueprint_library().find("vehicle.chevrolet.impala")
    front_vehicle = world.spawn_actor(vehicle_front_bp, front_transform)
    vehicles_list.append(front_vehicle)
    front_vehicle.set_autopilot(True, 8000)
    print("Spawned the front vehicle.")

    # create array to store vehicles on the left and right
    left_vehicles = []
    right_vehicles = []

    left_next = -50
    right_next = -50

    for i in range(0, 3, 1):
        left_next += random.randint(15, 30)
        right_next += random.randint(15, 30)
        left_next = 1 if left_next == 0 else left_next
        right_next = 1 if right_next == 0 else right_next

        vehicle_left_bp = random.choice(blueprints)
        vehicle_right_bp = random.choice(blueprints)

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

        vehicle_left = world.try_spawn_actor(vehicle_left_bp, left_transform)
        vehicle_right = world.try_spawn_actor(vehicle_right_bp, right_transform)

        if vehicle_left is not None:
            left_vehicles.insert(0, vehicle_left)
            vehicle_left.set_autopilot(True, 8000)
            traffic_manager.auto_lane_change(vehicle_left, False)
            vehicles_list.append(vehicle_left)
        if vehicle_right is not None:
            right_vehicles.insert(0, vehicle_right)
            vehicle_right.set_autopilot(True, 8000)
            traffic_manager.auto_lane_change(vehicle_right, False)
            vehicles_list.append(vehicle_right)
    return (left_vehicles, right_vehicles)


def stop_at_barrier(world,traffic_manager, barrier_waypoint, left_vehicles, right_vehicles):
    stop_vehicle_array_at_barrier(world, traffic_manager, barrier_waypoint, left_vehicles)
    stop_vehicle_array_at_barrier(world, traffic_manager, barrier_waypoint, right_vehicles)

def stop_vehicle_array_at_barrier(world, traffic_manager, barrier_waypoint, vehicles_list):
    # The first vehicle in the array will be the frontmost, and hence the closest
    if (len(vehicles_list) != 0 and barrier_waypoint.transform.location.distance(vehicles_list[0].get_location()) <= 15):
        stop_vehicles(world, traffic_manager,vehicles_list)

def stop_vehicles(world, traffic_manager, vehicles_list):
    isFirstVehicle = True
    for vehicle in vehicles_list:
        if isFirstVehicle:
            vehicle.set_autopilot(False, 8000)
            vehicle.enable_constant_velocity(carla.Vector3D(0, 0, 0))
            vehicle.apply_control(carla.VehicleControl(throttle=0, brake=1, manual_gear_shift=False, gear=0))
            isFirstVehicle = False
        else:
            traffic_manager.vehicle_percentage_speed_difference(vehicle, -100)
        world.tick()
from tkinter.tix import TEXT
import numpy as np
from typing import Any, Dict, List, Optional

import time
import carla

def get_lane_offset(world, DReyeVR_vehicle, last_logged_at):
    ego_position = DReyeVR_vehicle.get_location()
    lane_center = world.get_map().get_waypoint(ego_position).transform.location
    if (time.time() - last_logged_at >= 0.2):
        return (ego_position.distance(lane_center), time.time())
    else:
        return (None, None)

def collision_performance(carla, world, DReyeVR_vehicle, collision_data):
    blueprint_library = world.get_blueprint_library()
    collision_sensor = world.spawn_actor(blueprint_library.find('sensor.other.collision'),
                                        carla.Transform(), attach_to=DReyeVR_vehicle)
    collision_sensor.listen(lambda event: collision_handler(event, collision_data))
    
def collision_handler(event, list):
    list.append([str(event.time_stamp), str(event.other_actor)])

def write_performance_data(DATA_FILE_PATH, configurations, lp_data, collision_data, scenario):
    if configurations["IGNORE"] == "0":
        first_rows = [configurations["PARTICIPANT_ID"], configurations["RSVP"], configurations["TTS"], configurations["TRIAL_NO"]]
        append_csv_row(DATA_FILE_PATH + "/LanePositionDifference.csv", first_rows + lp_data)
        if len(collision_data) == 0:
            append_csv_row(DATA_FILE_PATH + "/CollisionData.csv", first_rows + "No Collision")
        else:
            append_csv_row(DATA_FILE_PATH + "/CollisionData.csv", first_rows + collision_data)
        append_csv_row(DATA_FILE_PATH + "/Scenario.csv", first_rows + [scenario])
        print(first_rows + collision_data)

def append_csv_row(FILE_PATH, list):
    file = open(FILE_PATH, "a")
    row = "\n"
    for i in range(0, len(list) - 1):
        row += "{}, ".format(list[i])
    row += "{}".format(list[i])
    file.write(row)
    file.close()

def read_config_file(CONFIG_FILE_PATH):
    f = open(CONFIG_FILE_PATH, "r")
    configurations = f.read()
     
    PARTICIPANT_ID_pos = configurations.find("PARTICIPANT_ID") + len("PARTICIPANT_ID") + 2
    TRIAL_NO_pos = configurations.find("TRIAL_NO") + len("TRIAL_NO") + 2
    IGNORE_pos = configurations.find("IGNORE") + len("IGNORE") + 2
    RSVP_pos = configurations.find("RSVP") + len("RSVP") + 2
    TTS_pos = configurations.find("TTS") + len("TTS") + 2
    WPM_pos = configurations.find("WPM") + len("WPM") + 2
    TEXTFILE_pos = configurations.find("TEXTFILE") + len("TEXTFILE") + 2

    PARTICIPANT_ID = configurations[PARTICIPANT_ID_pos : PARTICIPANT_ID_pos + 3]
    TRIAL_NO = configurations[TRIAL_NO_pos: TRIAL_NO_pos + 1]
    IGNORE = configurations[IGNORE_pos: IGNORE_pos + 1]
    RSVP = configurations[RSVP_pos: RSVP_pos + 1]
    WPM = configurations[WPM_pos: WPM_pos + 3]
    TTS = configurations[TTS_pos: TTS_pos + 1]
    TEXTFILE = configurations[TEXTFILE_pos: TEXTFILE_pos + 5]

    return {"PARTICIPANT_ID": PARTICIPANT_ID, "TRIAL_NO": TRIAL_NO, "IGNORE": IGNORE, "RSVP": RSVP, "WPM": WPM, "TTS": TTS, "TEXTFILE": TEXTFILE}

def write_signal_file(file_path, signal):
    try:
        f = open(file_path, "w")
        f.write(str(signal))
        f.close()
    except:
        print("Error occured while opening/writing to the signal file")


def read_signal_file(file_path):
    try:
        f = open(file_path, "r")
        signal = int(f.read())
        f.close()
        return signal
    except:
        print("Error occured while opening/reading the signal file")

def extract_text(TEXT_FILE_PATH):
    try:
        f = open(TEXT_FILE_PATH, "r")
        string = f.read()
        f.close()
        return string
    except:
        print("Error opening the reading comprehension text file.")

def wait(world, duration):
  target_time = time.time() + duration
  while time.time() < target_time:
    world.tick()
    
def wait_for_NDRT(SIGNAL_FILE_PATH, world):
    while read_signal_file(SIGNAL_FILE_PATH) != 3:
        world.tick()
def find_ego_vehicle(world: carla.libcarla.World) -> Optional[carla.libcarla.Vehicle]:
    DReyeVR_vehicle = None
    ego_vehicles = world.get_actors().filter("vehicle.dreyevr.egovehicle")
    try:
        DReyeVR_vehicle = ego_vehicles[0]  # TODO: support for multiple ego vehicles?
    except IndexError:
        print("Unable to find DReyeVR ego vehicle in world!")
    return DReyeVR_vehicle


def find_ego_sensor(world: carla.libcarla.World) -> Optional[carla.libcarla.Sensor]:
    sensor = None
    ego_sensors = world.get_actors().filter("sensor.dreyevr.dreyevrsensor")
    try:
        sensor = ego_sensors[0]  # TODO: support for multiple eye trackers?
    except IndexError:
        print("Unable to find DReyeVR ego vehicle in world!")
    return sensor


class DReyeVRSensor:
    def __init__(self, world: carla.libcarla.World):
        self.ego_sensor: carla.sensor.dreyevrsensor = find_ego_sensor(world)
        self.data: Dict[str, Any] = {}
        print("initialized DReyeVRSensor PythonAPI client")

    def preprocess(self, obj: Any) -> Any:
        if isinstance(obj, carla.libcarla.Vector3D):
            return np.array([obj.x, obj.y, obj.z])
        if isinstance(obj, carla.libcarla.Vector2D):
            return np.array([obj.x, obj.y])
        if isinstance(obj, carla.libcarla.Transform):
            return [
                np.array([obj.location.x, obj.location.y, obj.location.z]),
                np.array([obj.rotation.pitch, obj.rotation.yaw, obj.rotation.roll]),
            ]
        return obj

    def update(self, data) -> None:
        # update local variables
        elements: List[str] = [key for key in dir(data) if "__" not in key]
        for key in elements:
            self.data[key] = self.preprocess(getattr(data, key))

    @classmethod
    def spawn(cls, world: carla.libcarla.World):
        # TODO: check if dreyevr sensor already exsists, then use it
        # spawn a DReyeVR sensor and begin listening
        if find_ego_sensor(world) is None:
            bp = [x for x in world.get_blueprint_library().filter("sensor.dreyevr*")]
            try:
                bp = bp[0]
            except IndexError:
                print("no eye tracker in blueprint library?!")
                return None
            ego_vehicle = find_ego_vehicle()
            ego_sensor = world.spawn_actor(
                bp, ego_vehicle.get_transform(), attach_to=ego_vehicle
            )
            print("Spawned DReyeVR sensor: " + ego_sensor.type_id)
        return cls(world)

    def calc_vergence_from_dir(self, L0, R0, LDir, RDir):
        # Calculating shortest line segment intersecting both lines
        # Implementation sourced from http://paulbourke.net/geometry/Ptlineplane/

        L0R0 = L0 - R0  # segment between L origin and R origin
        epsilon = 0.00000001  # small positive real number

        # Calculating dot-product equation to find perpendicular shortest-line-segment
        d1343 = L0R0[0] * RDir[0] + L0R0[1] * RDir[1] + L0R0[2] * RDir[2]
        d4321 = RDir[0] * LDir[0] + RDir[1] * LDir[1] + RDir[2] * LDir[2]
        d1321 = L0R0[0] * LDir[0] + L0R0[1] * LDir[1] + L0R0[2] * LDir[2]
        d4343 = RDir[0] * RDir[0] + RDir[1] * RDir[1] + RDir[2] * RDir[2]
        d2121 = LDir[0] * LDir[0] + LDir[1] * LDir[1] + LDir[2] * LDir[2]
        denom = d2121 * d4343 - d4321 * d4321
        if abs(denom) < epsilon:
            return 1.0  # no intersection, would cause div by 0 err (potentially)
        numer = d1343 * d4321 - d1321 * d4343

        # calculate scalars (mu) that scale the unit direction XDir to reach the desired points
        # variable scale of direction vector for LEFT ray
        muL = numer / denom
        # variable scale of direction vector for RIGHT ray
        muR = (d1343 + d4321 * (muL)) / d4343

        # calculate the points on the respective rays that create the intersecting line
        ptL = L0 + muL * LDir  # the point on the Left ray
        ptR = R0 + muR * RDir  # the point on the Right ray

        # calculate the vector between the middle of the two endpoints and return its magnitude
        # middle point between two endpoints of shortest-line-segment
        ptM = (ptL + ptR) / 2.0
        oM = (L0 + R0) / 2.0  # midpoint between two (L & R) origins
        FinalRay = ptM - oM  # Combined ray between midpoints of endpoints
        # returns the magnitude of the vector (length)
        return np.linalg.norm(FinalRay) / 100.0

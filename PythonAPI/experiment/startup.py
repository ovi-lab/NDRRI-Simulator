#!/usr/bin/env python

###############################################
# Copyright (c) Shiv Patel, 2022
# BC, Canada.
# The University of British Columbia, Okanagan
###############################################

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

import argparse

# Importing scenario implementations
import ExtremeWeather
import LVAD
import CSA
import ACR

################################ CHANGE UPON PACKAGING ################################
CONTENT_FOLDER_PATH = "D:/carla/Build/UE4Carla/65af421-dirty/WindowsNoEditor/CarlaUE4/Content"
# CONTENT_FOLDER_PATH = "D:/carla/Unreal/CarlaUE4/Content"
#######################################################################################

def main(arg):
    if arg == 1:
        ExtremeWeather.run(CONTENT_FOLDER_PATH=CONTENT_FOLDER_PATH)
    elif arg == 2:
        LVAD.run(CONTENT_FOLDER_PATH=CONTENT_FOLDER_PATH)
    elif arg == 3:
        CSA.run(CONTENT_FOLDER_PATH=CONTENT_FOLDER_PATH)
    else:
        ACR.run(CONTENT_FOLDER_PATH=CONTENT_FOLDER_PATH)

if __name__ == '__main__':

    try:
        if len(sys.argv) == 1:
            main(4) # Run extreme weather scenario by default
        else:
            main(int(sys.argv[1]))
    except KeyboardInterrupt:
        print("Execution terminated!")
        pass
    finally:
        print('\ndone.')

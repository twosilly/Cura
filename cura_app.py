#!/usr/bin/env python3

# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

import argparse
import faulthandler
import os
import sys

from UM.OS import OS

parser = argparse.ArgumentParser(prog = "cura",
                                 add_help = False)
parser.add_argument('--debug',
                    action='store_true',
                    default = False,
                    help = "Turn on the debug mode by setting this option."
                    )
parser.add_argument('--trigger-early-crash',
                    dest = 'trigger_early_crash',
                    action = 'store_true',
                    default = False,
                    help = "FOR TESTING ONLY. Trigger an early crash to show the crash dialog."
                    )
known_args = vars(parser.parse_known_args()[0])

if not known_args["debug"]:
    def get_cura_dir_path():
        if OS.isWindows():
            return os.path.expanduser("~/AppData/Roaming/cura")
        elif OS.isLinux():
            return os.path.expanduser("~/.local/share/cura")
        elif OS.isOSX():
            return os.path.expanduser("~/Library/Logs/cura")

    if hasattr(sys, "frozen"):
        dirpath = get_cura_dir_path()
        os.makedirs(dirpath, exist_ok = True)
        sys.stdout = open(os.path.join(dirpath, "stdout.log"), "w", encoding = "utf-8")
        sys.stderr = open(os.path.join(dirpath, "stderr.log"), "w", encoding = "utf-8")


# When frozen, i.e. installer version, don't let PYTHONPATH mess up the search path for DLLs.
if OS.isWindows() and hasattr(sys, "frozen"):
    try:
        del os.environ["PYTHONPATH"]
    except KeyError:
        pass

# WORKAROUND: GITHUB-704 GITHUB-708
# It looks like setuptools creates a .pth file in
# the default /usr/lib which causes the default site-packages
# to be inserted into sys.path before PYTHONPATH.
# This can cause issues such as having libsip loaded from
# the system instead of the one provided with Cura, which causes
# incompatibility issues with libArcus
if "PYTHONPATH" in os.environ.keys():                       # If PYTHONPATH is used
    PYTHONPATH = os.environ["PYTHONPATH"].split(os.pathsep) # Get the value, split it..
    PYTHONPATH.reverse()                                    # and reverse it, because we always insert at 1
    for PATH in PYTHONPATH:                                 # Now beginning with the last PATH
        PATH_real = os.path.realpath(PATH)                  # Making the the path "real"
        if PATH_real in sys.path:                           # This should always work, but keep it to be sure..
            sys.path.remove(PATH_real)
        sys.path.insert(1, PATH_real)                       # Insert it at 1 after os.curdir, which is 0.


# Enable dumping traceback for all threads
faulthandler.enable(all_threads = True)

# Workaround for a race condition on certain systems where there
# is a race condition between Arcus and PyQt. Importing Arcus
# first seems to prevent Sip from going into a state where it
# tries to create PyQt objects on a non-main thread.
from cura.CuraCLI import CuraCLI

app = CuraCLI()
app.addCommandLineOptions()
app.parseCliOptions()

app.initialize()
app.startSplashWindowPhase()
app.run()

#!/usr/bin/env python
# This experiment enables CGroup tracing for UiBench workloads
# The main difference between the run_uibench.py experiment is:
# - post_collect_start hook used to dump fake cgroup events
# - extra event: 'cgroup_attach_task' passed to systrace_start

import logging

from conf import LisaLogging
LisaLogging.setup()
import json
import os
import devlib
from env import TestEnv
from android import Screen, Workload, System
from trace import Trace
import trappy
import pandas as pd
import sqlite3
import argparse
import shutil
import time

parser = argparse.ArgumentParser(description='UiBench tests')

parser.add_argument('--out_prefix', dest='out_prefix', action='store', default='cgroup',
                    help='prefix for out directory')

parser.add_argument('--collect', dest='collect', action='store', default='systrace',
                    help='what to collect (default systrace)')

parser.add_argument('--test', dest='test_name', action='store',
                    default='UiBenchJankTests#testGLTextureView',
                    help='which test to run')

parser.add_argument('--duration', dest='duration_s', action='store',
                    default=30, type=int,
                    help='Duration of test (default 30s)')

parser.add_argument('--serial', dest='serial', action='store',
                    help='Serial number of device to test')

args = parser.parse_args()

def experiment():
    # Get workload
    wload = Workload.getInstance(te, 'UiBench')

    outdir=te.res_dir + '_' + args.out_prefix
    try:
        shutil.rmtree(outdir)
    except:
        print "coulnd't remove " + outdir
        pass
    os.makedirs(outdir)

    # Run UiBench
    wload.run(outdir, test_name=args.test_name, duration_s=args.duration_s, collect=args.collect)

    # Dump platform descriptor
    te.platform_dump(te.res_dir)

    te._log.info('RESULTS are in out directory: {}'.format(outdir))

# Setup target configuration
my_conf = {

    # Target platform and board
    "platform"     : 'android',

    # Useful for reading names of little/big cluster
    # and energy model info, its device specific and use
    # only if needed for analysis
    # "board"        : 'pixel',

    # Device
    # By default the device connected is detected, but if more than 1
    # device, override the following to get a specific device.
    # "device"       : "HT6880200489",

    # Folder where all the results will be collected
    "results_dir" : "UiBench",

    # Define devlib modules to load
    "modules"     : [
        'cpufreq',      # enable CPUFreq support
        'cpuidle',      # enable cpuidle support
        'cgroups'       # Enable for cgroup support, doing this also enables cgroup tracing
    ],

    "emeter" : {
        'instrument': 'monsoon',
        'conf': { }
    },

    "systrace": {
        # Mandatory events for CGroup tracing
        'extra_events': ['cgroup_attach_task', 'sched_process_fork']
    },

    # Tools required by the experiments
    "tools"   : [ 'taskset'],
}

if args.serial:
    my_conf["device"] = args.serial

# Initialize a test environment using:
te = TestEnv(my_conf, wipe=False)
target = te.target

results = experiment()

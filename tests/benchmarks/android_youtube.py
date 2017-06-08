#!/usr/bin/env python

import os
from time import sleep

# The workload class MUST be loaded before the LisaBenchmark
from android import Workload
from android import LisaBenchmark

from devlib.exception import TargetError

class YouTubeTest(LisaBenchmark):

    bm_conf = {

        # Target platform and board
        "platform"      : 'android',

        # Define devlib modules to load
        "modules"     : [
            'cpufreq',
            'cpuidle'
        ],

        # FTrace events to collect for all the tests configuration which have
        # the "ftrace" flag enabled
        "ftrace"  : {
            "events" : [
                "sched_switch",
                "sched_overutilized",
                "sched_contrib_scale_f",
                "sched_load_avg_cpu",
                "sched_load_avg_task",
                "sched_tune_tasks_update",
                "sched_boost_cpu",
                "sched_boost_task",
                "sched_energy_diff",
                "cpu_frequency",
                "cpu_idle",
                "cpu_capacity",
            ],
            "buffsize" : 10 * 1024,
        },

        # Default EnergyMeter Configuration
        "emeter" : {
            'instrument': 'monsoon',
            'conf': { }
        },

        # Tools required by the experiments
        "tools"   : [ 'trace-cmd' ],

		# Default results folder
		"results_dir" : "AndroidYouTube",

    }

    # Android Workload to run
    bm_name = 'YouTube'

    # Default products to be collected
    bm_collect = 'ftrace energy'

    def benchmarkInit(self):
        self.setupWorkload()
        self.setupGovernor()

    def __init__(self, governor, video_url, video_duration_s):
        self.governor = governor
        self.video_url = video_url
        self.video_duration_s = video_duration_s
        super(YouTubeTest, self).__init__()

    def setupWorkload(self):
        # Create a results folder for each "governor/test"
        self.out_dir = os.path.join(self.te.res_dir, governor,
                       self.video_url.replace('/', '_'))
        try:
                os.stat(self.out_dir)
        except:
                os.makedirs(self.out_dir)
        # Setup workload parameters
        self.bm_params = {
            'video_url'  : self.video_url,
            'video_duration_s' : self.video_duration_s,
        }

    def setupGovernor(self):
        try:
            self.target.cpufreq.set_all_governors(self.governor);
        except TargetError:
            self._log.warning('Governor [%s] not available on target',
                             self.governor)
            raise

        # Setup schedutil parameters
        if self.governor == 'schedutil':
            rate_limit_us = 2000
            # Different schedutil versions have different tunables
            tunables = self.target.cpufreq.list_governor_tunables(0)
            if 'rate_limit_us' in tunables:
                tunables = {'rate_limit_us' : str(rate_limit_us)}
            else:
                assert ('up_rate_limit_us' in tunables and
                        'down_rate_limit_us' in tunables)
                tunables = {
                    'up_rate_limit_us' : str(rate_limit_us),
                    'down_rate_limit_us' : str(rate_limit_us)
                }

            try:
                for cpu_id in range(self.te.platform['cpus_count']):
                    self.target.cpufreq.set_governor_tunables(
                        cpu_id, 'schedutil', **tunables)
            except TargetError as e:
                self._log.warning('Failed to set schedutils parameters: {}'\
                                 .format(e))
                raise
            self._log.info('Set schedutil.rate_limit_us=%d', rate_limit_us)

        # Setup ondemand parameters
        if self.governor == 'ondemand':
            try:
                for cpu_id in range(self.te.platform['cpus_count']):
                    tunables = self.target.cpufreq.get_governor_tunables(cpu_id)
                    self.target.cpufreq.set_governor_tunables(
                        cpu_id, 'ondemand',
                        **{'sampling_rate' : tunables['sampling_rate_min']})
            except TargetError as e:
                self._log.warning('Failed to set ondemand parameters: {}'\
                                 .format(e))
                raise
            self._log.info('Set ondemand.sampling_rate to minimum supported')

        # Report configured governor
        governors = self.target.cpufreq.get_all_governors()
        self._log.info('Using governors: %s', governors)

# Run the benchmark in each of the supported governors

video_duration_s = 60

governors = [
    'performance',
    'ondemand',
    'interactive',
    'sched',
    'schedutil',
    'powersave',
]

video_urls = [
    'https://youtu.be/XSGBVzeBUbk?t=45s',
]

tests_remaining = len(governors) * len(video_urls)
tests_completed = 0
for governor in governors:
    for url in video_urls:
        tests_remaining -= 1
        try:
            YouTubeTest(governor, url, video_duration_s)
            tests_completed += 1
        except:
            # A test configuraion failed, continue with other tests
            pass

# We want to collect data from at least one governor
assert(tests_completed >= 1)

# vim :set tabstop=4 shiftwidth=4 expandtab

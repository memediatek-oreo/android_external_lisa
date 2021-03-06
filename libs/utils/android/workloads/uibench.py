# SPDX-License-Identifier: Apache-2.0
#
# Copyright (C) 2015, ARM Limited and contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import re
import os
import logging

from subprocess import Popen, PIPE
from time import sleep

from android import Screen, System, Workload

class UiBench(Workload):
    """
    Android UiBench workload
    """

    # Package required by this workload
    package = 'com.android.test.uibench'

    # Instrumentation required to run tests
    test_package = 'com.android.uibench.janktests'

    # Supported tests list
    test_ClippedListView = 'UiBenchJankTests#testClippedListView'
    test_DialogListFling = 'UiBenchJankTests#testDialogListFling'
    test_FadingEdgeListViewFling = 'UiBenchJankTests#testFadingEdgeListViewFling'
    test_FullscreenOverdraw = 'UiBenchJankTests#testFullscreenOverdraw'
    test_GLTextureView = 'UiBenchJankTests#testGLTextureView'
    test_InflatingListViewFling = 'UiBenchJankTests#testInflatingListViewFling'
    test_Invalidate = 'UiBenchJankTests#testInvalidate'
    test_InvalidateTree = 'UiBenchJankTests#testInvalidateTree'
    test_OpenNavigationDrawer = 'UiBenchJankTests#testOpenNavigationDrawer'
    test_OpenNotificationShade = 'UiBenchJankTests#testOpenNotificationShade'
    test_ResizeHWLayer = 'UiBenchJankTests#testResizeHWLayer'
    test_SaveLayerAnimation = 'UiBenchJankTests#testSaveLayerAnimation'
    test_SlowBindRecyclerViewFling = 'UiBenchJankTests#testSlowBindRecyclerViewFling'
    test_SlowNestedRecyclerViewFling = 'UiBenchJankTests#testSlowNestedRecyclerViewFling'
    test_SlowNestedRecyclerViewInitialFling = 'UiBenchJankTests#testSlowNestedRecyclerViewInitialFling'
    test_TrivialAnimation = 'UiBenchJankTests#testTrivialAnimation'
    test_TrivialListViewFling = 'UiBenchJankTests#testTrivialListViewFling'
    test_TrivialRecyclerListViewFling = 'UiBenchJankTests#testTrivialRecyclerListViewFling'
    test_BitmapUploadJank = 'UiBenchRenderingJankTests#testBitmapUploadJank'
    test_ShadowGridListFling = 'UiBenchRenderingJankTests#testShadowGridListFling'
    test_EditTextTyping = 'UiBenchTextJankTests#testEditTextTyping'
    test_LayoutCacheHighHitrateFling = 'UiBenchTextJankTests#testLayoutCacheHighHitrateFling'
    test_LayoutCacheLowHitrateFling = 'UiBenchTextJankTests#testLayoutCacheLowHitrateFling'
    test_ActivityTransitionsAnimation = 'UiBenchTransitionsJankTests#testActivityTransitionsAnimation'
    test_WebViewFling = 'UiBenchWebView#testWebViewFling'

    def __init__(self, test_env):
        super(UiBench, self).__init__(test_env)
        self._log = logging.getLogger('UiBench')
        self._log.debug('Workload created')

        # Set of output data reported by UiBench
        self.db_file = None

    def run(self, out_dir, test_name, duration_s, collect=''):
        """
        Run single UiBench workload.

        :param out_dir: Path to experiment directory where to store results.
        :type out_dir: str

        :param test_name: Name of the test to run
        :type test_name: str

        :param duration_s: Run benchmak for this required number of seconds
        :type duration_s: int

        :param collect: Specifies what to collect. Possible values:
            - 'energy'
            - 'systrace'
            - 'ftrace'
            - any combination of the above
        :type collect: list(str)
        """

        activity = '.' + test_name

        # Keep track of mandatory parameters
        self.out_dir = out_dir
        self.collect = collect

        # Unlock device screen (assume no password required)
        Screen.unlock(self._target)

        # Close and clear application
        System.force_stop(self._target, self.package, clear=True)

        # Set airplane mode
        System.set_airplane_mode(self._target, on=True)

        # Set min brightness
        Screen.set_brightness(self._target, auto=False, percent=0)

        # Start the main view of the app which must be running
        # to reset the frame statistics.
        System.monkey(self._target, self.package)

        # Force screen in PORTRAIT mode
        Screen.set_orientation(self._target, portrait=True)

        # Reset frame statistics
        System.gfxinfo_reset(self._target, self.package)
        sleep(1)

        # Clear logcat
        os.system(self._adb('logcat -c'));

        # Regexps for benchmark synchronization
        start_logline = r'TestRunner: started'
        UIBENCH_BENCHMARK_START_RE = re.compile(start_logline)
        self._log.debug("START string [%s]", start_logline)

        # Parse logcat output lines
        logcat_cmd = self._adb(
                'logcat TestRunner:* System.out:I *:S BENCH:*'\
                .format(self._target.adb_name))
        self._log.info("%s", logcat_cmd)

        # Run benchmark with a lot of iterations to avoid finishing before duration_s elapses
        command = "nohup am instrument -e iterations 1000000 -e class {}{} -w {}".format(
            self.test_package, activity, self.test_package)
        self._target.background(command)

        logcat = Popen(logcat_cmd, shell=True, stdout=PIPE)
        while True:

            # read next logcat line (up to max 1024 chars)
            message = logcat.stdout.readline(1024)

            # Benchmark start trigger
            match = UIBENCH_BENCHMARK_START_RE.search(message)
            if match:
                self.tracingStart()
                self._log.debug("Benchmark started!")
                break

        # Run the workload for the required time
        self._log.info('Benchmark [%s] started, waiting %d [s]',
                     activity, duration_s)
        sleep(duration_s)

        self._log.debug("Benchmark done!")
        self.tracingStop()

        # Get frame stats
        self.db_file = os.path.join(out_dir, "framestats.txt")
        System.gfxinfo_get(self._target, self.package, self.db_file)

        # Close and clear application
        System.force_stop(self._target, self.package, clear=True)

        # Go back to home screen
        System.home(self._target)

        # Switch back to original settings
        Screen.set_orientation(self._target, auto=True)
        System.set_airplane_mode(self._target, on=False)
        Screen.set_brightness(self._target, auto=True)

# vim :set tabstop=4 shiftwidth=4 expandtab

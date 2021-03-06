# SPDX-License-Identifier: Apache-2.0
#
# Copyright (C) 2015, Google, ARM Limited and contributors.
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

""" Residency Analysis Module """

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
import pandas as pd
import pylab as pl
import operator
from trappy.utils import listify
from devlib.utils.misc import memoized
import numpy as np
import logging
import trappy
from analysis_module import AnalysisModule
from trace import ResidencyTime, ResidencyData
from bart.common.Utils import area_under_curve

class Residency(object):
    def __init__(self, pivot, time):
        self.last_start_time = time
        self.total_time = np.float64(0.0)
        # Keep track of last seen start times
        self.start_time = -1
        # Keep track of maximum runtime seen
        self.end_time = -1
        self.max_runtime = -1
        # When Residency is created for the first time,
        # its running (switch in)
        self.running = 1

################################################################
# Callback and state machinery                                 #
################################################################

def process_pivot(pivot_list, pivot):
    if not pivot_list:
        return True
    return pivot in pivot_list

def pivot_process_cb(data, args):

    pivot = args[0]['pivot']
    if args[0].has_key('pivot_list'):
        pivot_list = args[0]['pivot_list']
    else:
        pivot_list = []
    res_analysis_obj = args[0]['res_analysis_obj']

    debugg = False if pivot == 'schedtune' else False

    log = res_analysis_obj._log
    prev_pivot = data['prev_' + pivot]
    next_pivot = data['next_' + pivot]
    time = data['Time']
    cpu = data['__cpu']
    pivot_res = res_analysis_obj.residency[pivot][int(cpu)]

    if debugg:
        print "{}: {} {} -> {} {}".format(time, prev_pivot, data['prev_comm'], \
                                          next_pivot, data['next_comm'])

    # prev pivot processing (switch out)
    if pivot_res.has_key(prev_pivot) and process_pivot(pivot_list, prev_pivot):
        pr = pivot_res[prev_pivot]
        if pr.running == 1:
            pr.running = 0
            runtime = time - pr.last_start_time
            if runtime > pr.max_runtime:
                pr.max_runtime = runtime
                pr.start_time = pr.last_start_time
                pr.end_time = time
            pr.total_time += runtime
            if debugg: log.info('adding to total time {}, new total {}'.format(runtime, pr.total_time))

        else:
            log.info('switch out seen while no switch in {}'.format(prev_pivot))
    elif process_pivot(pivot_list, prev_pivot):
        log.info('switch out seen while no switch in {}'.format(prev_pivot))

    # Filter the next pivot
    if not process_pivot(pivot_list, next_pivot):
        return

    # next_pivot processing for new pivot switch in
    if not pivot_res.has_key(next_pivot):
        pr = Residency(next_pivot, time)
        pivot_res[next_pivot] = pr
        return

    # next_pivot processing for previously discovered pid (switch in)
    pr = pivot_res[next_pivot]
    if pr.running == 1:
        log.info('switch in seen for already running task {}'.format(next_pivot))
        return
    pr.running = 1
    pr.last_start_time = time

class ResidencyAnalysis(AnalysisModule):
    """
    Support for calculating residencies

    :param trace: input Trace object
    :type trace: :mod:`libs.utils.Trace`
    """

    def __init__(self, trace):
        self.pid_list = []
        self.pid_tgid = {}
	# Hastable of pivot -> array of entities (cores) mapping
        # Each element of the array represents a single entity (core) to calculate on
        # Each array entry is a hashtable, for ex: residency['pid'][0][123]
        # is the residency of PID 123 on core 0
        self.residency = { }
        super(ResidencyAnalysis, self).__init__(trace)

    def generate_residency_data(self, pivot_type, pivot_ids):
        logging.info("Generating residency for {} {}s!".format(len(pivot_ids), pivot_type))
        for pivot in pivot_ids:
            dict_ret = {}
            total = 0
            # dict_ret['name'] = self._trace.getTaskByPid(pid)[0] if self._trace.getTaskByPid(pid) else 'UNKNOWN'
            # dict_ret['tgid'] = -1 if not self.pid_tgid.has_key(pid) else self.pid_tgid[pid]
            for cpunr in range(0, self.ncpus):
                cpu_key = 'cpu_{}'.format(cpunr)
                try:
                    dict_ret[cpu_key] = self.residency[pivot_type][int(cpunr)][pivot].total_time
                except:
                    dict_ret[cpu_key] = 0
                total += dict_ret[cpu_key]

            dict_ret['total'] = total
            yield dict_ret

    @memoized
    def _dfg_cpu_residencies(self, pivot, pivot_list=[], event_name='sched_switch'):
       # Build a list of pids
        df = self._dfg_trace_event('sched_switch')
        df = df[['__pid']].drop_duplicates(keep='first')
        for s in df.iterrows():
            self.pid_list.append(s[1]['__pid'])

        # Build the pid_tgid map (skip pids without tgid)
        df = self._dfg_trace_event('sched_switch')
        df = df[['__pid', '__tgid']].drop_duplicates(keep='first')
        df_with_tgids = df[df['__tgid'] != -1]
        for s in df_with_tgids.iterrows():
            self.pid_tgid[s[1]['__pid']] = s[1]['__tgid']

	self.pid_tgid[0] = 0 # Record the idle thread as well (pid = tgid = 0)

        self.npids = len(df.index)                      # How many pids in total
        self.npids_tgid = len(self.pid_tgid.keys())     # How many pids with tgid
	self.ncpus = self._trace.ftrace._cpus		# How many total cpus

        logging.info("TOTAL number of CPUs: {}".format(self.ncpus))
        logging.info("TOTAL number of PIDs: {}".format(self.npids))
        logging.info("TOTAL number of TGIDs: {}".format(self.npids_tgid))

        # Create empty hash tables, 1 per CPU for each each residency
        self.residency[pivot] = []
        for cpunr in range(0, self.ncpus):
            self.residency[pivot].append({})

        # Calculate residencies
        if hasattr(self._trace.data_frame, event_name):
            df = getattr(self._trace.data_frame, event_name)()
        else:
            df = self._dfg_trace_event(event_name)

        kwargs = { 'pivot': pivot, 'res_analysis_obj': self, 'pivot_list': pivot_list }
        trappy.utils.apply_callback(df, pivot_process_cb, kwargs)

        # Build the pivot id list
        pivot_ids = []
        for cpunr in range(0, len(self.residency[pivot])):
            res_ht = self.residency[pivot][cpunr]
            # print res_ht.keys()
            pivot_ids = pivot_ids + res_ht.keys()

        # Make unique
        pivot_ids = list(set(pivot_ids))

        # Now build the final DF!
        pid_idx = pd.Index(pivot_ids, name=pivot)
        df = pd.DataFrame(self.generate_residency_data(pivot, pivot_ids), index=pid_idx)
        df.sort_index(inplace=True)

        logging.info("total time spent by all pids across all cpus: {}".format(df['total'].sum()))
        logging.info("total real time range of events: {}".format(self._trace.time_range))
        return df

    def _dfg_cpu_residencies_cgroup(self, controller, cgroups=[]):
        return self._dfg_cpu_residencies(controller, pivot_list=cgroups, event_name='sched_switch_cgroup')

    def plot_cgroup(self, controller, cgroup='all', idle=False):
        """
        controller: name of the controller
        idle: Consider idle time?
        """
        df = self._dfg_cpu_residencies_cgroup(controller)
	# Plot per-CPU break down for a single CGroup (Single pie plot)
        if cgroup != 'all':
            df = df[df.index == cgroup]
            df = df.drop('total', 1)
            df = df.apply(lambda x: x*10)

            plt.style.use('ggplot')
            colors = plt.rcParams['axes.color_cycle']
            fig, axes = plt.subplots(nrows=1, ncols=1, figsize=(8,8))
            patches, texts, autotexts = axes.pie(df.loc[cgroup], labels=df.columns, autopct='%.2f', colors=colors)
            axes.set(ylabel='', title=cgroup + ' per CPU percentage breakdown', aspect='equal')

            axes.legend(bbox_to_anchor=(0, 0.5))
            proptease = fm.FontProperties()
            proptease.set_size('x-large')
            plt.setp(autotexts, fontproperties=proptease)
            plt.setp(texts, fontproperties=proptease)

            plt.show()
            return

	# Otherwise, Plot per-CGroup of a Controller down for each CPU
        if not idle:
            df = df[pd.isnull(df.index) != True]
        # Bug in matplot lib causes plotting issues when residency is < 1
        df = df.apply(lambda x: x*10)
        plt.style.use('ggplot')
        colors = plt.rcParams['axes.color_cycle']
        fig, axes = plt.subplots(nrows=5, ncols=2, figsize=(12,30))

        for ax, col in zip(axes.flat, df.columns):
            ax.pie(df[col], labels=df.index, autopct='%.2f', colors=colors)
            ax.set(ylabel='', title=col, aspect='equal')

        axes[0, 0].legend(bbox_to_anchor=(0, 0.5))
        plt.show()

















# vim :set tabstop=4 shiftwidth=4 expandtab

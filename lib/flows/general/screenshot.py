#!/usr/bin/env python
# Copyright 2012 Google Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Flows to take a screenshot."""


import time

from grr.lib import aff4
from grr.lib import flow
from grr.lib import utils

from grr.proto import jobs_pb2


class TakeScreenshot(flow.GRRFlow):
  """Take a screenshot from a running system."""

  category = "/Misc/"

  @flow.StateHandler(next_state=["RetrieveFile"])
  def Start(self):
    """Start processing."""
    self.urn = aff4.ROOT_URN.Add(self.client_id)
    fd = aff4.FACTORY.Open(self.urn, token=self.token)
    self.hostname = fd.Get(fd.Schema.HOSTNAME)
    system = fd.Get(fd.Schema.SYSTEM)
    if system != "Darwin":
      raise flow.FlowError("Only OSX is supported for screen capture.")

    self._sspath = "/tmp/ss.dat"
    # TODO(user): Add support for non-constrained parameters so file can be
    # random/hidden.
    cmd = jobs_pb2.ExecuteRequest(cmd="/usr/sbin/screencapture",
                                  args=["-x", "-t", "jpg", self._sspath],
                                  time_limit=15)
    self.CallClient("ExecuteCommand", cmd, next_state="RetrieveFile")

  @flow.StateHandler(next_state=["ProcessFile"])
  def RetrieveFile(self, responses):
    """Retrieve the file if we successfully captured."""

    if not responses.success or responses.First().exit_status != 0:
      raise flow.FlowError("Capture failed to run." % responses.status)

    pathspec = jobs_pb2.Path(pathtype=jobs_pb2.Path.OS, path=self._sspath)
    self.CallFlow("GetFile", next_state="ProcessFile",
                  pathspec=pathspec)

  @flow.StateHandler(next_state=["FinishedRemove"])
  def ProcessFile(self, responses):
    """Process the file we retrieved."""
    if not responses.success:
      raise flow.FlowError("Failed to retrieve captured file. This may be due"
                           "to the screen being off.")

    ss_file = responses.First()
    ss_pathspec = utils.Pathspec(ss_file.pathspec)
    ss_urn = aff4.AFF4Object.VFSGRRClient.PathspecToURN(ss_pathspec,
                                                        self.client_id)
    ss_fd = aff4.FACTORY.Open(ss_urn, required_type="HashImage")
    content = ss_fd.Read(10000000)

    curr_time = time.asctime(time.gmtime())
    self.filename = "%s.screencap.%s" % (self.hostname, curr_time)
    self.new_urn = self.urn.Add("analysis").Add("screencaps").Add(self.filename)
    fd = aff4.FACTORY.Create(self.new_urn, "VFSFile", token=self.token)
    fd.Write(content)
    fd.Close()

    cmd = jobs_pb2.ExecuteRequest(cmd="/bin/rm",
                                  args=["-f", self._sspath],
                                  time_limit=15)
    self.CallClient("ExecuteCommand", cmd, next_state="FinishedRemove")

  @flow.StateHandler()
  def FinishedRemove(self, responses):
    """Check the status of the rm."""
    if not responses.success:
      self.Log("Failed to remove captured file")

  @flow.StateHandler()
  def End(self):
    self.Notify("ViewObject", self.new_urn, "Got screencap %s" % self.filename)
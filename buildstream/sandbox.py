#!/usr/bin/env python3
#
#  Copyright (C) 2016 Codethink Limited
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library. If not, see <http://www.gnu.org/licenses/>.
#
#  Authors:
#        Andrew Leeming <andrew.leeming@codethink.co.uk>

from enum import Enum
from ._sandboxbwrap import _SandboxBwap
from ._sandboxchroot import _SandboxChroot

Executors = Enum('chroot', 'bwrap')

class Sandbox:

    def __init__(self, executor=Executors.bwrap, **kwargs):
        self.executorType = executor

        if executor is Executors.chroot:
            self.executor = _SandboxChroot()
        elif executor is Executors.bwrap:
            self.executor = _SandboxBwap()

    def getExecutor(self):
        return self.executor

    def setMounts(self, mnt_list=[], global_write=False, append=False):
        self.executor.setMounts(mnt_list=mnt_list, global_write=global_write,
                                append=append)

    def run(self, command):
        # Run command in sandbox and save outputs
        self.exitcode, self.out, self.err = self.executor.run(command)

        return self.exitcode, self.out, self.err
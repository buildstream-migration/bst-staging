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

""" TODO docstr for this class

This class contains a lot of cannibalised code from sandboxlib.bubblewrap
"""

import os
import sys
import subprocess
import shutil

from .exceptions import ProgramNotFound

# Special value for 'stderr' and 'stdout' parameters to indicate 'capture
# and return the data'.
CAPTURE = subprocess.PIPE

# Special value for 'stderr' parameter to indicate 'forward to stdout'.
STDOUT = subprocess.STDOUT


class Sandbox():

    def __init__(self):

        self.fs_root = "/"
        """Path of the host that we wish to map as '/' in the sandbox"""

        self.cwd = None
        """Current working directory we want to start the sandbox in. If
        None then cwd is inherited from the caller's CWD
        """

        self.stdout = CAPTURE
        """Standard out stream is captured by default"""

        self.stderr = CAPTURE
        """Standard error stream is captured by default"""

    def run(self, command):
        """Run the sandbox

        :return:
        """

        # We want command args as a list of strings
        if type(command) == str:
            command = [command]

        # Grab the full path of the bwrap binary
        bwrap_command = [self._getBinary()]

        # Add in the root filesystem stuff first
        # rootfs is mounted as RW initially so that further mounts can be
        # placed on top. If a RO root is required, after all other mounts
        # are complete, root is remounted as RO
        bwrap_command += ["--bind", self.fs_root, "/"]

        bwrap_command += self._processNetworkConfig()

        if self.cwd is not None:
            bwrap_command.extend(['--chdir', self.cwd])

        # do pre checks on mounts
        ## TODO collect mounts
        #
        self._createMountPoints()

        # Handles the ro and rw mounts
        bwrap_command += self._processMounts(self.fs_root, extra_mounts,
                                        filesystem_writable_paths)

        # Set UID and GUI
        bwrap_command += self._userNamespace()
        #bwrap_command.extend(['--unshare-user', '--uid', '0', '--gid', '0'])

        argv = bwrap_command + command

        exit, out, err = self._run_command(argv, self.stdout, self.stderr, env=env)

        return exit, out, err

    def setCwd(self, cwd):
        """

        :param cwd:
        :return:
        """

        # TODO check valid path of `cwd`
        self.cwd=cwd

        return

    def _getBinary(self):
        """Get the absolute path of a program

        :return:
        """
        program_name = "bwrap"

        search_path = os.environ.get('PATH')

        # Python 3.3 and newer provide a 'find program in PATH' function. Otherwise
        # we fall back to the `which` program.
        if sys.version_info.major >= 3 and sys.version_info.minor >= 3:
            program_path = shutil.which(program_name, path=search_path)
        else:
            try:
                argv = ['which', program_name]
                program_path = subprocess.check_output(argv).strip()
            except subprocess.CalledProcessError as e:
                program_path = None

        if program_path is None:
            raise ProgramNotFound(
                "Did not find '%s' in PATH. Searched '%s'" % (
                    program_name, search_path))

        return program_path

    def _createMountPoints(self):
        pass

    def _isMountWritable(self, mnt):
        pass

    def _processNetworkConfig(self):
        pass

    def _run_command(self, argv, stdout, stderr, cwd=None, env=None):
        """Wrapper around subprocess.Popen() with common settings.

        This function blocks until the subprocess has terminated.

        Unlike the subprocess.Popen() function, if stdout or stderr are None then
        output is discarded.

        It then returns a tuple of (exit code, stdout output, stderr output).
        If stdout was not equal to subprocess.PIPE, stdout will be None. Same for
        stderr.

        """
        if stdout is None or stderr is None:
            dev_null = open(os.devnull, 'w')
            stdout = stdout or dev_null
            stderr = stderr or dev_null
        else:
            dev_null = None

        try:
            process = subprocess.Popen(
                argv,
                # The default is to share file descriptors from the parent process
                # to the subprocess, which is rarely good for sandboxing.
                close_fds=True,
                cwd=cwd,
                env=env,
                stdout=stdout,
                stderr=stderr,
            )

            # The 'out' variable will be None unless subprocess.PIPE was passed as
            # 'stdout' to subprocess.Popen(). Same for 'err' and 'stderr'. If
            # subprocess.PIPE wasn't passed for either it'd be safe to use .wait()
            # instead of .communicate(), but if they were then we must use
            # .communicate() to avoid blocking the subprocess if one of the pipes
            # becomes full. It's safe to use .communicate() in all cases.

            out, err = process.communicate()
        finally:
            if dev_null is not None:
                dev_null.close()

        return process.returncode, out, err

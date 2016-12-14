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

MOUNT_TYPES = ['dev','host-dev','tmpfs','proc']

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

        self.network_enable = False
        """Boolean flag for if network resources can be utilised"""

        self.namespace_uid = None
        self.namespace_gid = None

        self._mounts = []
        """List of mounts, each in the format (src, dest, type, writeable)"""

    def run(self, command):
        """Runs a command inside the sandbox environment

        Args:
            command (string): The command to run in the sandboxed environment

        Raises:
            :class'`.ProgramNotfound` If bwrap(bubblewrap) binary can not be found

        Returns:
            exitcode, stdout, stderr
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
        self._createMountPoints()

        # Handles the ro and rw mounts
        bwrap_command += self._processMounts()

        # Set UID and GUI
        bwrap_command += self._userNamespace()

        argv = bwrap_command + command
        exitcode, out, err = self._run_command(argv, self.stdout, self.stderr, env=self.env)

        return exitcode, out, err


    def setCwd(self, cwd):
        """Set the CWD for the sandbox

        Args:
            cwd (string): Path to desired working directory when the sandbox is entered
        """

        # TODO check valid path of `cwd`
        self.cwd=cwd
        return


    def setMounts(self, mnt_list=[], global_write=False, append=False):
        """Set mounts for the sandbox to use

        Args:
            mnt_list (list): List of dicts describing mounts. Dict is in the format {'src','dest','type','writable'}
                Only 'src' and 'dest' are required.
            global_write (boolean): Set all mounts given as writable (overrides setting in dict)
            append (boolean): If set, multiple calls to `setMounts` extends the list of mounts.
                Else they are overridden.

        The mount dict is in the format {'src','dest','type','writable'}.
            - src : Path of the mount on the HOST
            - dest : Path we wish to mount to on the TARGET
            - type : (optional) Some mounts are special such as dev, proc and tmp, and need to be tagged accordingly
            - writable : (optional) Boolean value to make mount writable instead of read-only
        """

        mounts=[]
        # Process mounts one by one
        for mnt in mnt_list:
            host_dir = mnt.get('src')
            target_dir = mnt.get('dest')
            mnt_type = mnt.get('type', None)
            writable = global_write or mnt.get('writable', False)

            mounts.append((host_dir, target_dir, mnt_type, writable))

        if append:
            self._mounts.extend(mounts)
        else:
            self._mounts = mounts


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
        """
        Creates any mount points that do not currently exist
        but have ben specified in _mounts
        :return:
        """

        for mnt in self._mounts:
            #(host_dir, target_dir, mnt_type, writable)
            target_dir = mnt[1]
            stripped=os.path.abspath(target_dir).lstrip('/')
            path = os.path.join(self.fs_root, stripped)

            if not os.path.exists(path):
                os.makedirs(path)


    def _isMountWritable(self, mnt):
        pass

    def _processNetworkConfig(self):
        if not self.network_enable:
            return ['--unshare-net']
        else
            return []

    def _userNamespace(self):
        """
        Set user namespace settings if set
        :return:
        """

        if self.namespace_uid is not None:
            return ['--unshare-user', '--uid', self.namespace_uid, '--gid', self.namespace_gid]
        else:
            return []

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

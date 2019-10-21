#
#  Copyright (C) 2018 Codethink Limited
#  Copyright (C) 2018-2019 Bloomberg Finance LP
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

import asyncio
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from .. import _signals, utils
from .._message import Message, MessageType
from ..types import FastEnum

_CASD_MAX_LOGFILES = 10

# Note that we want to make sure that BuildStream and buildbox-casd are on the
# same page about what the hostname is, for that reason we may want to avoid
# e.g. empty string as the hostname. We also don't want buildbox-casd to accept
# connections from other machines in this use-case.
#
# Note that buildbox-casd will stop with an error if it fails to listen on all
# addresses, but if it sucessfully listens on any then it will continue. For
# this reason we don't want to choose `localhost` as the hostname, otherwise it
# will also bind to the ipv6 address `::1`.
#
_HOSTNAME = "127.0.0.1"


class ConnectionType(FastEnum):
    UNIX_SOCKET = 0
    LOCALHOST_PORT = 1


# Note that it's necessary to use the LOCALHOST_PORT option on Windows, because
# grpc doesn't support AF_UNIX on win32 yet. You can verify this in the grpc
# source by searching for 'GRPC_HAVE_UNIX_SOCKET'.
#
# There also isn't support in grpc for receiving a WSADuplicateSocket, so we
# can't pass one over. You can verify this in the grpc source by searching for
# 'WSASocket' and noting that the lpProtocolInfo parameter is always null.


# CASDProcessManager
#
# This manages the subprocess that runs buildbox-casd.
#
# Args:
#     path (str): The root directory for the CAS repository
#     log_dir (str): The directory for the logs
#     log_level (LogLevel): Log level to give to buildbox-casd for logging
#     cache_quota (int): User configured cache quota
#     protect_session_blobs (bool): Disable expiry for blobs used in the current session
#     connection_type (ConnectionType): How to connect to the cas daemon
#
class CASDProcessManager:

    def __init__(
            self,
            path,
            log_dir,
            log_level,
            cache_quota,
            protect_session_blobs,
            connection_type=ConnectionType.UNIX_SOCKET,
    ):
        self._log_dir = log_dir

        if connection_type == ConnectionType.UNIX_SOCKET:
            self._connection = _UnixSocketConnection()
        else:
            assert connection_type == ConnectionType.LOCALHOST_PORT
            self._connection = _LocalhostPortConnection()

        casd_args = [utils.get_host_tool('buildbox-casd')]
        casd_args.append('--bind=' + self.connection_string)
        casd_args.append('--log-level=' + log_level.value)

        if cache_quota is not None:
            casd_args.append('--quota-high={}'.format(int(cache_quota)))
            casd_args.append('--quota-low={}'.format(int(cache_quota / 2)))

            if protect_session_blobs:
                casd_args.append('--protect-session-blobs')

        casd_args.append(path)

        self.start_time = time.time()
        self.logfile = self._rotate_and_get_next_logfile()

        with open(self.logfile, "w") as logfile_fp:
            # Block SIGINT on buildbox-casd, we don't need to stop it
            # The frontend will take care of it if needed
            with _signals.blocked([signal.SIGINT], ignore=False):
                self._process = subprocess.Popen(
                    casd_args, cwd=path, stdout=logfile_fp, stderr=subprocess.STDOUT)

        self._failure_callback = None
        self._watcher = None

    @property
    def connection_string(self):
        return self._connection.connection_string

    # _rotate_and_get_next_logfile()
    #
    # Get the logfile to use for casd
    #
    # This will ensure that we don't create too many casd log files by
    # rotating the logs and only keeping _CASD_MAX_LOGFILES logs around.
    #
    # Returns:
    #   (str): the path to the log file to use
    #
    def _rotate_and_get_next_logfile(self):
        try:
            existing_logs = sorted(os.listdir(self._log_dir))
        except FileNotFoundError:
            os.makedirs(self._log_dir)
        else:
            while len(existing_logs) >= _CASD_MAX_LOGFILES:
                logfile_to_delete = existing_logs.pop(0)
                os.remove(os.path.join(self._log_dir, logfile_to_delete))

        return os.path.join(self._log_dir, str(self.start_time) + ".log")

    # release_resources()
    #
    # Terminate the process and release related resources.
    #
    def release_resources(self, messenger=None):
        self._terminate(messenger)
        self._process = None
        self._connection.release_resouces()

    # _terminate()
    #
    # Terminate the buildbox casd process.
    #
    def _terminate(self, messenger=None):
        assert self._watcher is None
        assert self._failure_callback is None

        return_code = self._process.poll()

        if return_code is not None:
            # buildbox-casd is already dead

            if messenger:
                messenger.message(
                    Message(
                        MessageType.BUG,
                        "Buildbox-casd died during the run. Exit code: {}, Logs: {}".format(
                            return_code, self.logfile
                        ),
                    )
                )
            return

        self._process.terminate()

        try:
            # Don't print anything if buildbox-casd terminates quickly
            return_code = self._process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            if messenger:
                cm = messenger.timed_activity("Terminating buildbox-casd")
            else:
                cm = contextlib.suppress()
            with cm:
                try:
                    return_code = self._process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=15)

                    if messenger:
                        messenger.message(
                            Message(MessageType.WARN, "Buildbox-casd didn't exit in time and has been killed")
                        )
                    return

        expected_return_code = 0
        if sys.platform == "win32":
            # Note that the return code is "1" on Windows by definition -
            # `POpen.terminate()` calls `TerminateProcess()`, which specifies
            # the return code for the process. Python specifies "1" as the
            # return code.
            expected_return_code = 1

        if return_code != expected_return_code and messenger:
            messenger.message(
                Message(
                    MessageType.BUG,
                    "Buildbox-casd didn't exit cleanly. Exit code: {}, Logs: {}".format(
                        return_code, self.logfile
                    ),
                )
            )

    # set_failure_callback()
    #
    # Call this function if the CASD process stops unexpectedly.
    #
    # Note that we guarantee that the lifetime of any 'watcher' used is bound
    # to the lifetime of the callback - we won't hang on to the asyncio loop
    # longer than necessary.
    #
    # We won't be able to use watchers on win32, so we'll need to support
    # another approach.
    #
    # Args:
    #   func (callable): a callable that takes no parameters
    #
    def set_failure_callback(self, func):
        assert func is not None
        assert self._watcher is None
        assert self._failure_callback is None, "We only support one callback for now"
        self._failure_callback = func
        self._watcher = asyncio.get_child_watcher()
        self._watcher.add_child_handler(self._process.pid, self._on_casd_failure)

    # clear_failure_callback()
    #
    # No longer call this callable if the CASD process stops unexpectedly
    #
    # Args:
    #   func (callable): The callable that was provided to add_failure_callback().
    #                    Supplying this again allows us to do error checking.
    #
    def clear_failure_callback(self, func):
        assert func is not None
        assert self._failure_callback == func, "We only support one callback for now"
        self._watcher.remove_child_handler(self._process.pid)
        self._failure_callback = None
        self._watcher = None

    # _on_casd_failure()
    #
    # Handler for casd process terminating unexpectedly
    #
    # Args:
    #   pid (int): the process id under which buildbox-casd was running
    #   returncode (int): the return code with which buildbox-casd exited
    #
    def _on_casd_failure(self, pid, returncode):
        assert self._failure_callback is not None
        self._process.returncode = returncode
        self._failure_callback()


class _LocalhostPortConnection:
    def __init__(self):
        # Note that there is a race-condition between us finding an available
        # port and buildbox-casd taking ownership of it. If another process
        # takes the port in the mean time, we will later fail with an error.
        with socket.socket() as s:
            s.bind((_HOSTNAME, 0))
            hostname, port = s.getsockname()
        assert hostname == _HOSTNAME
        self.connection_string = "{}:{}".format(hostname, port)

    def release_resouces(self):
        pass


class _UnixSocketConnection:
    def __init__(self):
        # Place socket in global/user temporary directory to avoid hitting
        # the socket path length limit.
        self._socket_tempdir = tempfile.mkdtemp(prefix='buildstream')
        socket_path = os.path.join(self._socket_tempdir, 'casd.sock')
        self.connection_string = "unix:" + socket_path

    def release_resouces(self):
        shutil.rmtree(self._socket_tempdir)

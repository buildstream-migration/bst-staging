#
#  Copyright (C) 2020 Codethink Limited
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
#        Tristan Van Berkom <tristan.vanberkom@codethink.co.uk>

from contextlib import contextmanager
from typing import Optional, Generator, Tuple

from .node import MappingNode
from .plugin import Plugin
from .types import SourceRef


# PluginProxyError()
#
# The PluginProxyError is raised by PluginProxy objects when an illegal
# method call is called by a Plugin.
#
# This exception does not derive from BstError because it is not a user
# facing error but a Plugin author facing error; the result of a
# PluginProxyError being raised is that BuildStream treats it as an
# unhandled exception, and issues a BUG message with a helpful stacktrace
# which can be helpful for the Plugin author to fix their bugs.
#
class PluginProxyError(Exception):
    pass


# PluginProxy()
#
# Base class for proxies to Plugin instances.
#
# Proxies are handed off to Plugin implementations whenever they observe the data
# model, like when the Element observes it's dependencies, this allows the core to
# do some police work and raise errors when plugins attempt to perform illegal method
# calls.
#
# Refer to the Plugin class for the documentation for these APIs.
#
# In this file we simply raise a PluginProxyError() in the case that a Plugin tries to
# call an illegal API, or we forward the method call along to the underlying Plugin
# instance if the given method call is considered legal.
#
# Args:
#    owner (Plugin): The owning plugin, i.e. the plugin which this proxy was given to
#    plugin (Plugin): The proxied plugin, i.e. the plugin this proxy is attached to
#
class PluginProxy:
    def __init__(self, owner: Plugin, plugin: Plugin):

        # These members are considered internal, they are accessed by subclasses
        # which extend the PluginProxy, but hidden from the client Plugin implementations
        # which the proxy objects are handed off to.
        #
        self._owner = owner  # The Plugin this proxy was given to / created for
        self._plugin = plugin  # The Plugin this proxy was created as a proxy for

    ##############################################################
    #             Properties (for instance members)              #
    ##############################################################
    @property
    def name(self):
        return self._plugin.name

    ##############################################################
    #                  Plugin abstract methods                   #
    ##############################################################
    def configure(self, node: MappingNode) -> None:
        self._raise_illegal_call("Plugin.configure")

    def preflight(self) -> None:
        self._raise_illegal_call("Plugin.preflight")

    def get_unique_key(self) -> SourceRef:  # type: ignore[return]
        self._raise_illegal_call("Plugin.get_unique_key")

    ##############################################################
    #                     Plugin Public APIs                     #
    ##############################################################
    def get_kind(self) -> str:
        return self._plugin.get_kind()

    def node_get_project_path(self, node, *, check_is_file=False, check_is_dir=False) -> str:  # type: ignore[return]
        self._raise_illegal_call("Plugin.node_get_project_path")

    def debug(self, brief: str, *, detail: Optional[str] = None) -> None:
        self._raise_illegal_call("Plugin.debug")

    def status(self, brief: str, *, detail: Optional[str] = None) -> None:
        self._raise_illegal_call("Plugin.status")

    def info(self, brief: str, *, detail: Optional[str] = None) -> None:
        self._raise_illegal_call("Plugin.status")

    def warn(self, brief: str, *, detail: Optional[str] = None, warning_token: Optional[str] = None) -> None:
        self._raise_illegal_call("Plugin.warn")

    def log(self, brief: str, *, detail: Optional[str] = None) -> None:
        self._raise_illegal_call("Plugin.log")

    @contextmanager
    def timed_activity(self, activity_name: str, *, detail: Optional[str] = None, silent_nested: bool = False) -> Generator[None, None, None]:  # type: ignore[return]
        self._raise_illegal_call("Plugin.timed_activity")

    def call(self, *popenargs, fail: Optional[str] = None, fail_temporarily: bool = False, **kwargs) -> int:  # type: ignore[return]
        self._raise_illegal_call("Plugin.call")

    def check_output(self, *popenargs, fail=None, fail_temporarily=False, **kwargs) -> Tuple[int, str]:  # type: ignore[return]
        self._raise_illegal_call("Plugin.check_output")

    ##############################################################
    #                  BuildStream internal methods              #
    ##############################################################

    # _raise_illegal_call():
    #
    # Raise a consistently worded PluginProxyError() for an illegal method call.
    #
    # Args:
    #    method_name (str): The name of the Plugin method, including the class name (e.g.: "Plugin.configure")
    #
    # Raises:
    #    (PluginProxyError): Always.
    #
    def _raise_illegal_call(self, method_name: str) -> None:
        raise PluginProxyError(
            "{}: Illegal method call to '{}' on plugin: {}".format(self._owner, method_name, self._plugin)
        )

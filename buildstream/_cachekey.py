#
#  Copyright (C) 2018 Codethink Limited
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


import hashlib
import pickle

from . import _yaml


# generate_key()
#
# Generate an sha256 hex digest from the given value. The value
# can be a simple value or recursive dictionary with lists etc,
# anything simple enough to serialize.
#
# Args:
#    value: A value to get a key for
#
# Returns:
#    (str): An sha256 hex digest of the given value
#
def generate_key(value):
    ordered = _yaml.node_sanitize(value)
    string = pickle.dumps(ordered)
    return hashlib.sha256(string).hexdigest()


# generate_key_pre_sanitized()
#
# Generate an sha256 hex digest from the given value. The value
# must be (a) compatible with generate_key() and (b) already have
# been passed through _yaml.node_sanitize()
#
# Args:
#    value: A sanitized value to get a key for
#
# Returns:
#    (str): An sha256 hex digest of the given value
#
def generate_key_pre_sanitized(value):
    string = pickle.dumps(value)
    return hashlib.sha256(string).hexdigest()

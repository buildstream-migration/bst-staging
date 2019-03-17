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
#        Tristan Van Berkom <tristan.vanberkom@codethink.co.uk>
#        Jürg Billeter <juerg.billeter@codethink.co.uk>

# BuildStream toplevel imports
from ... import Consistency

# Local imports
from . import Queue, QueueStatus
from ..resources import ResourceType
from ..jobs import JobStatus


# A queue which fetches element sources
#
class FetchQueue(Queue):

    action_name = "Fetch"
    complete_name = "Fetched"
    resources = [ResourceType.DOWNLOAD]

    def __init__(self, scheduler, skip_cached=False, fetch_original=False):
        super().__init__(scheduler)

        self._skip_cached = skip_cached
        self._fetch_original = fetch_original

    def process(self, element):
        element._fetch(fetch_original=self._fetch_original)

    def status(self, element):
        if not element._is_required():
            # Artifact is not currently required but it may be requested later.
            # Keep it in the queue.
            return QueueStatus.WAIT

        # Optionally skip elements that are already in the artifact cache
        if self._skip_cached:
            if not element._can_query_cache():
                return QueueStatus.WAIT

            if element._cached():
                return QueueStatus.SKIP

        # This will automatically skip elements which
        # have no sources.

        if not element._should_fetch(self._fetch_original):
            return QueueStatus.SKIP

        return QueueStatus.READY

    def done(self, _, element, result, status):

        if status == JobStatus.FAIL:
            return

        element._fetch_done()

        # Successful fetch, we must be CACHED now
        assert element._get_consistency() == Consistency.CACHED

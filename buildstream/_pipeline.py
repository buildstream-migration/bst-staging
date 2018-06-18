#!/usr/bin/env python3
#
#  Copyright (C) 2016-2018 Codethink Limited
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
#        Tristan Maat <tristan.maat@codethink.co.uk>

import os
import itertools
from operator import itemgetter

from ._exceptions import PipelineError
from ._message import Message, MessageType
from ._loader import Loader
from ._profile import Topics, profile_start, profile_end
from .element import Element
from . import Scope, Consistency
from ._project import ProjectRefStorage


# PipelineSelection()
#
# Defines the kind of pipeline selection to make when the pipeline
# is provided a list of targets, for whichever purpose.
#
# These values correspond to the CLI `--deps` arguments for convenience.
#
class PipelineSelection():

    # Select only the target elements in the associated targets
    NONE = 'none'

    # Select elements which must be built for the associated targets to be built
    PLAN = 'plan'

    # All dependencies of all targets, including the targets
    ALL = 'all'

    # All direct build dependencies and their recursive runtime dependencies,
    # excluding the targets
    BUILD = 'build'

    # All direct runtime dependencies and their recursive runtime dependencies,
    # including the targets
    RUN = 'run'


# Pipeline()
#
# Args:
#    project (Project): The Project object
#    context (Context): The Context object
#    artifacts (Context): The ArtifactCache object
#
class Pipeline():

    def __init__(self, context, project, artifacts):

        self._context = context     # The Context
        self._project = project     # The toplevel project

        #
        # Private members
        #
        self._artifacts = artifacts
        self._loader = None

    # load()
    #
    # Loads elements from target names.
    #
    # This function is called with a list of lists, such that multiple
    # target groups may be specified. Element names specified in `targets`
    # are allowed to be redundant.
    #
    # Args:
    #    target_groups (list of lists): Groups of toplevel targets to load
    #    fetch_subprojects (bool): Whether we should fetch subprojects as a part of the
    #                              loading process, if they are not yet locally cached
    #    rewritable (bool): Whether the loaded files should be rewritable
    #                       this is a bit more expensive due to deep copies
    #
    # Returns:
    #    (tuple of lists): A tuple of grouped Element objects corresponding to target_groups
    #
    def load(self, target_groups, *,
             fetch_subprojects=True,
             rewritable=False):

        # First concatenate all the lists for the loader's sake
        targets = list(itertools.chain(*target_groups))

        profile_start(Topics.LOAD_PIPELINE, "_".join(t.replace(os.sep, '-') for t in targets))

        self._loader = Loader(self._context, self._project, targets,
                              fetch_subprojects=fetch_subprojects)

        with self._context.timed_activity("Loading pipeline", silent_nested=True):
            meta_elements = self._loader.load(rewritable, None)

        # Resolve the real elements now that we've loaded the project
        with self._context.timed_activity("Resolving pipeline"):
            elements = [
                Element._new_from_meta(meta, self._artifacts)
                for meta in meta_elements
            ]

        # Now warn about any redundant source references which may have
        # been discovered in the resolve() phase.
        redundant_refs = Element._get_redundant_source_refs()
        if redundant_refs:
            detail = "The following inline specified source references will be ignored:\n\n"
            lines = [
                "{}:{}".format(source._get_provenance(), ref)
                for source, ref in redundant_refs
            ]
            detail += "\n".join(lines)
            self._message(MessageType.WARN, "Ignoring redundant source references", detail=detail)

        # Now create element groups to match the input target groups
        elt_iter = iter(elements)
        element_groups = [
            [next(elt_iter) for i in range(len(group))]
            for group in target_groups
        ]

        profile_end(Topics.LOAD_PIPELINE, "_".join(t.replace(os.sep, '-') for t in targets))

        return tuple(element_groups)

    # resolve_elements()
    #
    # Resolve element state and cache keys.
    #
    # Args:
    #    targets (list of Element): The list of toplevel element targets
    #
    def resolve_elements(self, targets):
        with self._context.timed_activity("Resolving cached state", silent_nested=True):
            for element in self.dependencies(targets, Scope.ALL):

                # Preflight
                element._preflight()

                # Determine initial element state.
                element._update_state()

    # dependencies()
    #
    # Generator function to iterate over elements and optionally
    # also iterate over sources.
    #
    # Args:
    #    targets (list of Element): The target Elements to loop over
    #    scope (Scope): The scope to iterate over
    #    recurse (bool): Whether to recurse into dependencies
    #
    def dependencies(self, targets, scope, *, recurse=True):
        # Keep track of 'visited' in this scope, so that all targets
        # share the same context.
        visited = {}

        for target in targets:
            for element in target.dependencies(scope, recurse=recurse, visited=visited):
                yield element

    # plan()
    #
    # Generator function to iterate over only the elements
    # which are required to build the pipeline target, omitting
    # cached elements. The elements are yielded in a depth sorted
    # ordering for optimal build plans
    #
    # Args:
    #    elements (list of Element): List of target elements to plan
    #
    # Returns:
    #    (list of Element): A depth sorted list of the build plan
    #
    # Args:
    #    directory (str): The directory to stage the source in
    #    no_checkout (bool): Whether to skip checking out the source
    #    track_first (bool): Whether to track and fetch first
    #    force (bool): Whether to ignore contents in an existing directory
    #
    def open_workspace(self, scheduler, directory, no_checkout, track_first, force):
        # When working on workspaces we only have one target
        target = self.targets[0]
        workdir = os.path.abspath(directory)
        projectdir = self.project.directory
        is_relative = False
        if workdir.startswith(projectdir):
            is_relative = True
            workdir = os.path.relpath(workdir, projectdir)

        if not list(target.sources()):
            build_depends = [x.name for x in target.dependencies(Scope.BUILD, recurse=False)]
            if not build_depends:
                raise PipelineError("The given element has no sources or build-dependencies")
            detail = "Try opening a workspace on one of its dependencies instead:\n"
            detail += "  \n".join(build_depends)
            raise PipelineError("The given element has no sources", detail=detail)

        # Check for workspace config
        if self.project._get_workspace(target.name):
            raise PipelineError("Workspace '{}' is already defined."
                                .format(target.name))

        plan = [target]

        # Track/fetch if required
        queues = []
        track = None

        if track_first:
            track = TrackQueue()
            queues.append(track)
        if not no_checkout or track_first:
            fetch = FetchQueue(skip_cached=True)
            queues.append(fetch)

        if queues:
            queues[0].enqueue(plan)

            elapsed, status = scheduler.run(queues)
            fetched = len(fetch.processed_elements)

            if status == SchedStatus.ERROR:
                self.message(MessageType.FAIL, "Tracking failed", elapsed=elapsed)
                raise PipelineError()
            elif status == SchedStatus.TERMINATED:
                self.message(MessageType.WARN,
                             "Terminated after fetching {} elements".format(fetched),
                             elapsed=elapsed)
                raise PipelineError()
            else:
                self.message(MessageType.SUCCESS,
                             "Fetched {} elements".format(fetched), elapsed=elapsed)

        if not no_checkout and target._consistency() != Consistency.CACHED:
            raise PipelineError("Could not stage uncached source. " +
                                "Use `--track` to track and " +
                                "fetch the latest version of the " +
                                "source.")

        # Check directory
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as e:
            raise PipelineError("Failed to create workspace directory: {}".format(e)) from e

        if not no_checkout:
            if not force and os.listdir(directory):
                raise PipelineError("Checkout directory is not empty: {}".format(directory))

            with target.timed_activity("Staging sources to {}".format(directory)):
                for source in target.sources():
                    source._init_workspace(directory)

        if is_relative:
            workdir = os.path.join(projectdir, workdir)
        self.project._set_workspace(target, workdir)

    # get_selection()
    #
    # Gets a full list of elements based on a toplevel
    # list of element targets
    #
    # Args:
    #    targets (list of Element): The target Elements
    #    mode (PipelineSelection): The PipelineSelection mode
    #
    # Various commands define a --deps option to specify what elements to
    # use in the result, this function reports a list that is appropriate for
    # the selected option.
    #
    def get_selection(self, targets, mode, *, silent=True):

        elements = None
        if mode == PipelineSelection.NONE:
            # Redirect and log if permitted
            elements = []
            for t in targets:
                new_elm = t._get_source_element()
                if new_elm != t and not silent:
                    self._message(MessageType.INFO, "Element '{}' redirected to '{}'"
                                  .format(t.name, new_elm.name))
                if new_elm not in elements:
                    elements.append(new_elm)
        elif mode == PipelineSelection.PLAN:
            elements = self.plan(targets)
        else:
            if mode == PipelineSelection.ALL:
                scope = Scope.ALL
            elif mode == PipelineSelection.BUILD:
                scope = Scope.BUILD
            elif mode == PipelineSelection.RUN:
                scope = Scope.RUN

            elements = list(self.dependencies(targets, scope))

        return elements

    # except_elements():
    #
    # Return what we are left with after the intersection between
    # excepted and target elements and their unique dependencies is
    # gone.
    #
    # Args:
    #    targets (list of Element): List of toplevel targetted elements
    #    elements (list of Element): The list to remove elements from
    #    except_targets (list of Element): List of toplevel except targets
    #
    # Returns:
    #    (list of Element): The elements list with the intersected
    #                       exceptions removed
    #
    def except_elements(self, targets, elements, except_targets):
        targeted = list(self.dependencies(targets, Scope.ALL))
        visited = []

        def find_intersection(element):
            if element in visited:
                return
            visited.append(element)

            # Intersection elements are those that are also in
            # 'targeted', as long as we don't recurse into them.
            if element in targeted:
                yield element
            else:
                for dep in element.dependencies(Scope.ALL, recurse=False):
                    yield from find_intersection(dep)

        # Build a list of 'intersection' elements, i.e. the set of
        # elements that lie on the border closest to excepted elements
        # between excepted and target elements.
        intersection = list(itertools.chain.from_iterable(
            find_intersection(element) for element in except_targets
        ))

        # Now use this set of elements to traverse the targeted
        # elements, except 'intersection' elements and their unique
        # dependencies.
        queue = []
        visited = []

        queue.extend(targets)
        while queue:
            element = queue.pop()
            if element in visited or element in intersection:
                continue
            visited.append(element)

            queue.extend(element.dependencies(Scope.ALL, recurse=False))

        # That looks like a lot, but overall we only traverse (part
        # of) the graph twice. This could be reduced to once if we
        # kept track of parent elements, but is probably not
        # significant.

        # Ensure that we return elements in the same order they were
        # in before.
        return [element for element in elements if element in visited]

    # targets_include()
    #
    # Checks whether the given targets are, or depend on some elements
    #
    # Args:
    #    targets (list of Element): A list of targets
    #    elements (list of Element): List of elements to check
    #
    # Returns:
    #    (bool): True if all of `elements` are the `targets`, or are
    #            somehow depended on by `targets`.
    #
    def targets_include(self, targets, elements):
        target_element_set = set(self.dependencies(targets, Scope.ALL))
        element_set = set(elements)
        return element_set.issubset(target_element_set)

    # subtract_elements()
    #
    # Subtract a subset of elements
    #
    # Args:
    #    elements (list of Element): The element list
    #    subtract (list of Element): List of elements to subtract from elements
    #
    # Returns:
    #    (list): The original elements list, with elements in subtract removed
    #
    def subtract_elements(self, elements, subtract):
        subtract_set = set(subtract)
        return [
            e for e in elements
            if e not in subtract_set
        ]

    # track_cross_junction_filter()
    #
    # Filters out elements which are across junction boundaries,
    # otherwise asserts that there are no such elements.
    #
    # This is currently assumed to be only relevant for element
    # lists targetted at tracking.
    #
    # Args:
    #    project (Project): Project used for cross_junction filtering.
    #                       All elements are expected to belong to that project.
    #    elements (list of Element): The list of elements to filter
    #    cross_junction_requested (bool): Whether the user requested
    #                                     cross junction tracking
    #
    # Returns:
    #    (list of Element): The filtered or asserted result
    #
    def track_cross_junction_filter(self, project, elements, cross_junction_requested):
        # Filter out cross junctioned elements
        if not cross_junction_requested:
            elements = self._filter_cross_junctions(project, elements)
        self._assert_junction_tracking(elements)

        return elements

    # assert_consistent()
    #
    # Asserts that the given list of elements are in a consistent state, that
    # is to say that all sources are consistent and can at least be fetched.
    #
    # Consequently it also means that cache keys can be resolved.
    #
    def assert_consistent(self, elements):
        inconsistent = []
        with self._context.timed_activity("Checking sources"):
            for element in elements:
                if element._get_consistency() == Consistency.INCONSISTENT:
                    inconsistent.append(element)

        if inconsistent:
            detail = "Exact versions are missing for the following elements\n" + \
                     "Try tracking these elements first with `bst track`\n\n"
            for element in inconsistent:
                detail += "  " + element._get_full_name() + "\n"
            raise PipelineError("Inconsistent pipeline", detail=detail, reason="inconsistent-pipeline")

    # cleanup()
    #
    # Cleans up resources used by the Pipeline.
    #
    def cleanup(self):
        if self._loader:
            self._loader.cleanup()

        # Reset the element loader state
        Element._reset_load_state()

    #############################################################
    #                     Private Methods                       #
    #############################################################

    # _filter_cross_junction()
    #
    # Filters out cross junction elements from the elements
    #
    # Args:
    #    project (Project): The project on which elements are allowed
    #    elements (list of Element): The list of elements to be tracked
    #
    # Returns:
    #    (list): A filtered list of `elements` which does
    #            not contain any cross junction elements.
    #
    def _filter_cross_junctions(self, project, elements):
        return [
            element for element in elements
            if element._get_project() is project
        ]

    # _assert_junction_tracking()
    #
    # Raises an error if tracking is attempted on junctioned elements and
    # a project.refs file is not enabled for the toplevel project.
    #
    # Args:
    #    elements (list of Element): The list of elements to be tracked
    #
    def _assert_junction_tracking(self, elements):

        # We can track anything if the toplevel project uses project.refs
        #
        if self._project.ref_storage == ProjectRefStorage.PROJECT_REFS:
            return

        # Ideally, we would want to report every cross junction element but not
        # their dependencies, unless those cross junction elements dependencies
        # were also explicitly requested on the command line.
        #
        # But this is too hard, lets shoot for a simple error.
        for element in elements:
            element_project = element._get_project()
            if element_project is not self._project:
                detail = "Requested to track sources across junction boundaries\n" + \
                         "in a project which does not use project.refs ref-storage."

                raise PipelineError("Untrackable sources", detail=detail, reason="untrackable-sources")

    # _message()
    #
    # Local message propagator
    #
    def _message(self, message_type, message, **kwargs):
        args = dict(kwargs)
        self._context.message(
            Message(None, message_type, message, **args))


# _Planner()
#
# An internal object used for constructing build plan
# from a given resolved toplevel element, while considering what
# parts need to be built depending on build only dependencies
# being cached, and depth sorting for more efficient processing.
#
class _Planner():
    def __init__(self):
        self.depth_map = {}
        self.visiting_elements = set()

    # Here we want to traverse the same element more than once when
    # it is reachable from multiple places, with the interest of finding
    # the deepest occurance of every element
    def plan_element(self, element, depth):
        if element in self.visiting_elements:
            # circular dependency, already being processed
            return

        prev_depth = self.depth_map.get(element)
        if prev_depth is not None and prev_depth >= depth:
            # element and dependencies already processed at equal or greater depth
            return

        self.visiting_elements.add(element)
        for dep in element.dependencies(Scope.RUN, recurse=False):
            self.plan_element(dep, depth)

        # Dont try to plan builds of elements that are cached already
        if not element._cached():
            for dep in element.dependencies(Scope.BUILD, recurse=False):
                self.plan_element(dep, depth + 1)

        self.depth_map[element] = depth
        self.visiting_elements.remove(element)

    def plan(self, roots, plan_cached):
        for root in roots:
            self.plan_element(root, 0)

        depth_sorted = sorted(self.depth_map.items(), key=itemgetter(1), reverse=True)
        return [item[0] for item in depth_sorted if plan_cached or not item[0]._cached()]

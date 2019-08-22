#
#  Copyright (C) 2019 Bloomberg Finance LP
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
#        Angelos Evripiotis <jevripiotis@bloomberg.net>


import copyreg
import io
import pickle

from ..._protos.buildstream.v2.artifact_pb2 import Artifact as ArtifactProto

# BuildStream toplevel imports
from ..._loader import Loader
from ..._messenger import Messenger


# pickle_child_job()
#
# Perform the special case pickling required to pickle a child job for
# unpickling in a child process.
#
# Note that we don't need an `unpickle_child_job`, as regular `pickle.load()`
# will do everything required.
#
# Args:
#    child_job     (ChildJob): The job to be pickled.
#    projects (List[Project]): The list of loaded projects, so we can get the
#                              relevant factories.
#
# Returns:
#    An `io.BytesIO`, with the pickled contents of the ChildJob and everything it
#    transitively refers to.
#
# Some types require special handling when pickling to send to another process.
# We register overrides for those special cases:
#
# o Very stateful objects: Some things carry much more state than they need for
#   pickling over to the child job process. This extra state brings
#   complication of supporting pickling of more types, and the performance
#   penalty of the actual pickling. Use private knowledge of these objects to
#   safely reduce the pickled state.
#
# o gRPC objects: These don't pickle, but they do have their own serialization
#   mechanism, which we use instead. To avoid modifying generated code, we
#   instead register overrides here.
#
# o Plugins: These cannot be unpickled unless the factory which created them
#   has been unpickled first, with the same identifier as before. See note
#   below. Some state in plugins is not necessary for child jobs, and comes
#   with a heavy cost; we also need to remove this before pickling.
#
def pickle_child_job(child_job, projects):

    element_classes = [
        cls
        for p in projects
        if p.config.element_factory is not None
        for cls, _ in p.config.element_factory.all_loaded_plugins()
    ]
    source_classes = [
        cls
        for p in projects
        if p.config.source_factory is not None
        for cls, _ in p.config.source_factory.all_loaded_plugins()
    ]

    data = io.BytesIO()
    pickler = pickle.Pickler(data)
    pickler.dispatch_table = copyreg.dispatch_table.copy()

    for cls in element_classes:
        pickler.dispatch_table[cls] = _reduce_plugin
    for cls in source_classes:
        pickler.dispatch_table[cls] = _reduce_plugin
    pickler.dispatch_table[ArtifactProto] = _reduce_artifact_proto
    pickler.dispatch_table[Loader] = _reduce_object
    pickler.dispatch_table[Messenger] = _reduce_object

    # import buildstream.testpickle
    # test_pickler = buildstream.testpickle.TestPickler()
    # test_pickler.dispatch_table = pickler.dispatch_table.copy()
    # test_pickler.test_dump(child_job)

    pickler.dump(child_job)
    data.seek(0)

    path = f"{child_job.action_name}_{child_job._task_id}"
    with open(path, "wb") as f:
        f.write(data.getvalue())

    return data


def _reduce_object(instance):
    cls = type(instance)
    state = instance.get_state_for_child_job_pickling()
    return (cls.__new__, (cls,), state)


def _reduce_artifact_proto(instance):
    assert isinstance(instance, ArtifactProto)
    data = instance.SerializeToString()
    return (_new_artifact_proto_from_reduction_args, (data,))


def _new_artifact_proto_from_reduction_args(data):
    instance = ArtifactProto()
    instance.ParseFromString(data)
    return instance


def _reduce_plugin(plugin):
    factory, meta_kind, state = plugin._get_args_for_child_job_pickling()
    args = (factory, meta_kind)
    return (_new_plugin_from_reduction_args, args, state)


def _new_plugin_from_reduction_args(factory, meta_kind):
    cls, _ = factory.lookup(meta_kind)
    plugin = cls.__new__(cls)

    # Note that we rely on the `__project` member of the Plugin to keep
    # `factory` alive after the scope of this function. If `factory` were to be
    # GC'd then we would see undefined behaviour.

    return plugin

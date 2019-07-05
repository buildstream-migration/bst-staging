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
#        Raoul Hidalgo Charman <raoul.hidalgocharman@codethink.co.uk>
#

# Pylint doesn't play well with fixtures and dependency injection from pytest
# pylint: disable=redefined-outer-name

import os
import shutil
import pytest

from buildstream._context import Context
from buildstream._project import Project

from buildstream.testing.runcli import cli  # pylint: disable=unused-import
from tests.testutils.element_generators import create_element_size


DATA_DIR = os.path.dirname(os.path.realpath(__file__))


def dummy_message_handler(message, is_silenced):
    pass


# walk that removes the root directory from roots
def relative_walk(rootdir):
    for root, dirnames, filenames in os.walk(rootdir):
        relative_root = root.split(rootdir)[1]
        yield (relative_root, dirnames, filenames)


@pytest.mark.datafiles(DATA_DIR)
def test_source_staged(tmpdir, cli, datafiles):
    project_dir = os.path.join(datafiles.dirname, datafiles.basename, 'project')
    cachedir = os.path.join(str(tmpdir), 'cache')

    cli.configure({
        'cachedir': cachedir
    })

    # set up minimal context
    context = Context()
    context.load()

    # load project and sourcecache
    project = Project(project_dir, context)
    project.ensure_fully_loaded()
    context.cachedir = cachedir
    context.messenger.set_message_handler(dummy_message_handler)
    sourcecache = context.sourcecache
    cas = context.get_cascache()

    res = cli.run(project=project_dir, args=["build", "import-bin.bst"])
    res.assert_success()

    # now check that the source is in the refs file, this is pretty messy but
    # seems to be the only way to get the sources?
    element = project.load_elements(["import-bin.bst"])[0]
    source = list(element.sources())[0]
    assert element._source_cached()
    assert sourcecache.contains(source)

    # Extract the file and check it's the same as the one we imported
    ref = source._get_source_name()
    digest = cas.resolve_ref(ref)
    extractdir = os.path.join(str(tmpdir), "extract")
    cas.checkout(extractdir, digest)
    dir1 = extractdir
    dir2 = os.path.join(project_dir, "files", "bin-files")

    assert list(relative_walk(dir1)) == list(relative_walk(dir2))


# Check sources are staged during a fetch
@pytest.mark.datafiles(DATA_DIR)
def test_source_fetch(tmpdir, cli, datafiles):
    project_dir = os.path.join(datafiles.dirname, datafiles.basename, 'project')
    cachedir = os.path.join(str(tmpdir), 'cache')

    cli.configure({
        'cachedir': cachedir
    })

    # set up minimal context
    context = Context()
    context.load()

    # load project and sourcecache
    project = Project(project_dir, context)
    project.ensure_fully_loaded()
    context.cachedir = cachedir
    context.messenger.set_message_handler(dummy_message_handler)
    cas = context.get_cascache()

    res = cli.run(project=project_dir, args=["source", "fetch", "import-dev.bst"])
    res.assert_success()

    element = project.load_elements(["import-dev.bst"])[0]
    source = list(element.sources())[0]
    assert element._source_cached()

    # check that the directory structures are idetical
    ref = source._get_source_name()
    digest = cas.resolve_ref(ref)
    extractdir = os.path.join(str(tmpdir), "extract")
    cas.checkout(extractdir, digest)
    dir1 = extractdir
    dir2 = os.path.join(project_dir, "files", "dev-files")

    assert list(relative_walk(dir1)) == list(relative_walk(dir2))


# Check that with sources only in the CAS build successfully completes
@pytest.mark.datafiles(DATA_DIR)
def test_staged_source_build(tmpdir, datafiles, cli):
    project_dir = os.path.join(datafiles.dirname, datafiles.basename, 'project')
    cachedir = os.path.join(str(tmpdir), 'cache')
    element_path = 'elements'
    source_refs = os.path.join(str(tmpdir), 'cache', 'cas', 'refs', 'heads', '@sources')
    source_dir = os.path.join(str(tmpdir), 'cache', 'sources')

    cli.configure({
        'cachedir': os.path.join(str(tmpdir), 'cache')
    })

    create_element_size('target.bst', project_dir, element_path, [], 10000)

    # get the source object
    context = Context()
    context.load()
    project = Project(project_dir, context)
    project.ensure_fully_loaded()
    context.cachedir = cachedir
    context.messenger.set_message_handler(dummy_message_handler)

    element = project.load_elements(["import-dev.bst"])[0]

    # check consistency of the source
    assert not element._source_cached()

    res = cli.run(project=project_dir, args=['build', 'target.bst'])
    res.assert_success()

    # delete artifacts check state is buildable
    cli.remove_artifact_from_cache(project_dir, 'target.bst')
    states = cli.get_element_states(project_dir, ['target.bst'])
    assert states['target.bst'] == 'buildable'

    # delete source dir and check that state is still buildable
    shutil.rmtree(source_dir)
    states = cli.get_element_states(project_dir, ['target.bst'])
    assert states['target.bst'] == 'buildable'

    # build and check that no fetching was done.
    res = cli.run(project=project_dir, args=['build', 'target.bst'])
    res.assert_success()
    assert 'Fetching from' not in res.stderr

    # assert the source directory is still empty (though there may be
    # directories from staging etc.)
    files = []
    for _, _, filename in os.walk(source_dir):
        files.extend(filename)
    assert files == []

    # Now remove the source refs and check the state
    shutil.rmtree(source_refs)
    cli.remove_artifact_from_cache(project_dir, 'target.bst')
    states = cli.get_element_states(project_dir, ['target.bst'])
    assert states['target.bst'] == 'fetch needed'

    # Check that it now fetches from when building the target
    res = cli.run(project=project_dir, args=['build', 'target.bst'])
    res.assert_success()
    assert 'Fetching from' in res.stderr

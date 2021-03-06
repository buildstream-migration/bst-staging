import os
import shutil
import pytest
from tests.testutils import cli, create_artifact_share

from buildstream import _yaml

# Project directory
DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "project",
)


# Assert that a given artifact is in the share
#
def assert_shared(cli, share, project, element_name):
    # NOTE: 'test' here is the name of the project
    # specified in the project.conf we are testing with.
    #
    cache_key = cli.get_element_key(project, element_name)
    if not share.has_artifact('test', element_name, cache_key):
        raise AssertionError("Artifact share at {} does not contain the expected element {}"
                             .format(share.repo, element_name))


@pytest.mark.datafiles(DATA_DIR)
def test_push_pull(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    share = create_artifact_share(os.path.join(str(tmpdir), 'artifactshare'))

    # First build it without the artifact cache configured
    result = cli.run(project=project, args=['build', 'import-bin.bst'])
    assert result.exit_code == 0

    # Assert that we are now cached locally
    state = cli.get_element_state(project, 'import-bin.bst')
    assert state == 'cached'

    # Configure artifact share
    cli.configure({
        'artifacts': {
            'pull-url': share.repo,
            'push-url': share.repo,
        }
    })

    # Now try bst push
    result = cli.run(project=project, args=['push', 'import-bin.bst'])
    assert result.exit_code == 0

    # And finally assert that the artifact is in the share
    assert_shared(cli, share, project, 'import-bin.bst')

    # Make sure we update the summary in our artifact share,
    # we dont have a real server around to do it
    #
    share.update_summary()

    # Now we've pushed, delete the user's local artifact cache
    # directory and try to redownload it from the share
    #
    artifacts = os.path.join(cli.directory, 'artifacts')
    shutil.rmtree(artifacts)

    # Assert that we are now in a downloadable state, nothing
    # is cached locally anymore
    state = cli.get_element_state(project, 'import-bin.bst')
    assert state == 'downloadable'

    # Now try bst pull
    result = cli.run(project=project, args=['pull', 'import-bin.bst'])
    assert result.exit_code == 0

    # And assert that it's again in the local cache, without having built
    state = cli.get_element_state(project, 'import-bin.bst')
    assert state == 'cached'


@pytest.mark.datafiles(DATA_DIR)
def test_push_pull_all(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    share = create_artifact_share(os.path.join(str(tmpdir), 'artifactshare'))

    # First build it without the artifact cache configured
    result = cli.run(project=project, args=['build', 'target.bst'])
    assert result.exit_code == 0

    # Assert that we are now cached locally
    state = cli.get_element_state(project, 'target.bst')
    assert state == 'cached'

    # Configure artifact share
    cli.configure({
        #
        # FIXME: This test hangs "sometimes" if we allow
        #        concurrent push.
        #
        #        It's not too bad to ignore since we're
        #        using the local artifact cache functionality
        #        only, but it should probably be fixed.
        #
        'scheduler': {
            'pushers': 1
        },
        'artifacts': {
            'pull-url': share.repo,
            'push-url': share.repo,
        }
    })

    # Now try bst push
    result = cli.run(project=project, args=['push', '--deps', 'all', 'target.bst'])
    assert result.exit_code == 0

    # And finally assert that the artifact is in the share
    all_elements = ['target.bst', 'import-bin.bst', 'import-dev.bst', 'compose-all.bst']
    for element_name in all_elements:
        assert_shared(cli, share, project, element_name)

    # Make sure we update the summary in our artifact share,
    # we dont have a real server around to do it
    #
    share.update_summary()

    # Now we've pushed, delete the user's local artifact cache
    # directory and try to redownload it from the share
    #
    artifacts = os.path.join(cli.directory, 'artifacts')
    shutil.rmtree(artifacts)

    # Assert that we are now in a downloadable state, nothing
    # is cached locally anymore
    for element_name in all_elements:
        state = cli.get_element_state(project, element_name)
        assert state == 'downloadable'

    # Now try bst pull
    result = cli.run(project=project, args=['pull', '--deps', 'all', 'target.bst'])
    assert result.exit_code == 0

    # And assert that it's again in the local cache, without having built
    for element_name in all_elements:
        state = cli.get_element_state(project, element_name)
        assert state == 'cached'

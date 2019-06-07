# Pylint doesn't play well with fixtures and dependency injection from pytest
# pylint: disable=redefined-outer-name

import os
import pytest

from buildstream.testing import cli_integration as cli  # pylint: disable=unused-import
from buildstream.testing._utils.site import HAVE_BWRAP, IS_LINUX


pytestmark = pytest.mark.integration
DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', '..', 'doc', 'examples', 'integration-commands'
)


@pytest.mark.skipif(not IS_LINUX or not HAVE_BWRAP, reason='Only available on linux with bubblewrap')
@pytest.mark.datafiles(DATA_DIR)
def test_integration_commands_build(cli, datafiles):
    project = str(datafiles)

    result = cli.run(project=project, args=['build', 'hello.bst'])
    assert result.exit_code == 0


# Test running the executable
@pytest.mark.skipif(not IS_LINUX or not HAVE_BWRAP, reason='Only available on linux with bubblewrap')
@pytest.mark.datafiles(DATA_DIR)
def test_integration_commands_run(cli, datafiles):
    project = str(datafiles)

    result = cli.run(project=project, args=['build', 'hello.bst'])
    assert result.exit_code == 0

    result = cli.run(project=project, args=['shell', 'hello.bst', '--', 'hello', 'pony'])
    assert result.exit_code == 0
    assert result.output == 'Hello pony\n'

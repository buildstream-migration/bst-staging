import os
import pytest

from buildstream import _yaml

from tests.testutils import cli_integration as cli
from tests.testutils.integration import assert_contains


pytestmark = pytest.mark.integration

DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "project"
)


@pytest.mark.datafiles(DATA_DIR)
def test_build_uid(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    checkout = os.path.join(cli.directory, 'checkout')
    element_name = 'build-uid/build-uid.bst'

    result = cli.run(project=project, args=['build', element_name])
    assert result.exit_code == 0


@pytest.mark.datafiles(DATA_DIR)
def test_build_uid_default(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    checkout = os.path.join(cli.directory, 'checkout')
    element_name = 'build-uid/build-uid-default.bst'

    result = cli.run(project=project, args=['build', element_name])
    assert result.exit_code == 0

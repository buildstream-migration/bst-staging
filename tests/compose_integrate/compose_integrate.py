import os
import pytest
import fnmatch
from tests.testutils.runcli import cli
from buildstream import _yaml
from buildstream import utils

# Project directory
DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "project",
)


def get_expected_files(op, split):
    envs = {
        'A': ['file-A-1',
              'sub/subfile-A-1',
              'file-A-2',
              'sub/subfile-A-2'],
        'B': ['file-B-1',
              'sub/subfile-B-1',
              'file-B-2',
              'sub/subfile-B-2'],
        'orphans': ['file-C-1',
                    'file-C-2']
    }

    orphans = 'include_orphans' not in split or split['include_orphans']
    if 'include' in split:
        included = set(split['include'])
    else:
        included = set(['A', 'B'])
    if orphans:
        included.add('orphans')

    if 'exclude' in split:
        for e in split['exclude']:
            included.remove(e)

    files = set([f for i in included for f in envs[i]])

    if op == 'add-file':
        files.add('file-C')
    elif op == 'touch-file':
        files.add('file-A-1')
    elif op == 'remove-file':
        files.discard('file-A-1')
    elif op == 'make-dir':
        files.add('sub2/subfile2')
    elif op == 'remove-dir':
        files.discard('sub/subfile-A-1')
        files.discard('sub/subfile-B-1')
        files.discard('sub/subfile-A-2')
        files.discard('sub/subfile-B-2')

    return files


@pytest.mark.parametrize("op",
                         ['add-file',
                          'make-dir',
                          'remove-dir',
                          'remove-file',
                          'touch-file'])
@pytest.mark.parametrize("split",
                         [{},
                          {'include': ['A']},
                          {'include': ['B']},
                          {'exclude': ['A']},
                          {'exclude': ['B']}])
@pytest.mark.datafiles(DATA_DIR)
def test_compose_integrate(datafiles, cli, op, split):
    project = os.path.join(datafiles.dirname, datafiles.basename)

    bst = {
        'kind': 'compose',
        'config': split,
        'depends': [
            {'filename': '{}.bst'.format(op),
             'type': 'build'},
            {'filename': 'import-2.bst',
             'type': 'build'}
        ]
    }
    _yaml.dump(bst, os.path.join(project, 'elements', 'target.bst'))

    expected_files = get_expected_files(op, split)

    checkout = os.path.join(cli.directory, 'checkout')

    # First build it
    result = cli.run(project=project, args=['build', 'target.bst'])
    assert result.exit_code == 0

    # Now check it out
    result = cli.run(project=project, args=[
        'checkout', 'target.bst', checkout
    ])
    assert result.exit_code == 0

    found_files = set(utils.list_relative_paths(checkout))
    assert found_files == expected_files


@pytest.mark.datafiles(DATA_DIR)
def test_compose_integrate_replace_directory_with_symbolic_link(datafiles, cli):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    checkout = os.path.join(cli.directory, 'checkout')

    # First build it
    result = cli.run(project=project, args=['build', 'compose-with-symlink.bst'])
    assert result.exit_code == 0

    # Now check it out
    result = cli.run(project=project, args=[
        'checkout', 'compose-with-symlink.bst', checkout
    ])
    assert result.exit_code == 0

    linkpath = os.path.join(checkout, 'sub', 'subfile-A-1')
    assert os.path.exists(linkpath)

    realpath = os.path.realpath(linkpath)
    expected_realpath = os.path.join(os.path.realpath(checkout), 'sub2', 'subfile-A-1')
    assert realpath == expected_realpath

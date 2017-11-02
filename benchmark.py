"""Measure the performance of BuildStream CLI from the user's perspective."""

import argparse
import collections
import contextlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--samples',
        type=int,
        default=3,
        help='How many times to repeat each measurement')
    parser.add_argument(
        '--erase-buildstream-cache',
        action='store_true')
    args = parser.parse_args()

    # run_benchmark(args, benchmark_python)
    # run_benchmark(args, benchmark_help)
    # run_benchmark_series(
    #     args,
    #     benchmark_import_local_files,
    #     (1, 5, 10, 20, 50, 100, 120, 150, 200))
    run_benchmark_series(
        args,
        benchmark_import_files_tar,
        range(1, 200 * 1000, 10 * 1000))


def benchmark_python(timer):
    with timer.context():
        run('python3', '-c', 'print("hello")')


def benchmark_help(timer):
    with timer.context():
        run('bst', '--help')


def benchmark_import_local_files(timer, num_files):
    with make_bst_project() as p:
        write_random_files(p.working_dir, 'files', num_files)
        p.write_file('import.bst', make_local_import_text('files/'))
        p.write_file('compose.bst', make_single_compose_text('import.bst'))

        with timer.context('show compose element'):
            p.bst('show', 'compose.bst')
        with timer.context('build import element'):
            p.bst('build', 'import.bst')
        with timer.context('build compose element'):
            p.bst('build', 'compose.bst')


def benchmark_import_files_tar(timer, num_files):
    with make_bst_project() as p:
        write_random_files(p.working_dir, 'files', num_files)
        tar_gz_directory(
            os.path.join(p.working_dir, 'files.tar.gz'),
            os.path.join(p.working_dir, 'files/'))
        shutil.rmtree(os.path.join(p.working_dir, 'files/'))

        p.write_file('import.bst', make_tar_import_text('files.tar.gz'))
        p.write_file('compose.bst', make_single_compose_text('import.bst'))

        with timer.context('track import element'):
            p.bst('track', 'import.bst')
        with timer.context('show compose element'):
            p.bst('show', 'compose.bst')
        with timer.context('build import element'):
            p.bst('build', 'import.bst')
        with timer.context('build compose element'):
            p.bst('build', 'compose.bst')


def run_benchmark(args, benchmark_fn):
    timer = Timer()
    for i in range(args.samples):
        if args.erase_buildstream_cache:
            erase_buildstream_cache()
        benchmark_fn(timer)

    for key in timer.ordered_names:
        name = benchmark_fn.__name__[len('benchmark_'):]
        if key is not None:
            name += ': ' + key
        print(
            name,
            '{:.2f}'.format(timer.elapsed[key] / args.samples),
            sep=',')


def run_benchmark_series(args, benchmark_fn, series):
    for item in series:
        timer = Timer()
        for i in range(args.samples):
            if args.erase_buildstream_cache:
                erase_buildstream_cache()
            benchmark_fn(timer, item)

        for key in timer.ordered_names:
            name = benchmark_fn.__name__[len('benchmark_'):]
            if key is not None:
                name += ':' + key
            print(
                name,
                item,
                '{:.2f}'.format(timer.elapsed[key] / args.samples),
                sep=',')


class Timer:

    def __init__(self):
        self.elapsed = collections.defaultdict(lambda: 0.0)
        self.ordered_names = []

    @contextlib.contextmanager
    def context(self, name=None):
        if name not in self.elapsed:
            self.ordered_names.append(name)
        t = time.perf_counter()
        yield
        self.elapsed[name] += time.perf_counter() - t


@contextlib.contextmanager
def make_bst_project():
    with tempfile.TemporaryDirectory() as dirname:
        yield BstProject(dirname)


def make_tar_import_text(url):
    return json.dumps({
        'kind': 'import',
        'sources': [
            {'kind': 'tar', 'url': url}
        ]
    })


def make_local_import_text(path):
    return json.dumps({
        'kind': 'import',
        'sources': [
            {'kind': 'local', 'path': path}
        ]
    })


def make_single_compose_text(depend_path):
    return json.dumps({
        'kind': 'compose',
        'depends': [
            {'filename': depend_path, 'type': 'build'}
        ]
    })


class BstProject():

    def __init__(self, working_dir):
        self.working_dir = working_dir
        self.write_file('project.conf', 'name: ' + random_name())

    def write_file(self, relative_path, contents):
        path = os.path.join(self.working_dir, relative_path)
        write_file(path, contents)

    def bst(self, *args):
        return run('bst', *args, working_dir=self.working_dir)


def random_name():
    return uuid.uuid4().hex


def write_random_files(root, dirname, num_files):
    for path in yield_random_paths(num_files):
        write_file(os.path.join(root, dirname, path), random_name())


def yield_random_paths(count):
    for i in range(count):
        name = uuid.uuid4().hex
        yield os.path.join(name[:2], name[2:4], name[4:])


def run(command, *args, working_dir=None):
    try:
        return subprocess.run(
            (command,) + args,
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            universal_newlines=True)
    except subprocess.CalledProcessError as e:
        print(e)
        print(e.stdout)
        print(e.stderr)
        raise


def tar_gz_directory(tgz_path, dir_path):
    with tarfile.open(tgz_path, "w:gz") as tar:
        tar.add(dir_path, arcname=os.path.basename(dir_path))


def write_file(path, contents):
    path = pathlib.Path(path)
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True)
    with open(path, "w") as f:
        f.write(contents)


def erase_buildstream_cache():
    cache_path = os.path.expanduser('~/.cache/buildstream')
    shutil.rmtree(cache_path)


if __name__ == '__main__':
    sys.exit(main())

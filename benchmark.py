#!/usr/bin/env python3
#
#  Copyright Bloomberg Finance LP
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
    # parser.add_argument(
    #     '--samples',
    #     type=int,
    #     default=3,
    #     help='How many times to repeat each measurement')
    # parser.add_argument(
    #     '--erase-buildstream-cache',
    #     action='store_true')
    args = parser.parse_args()

    # Compare start-up times of Python and BuildStream
    run_benchmark(100, benchmark_python)
    run_benchmark(10, benchmark_python_import_buildstream)
    run_benchmark(10, benchmark_help)

    thousands = range(1, 10 * 1000, 1000)

    # Compare operations involving many files, use writing random files as a
    # reference for comparison.
    run_benchmark_series(
        10,
        benchmark_write_files,
        series=thousands)
    run_benchmark_series(
        1,
        benchmark_import_files_tar,
        series=thousands)
    run_benchmark_series(
        1,
        benchmark_import_local_files,
        series=thousands)


def benchmark_python(timer):
    with timer.context():
        run('python3', '-c', 'print("hello")')


def benchmark_python_import_buildstream(timer):
    with timer.context():
        run('python3', '-c', 'import buildstream')


def benchmark_help(timer):
    with timer.context():
        run('bst', '--help')


def benchmark_write_files(timer, num_files):
    with make_bst_project() as p:
        with timer.context():
            write_random_files(p.working_dir, 'files', num_files)


def benchmark_import_files_tar(timer, num_files):
    with make_bst_project() as p:
        p.set_timer(timer)

        write_random_files(p.working_dir, 'files', num_files)
        tar_gz_directory(
            os.path.join(p.working_dir, 'files.tar.gz'),
            os.path.join(p.working_dir, 'files/'))
        shutil.rmtree(os.path.join(p.working_dir, 'files/'))

        tar_path = os.path.join(p.working_dir, 'files.tar.gz')
        p.write_file(
            'import.bst',
            make_tar_import_text('file://' + tar_path))
        p.write_file('compose.bst', make_single_compose_text('import.bst'))

        p.timed_bst('track', 'import.bst')
        p.timed_bst('show', 'compose.bst')
        p.timed_bst('build', 'import.bst')
        p.timed_bst('build', 'compose.bst')
        p.timed_bst('build', 'compose.bst', note='cached')
        p.timed_bst('checkout', 'compose.bst', 'files_checkout')


def benchmark_import_local_files(timer, num_files):
    with make_bst_project() as p:
        p.set_timer(timer)

        write_random_files(p.working_dir, 'files', num_files)
        p.write_file('import.bst', make_local_import_text('files/'))
        p.write_file('compose.bst', make_single_compose_text('import.bst'))

        p.timed_bst('show', 'compose.bst')
        p.timed_bst('build', 'import.bst')
        p.timed_bst('build', 'compose.bst')
        p.timed_bst('build', 'compose.bst', note='cached')
        p.timed_bst('checkout', 'compose.bst', 'files_checkout')


def run_benchmark(samples, benchmark_fn):
    timer = Timer()
    for i in range(samples):
        # if args.erase_buildstream_cache:
        #     erase_buildstream_cache()
        benchmark_fn(timer)

    for key in timer.ordered_names:
        name = benchmark_fn.__name__[len('benchmark_'):]
        if key is not None:
            name += ': ' + key
        print(
            name,
            '{:.2f}'.format(timer.elapsed[key] / samples),
            sep=',')


def run_benchmark_series(samples, benchmark_fn, series):
    for item in series:
        timer = Timer()

        for i in range(samples):
            # if args.erase_buildstream_cache:
            #     erase_buildstream_cache()
            benchmark_fn(timer, item)

        for key in timer.ordered_names:
            name = benchmark_fn.__name__[len('benchmark_'):]
            if key is not None:
                name += ':' + key
            print(
                name,
                item,
                '{:.2f}'.format(timer.elapsed[key] / samples),
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
        self.timer = None

    def write_file(self, relative_path, contents):
        path = os.path.join(self.working_dir, relative_path)
        write_file(path, contents)

    def bst(self, *args):
        return run('bst', *args, working_dir=self.working_dir)

    def set_timer(self, timer):
        self.timer = timer

    def timed_bst(self, *args, note=None, custom_timer=None):

        timer = custom_timer
        if timer is None:
            timer = self.timer
        if timer is None:
            raise Exception('Must supply a timer, or use set_timer()')

        context_name = ' '.join(args)
        if note is not None:
            context_name = '{} ({})'.format(context_name, note)

        with timer.context(context_name):
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

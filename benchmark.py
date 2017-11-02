"""Measure the performance of BuildStream CLI from the user's perspective."""
import argparse
import contextlib
import os
import pathlib
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--samples',
        type=int,
        default=3,
        help='How many times to repeat each measurement')
    args = parser.parse_args()

    run_benchmark(benchmark_python, args.samples)
    run_benchmark(benchmark_help, args.samples)
    # run_benchmark(benchmark_files, args.samples)


def run_benchmark(benchmark_fn, num_samples):
    timer = Timer()
    for i in range(num_samples):
        benchmark_fn(timer)
    print(timer.elapsed / num_samples)


def benchmark_python(timer):
    with timer.context():
        run('python3', '-c', 'print("hello")')


def benchmark_help(timer):
    with timer.context():
        run('bst', '--help')


def benchmark_files(timer):
    timer = Timer()

    for i in range(3):
        with make_fixture(FileImportFixture) as f:
            with timer.context():
                result = f.bst('build', f.files_bst)
                print(result.stdout)
                print(result.stderr)
            # f.bst('build', f.compose_bst)

    print(timer.elapsed)


class Timer:

    def __init__(self):
        self.elapsed = 0

    @contextlib.contextmanager
    def context(self):
        t = time.perf_counter()
        yield
        self.elapsed += time.perf_counter() - t


@contextlib.contextmanager
def make_fixture(klass):
    with tempfile.TemporaryDirectory() as dirname:
        yield klass(dirname)


IMPORT_TEMPLATE = """
kind: import

sources:
- kind: local
  path: {path}
""".strip()


COMPOSE_TEMPLATE = """
kind: compose

depends:
- filename: {depend}
  type: build
""".strip()


class FileImportFixture():

    def __init__(self, working_directory):
        self.working_directory = working_directory
        self.write_file('project.conf', 'name: benchmark')
        self.write_file('files/a', 'hello')

        self.files_bst = 'files.bst'
        self.write_file(
            self.files_bst,
            IMPORT_TEMPLATE.format(path='files'))

        compose_bst = 'compose.bst'
        self.write_file(
            compose_bst,
            COMPOSE_TEMPLATE.format(depend=self.files_bst))

    def write_file(self, relative_path, contents):
        path = os.path.join(self.working_directory, relative_path)
        write_file(path, contents)

    def bst(self, *args):
        return run('bst', *args, working_dir=working_directory)


def run(command, *args, working_dir=None):
    return subprocess.run(
        (command,) + args,
        cwd=working_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        universal_newlines=True)


def write_file(path, contents):
    path = pathlib.Path(path)
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True)
    with open(path, "w") as f:
        f.write(contents)


if __name__ == '__main__':
    sys.exit(main())

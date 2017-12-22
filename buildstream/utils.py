#!/usr/bin/env python3
#
#  Copyright (C) 2016 Codethink Limited
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
"""
Utilities
=========
"""

import calendar
import errno
import hashlib
import os
import pickle
import re
import shutil
import signal
import stat
import string
import subprocess
import tempfile
from contextlib import contextmanager

import pkg_resources
import psutil

from . import _signals
from . import _yaml
from ._exceptions import BstError


class UtilError(BstError):
    """Raised by utility functions when system calls fail.

    This will be handled internally by the BuildStream core,
    if you need to handle this error, then it should be reraised,
    or either of the :class:`.ElementError` or :class:`.SourceError`
    exceptions should be raised from this error.
    """
    pass


class ProgramNotFoundError(BstError):
    """Raised if a required program is not found.

    It is normally unneeded to handle this exception from plugin code.
    """
    pass


class FileListResult():
    """An object which stores the result of one of the operations
    which run on a list of files.
    """

    def __init__(self):

        self.overwritten = []
        """List of files which were overwritten in the target directory"""

        self.ignored = []
        """List of files which were ignored, because they would have
        replaced a non empty directory"""

        self.failed_attributes = []
        """List of files for which attributes could not be copied over"""

        self.files_written = []
        """List of files that were written."""


def list_relative_paths(directory):
    """A generator for walking directory relative paths

    This generator is useful for checking the full manifest of
    a directory.

    Note that directories will be yielded only if they are
    empty.

    Symbolic links will not be followed, but will be included
    in the manifest.

    Args:
       directory (str): The directory to list files in

    Yields:
       Relative filenames in `directory`
    """
    for (dirpath, dirnames, filenames) in os.walk(directory):

        relpath = os.path.relpath(dirpath, directory)

        # We don't want "./" pre-pended to all the entries in the root of
        # `directory`, prefer to have no prefix in that case.
        basepath = relpath if relpath != '.' and dirpath != directory else ''

        # os.walk does not decend into symlink directories, which
        # makes sense because otherwise we might have redundant
        # directories, or end up descending into directories outside
        # of the walk() directory.
        #
        # But symlinks to directories are still identified as
        # subdirectories in the walked `dirpath`, so we extract
        # these symlinks from `dirnames`
        #
        for d in dirnames:
            fullpath = os.path.join(dirpath, d)
            if os.path.islink(fullpath):
                yield os.path.join(basepath, d)

        # We've decended into an empty directory, in this case we
        # want to include the directory itself, but not in any other
        # case.
        if not filenames:
            yield relpath

        # List the filenames in the walked directory
        for f in filenames:
            yield os.path.join(basepath, f)


def glob(paths, pattern):
    """A generator to yield paths which match the glob pattern

    Args:
       paths (iterable): The paths to check
       pattern (str): A glob pattern

    This generator will iterate over the passed *paths* and
    yield only the filenames which matched the provided *pattern*.

    +--------+------------------------------------------------------------------+
    | Meta   | Description                                                      |
    +========+==================================================================+
    | \*     | Zero or more of any character, excepting path separators         |
    +--------+------------------------------------------------------------------+
    | \**    | Zero or more of any character, including path separators         |
    +--------+------------------------------------------------------------------+
    | ?      | One of any character, except for path separators                 |
    +--------+------------------------------------------------------------------+
    | [abc]  | One of any of the specified characters                           |
    +--------+------------------------------------------------------------------+
    | [a-z]  | One of the characters in the specified range                     |
    +--------+------------------------------------------------------------------+
    | [!abc] | Any single character, except the specified characters            |
    +--------+------------------------------------------------------------------+
    | [!a-z] | Any single character, except those in the specified range        |
    +--------+------------------------------------------------------------------+

    .. note::

       Escaping of the metacharacters is not possible

    """
    # Ensure leading slash, just because we want patterns
    # to match file lists regardless of whether the patterns
    # or file lists had a leading slash or not.
    if not pattern.startswith(os.sep):
        pattern = os.sep + pattern

    expression = _glob2re(pattern)
    regexer = re.compile(expression)

    for filename in paths:
        filename_try = filename
        if not filename_try.startswith(os.sep):
            filename_try = os.sep + filename_try

        if regexer.match(filename_try):
            yield filename


def sha256sum(filename):
    """Calculate the sha256sum of a file

    Args:
       filename (str): A path to a file on disk

    Returns:
       (str): An sha256 checksum string

    Raises:
       UtilError: In the case there was an issue opening
                  or reading `filename`
    """
    try:
        h = hashlib.sha256()
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
    except OSError as e:
        raise UtilError("Failed to get a checksum of file '{}': {}"
                        .format(filename, e)) from e

    return h.hexdigest()


def safe_copy(src, dest, *, result=None):
    """Copy a file while preserving attributes

    Args:
       src (str): The source filename
       dest (str): The destination filename
       result (:class:`~.FileListResult`): An optional collective result

    Raises:
       UtilError: In the case of unexpected system call failures

    This is almost the same as shutil.copy2(), except that
    we unlink *dest* before overwriting it if it exists, just
    incase *dest* is a hardlink to a different file.
    """
    # First unlink the target if it exists
    try:
        os.unlink(dest)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise UtilError("Failed to remove destination file '{}': {}"
                            .format(dest, e)) from e

    shutil.copyfile(src, dest)
    try:
        shutil.copystat(src, dest)
    except PermissionError:
        # If we failed to copy over some file stats, dont treat
        # it as an unrecoverable error, but provide some feedback
        # we can use for a warning.
        #
        # This has a tendency of happening when attempting to copy
        # over extended file attributes.
        if result:
            result.failed_attributes.append(dest)
        pass
    except shutil.Error as e:
        raise UtilError("Failed to copy '{} -> {}': {}"
                        .format(src, dest, e)) from e


def safe_link(src, dest, *, result=None):
    """Try to create a hardlink, but resort to copying in the case of cross device links.

    Args:
       src (str): The source filename
       dest (str): The destination filename
       result (:class:`~.FileListResult`): An optional collective result

    Raises:
       UtilError: In the case of unexpected system call failures
    """

    # First unlink the target if it exists
    try:
        os.unlink(dest)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise UtilError("Failed to remove destination file '{}': {}"
                            .format(dest, e)) from e

    # If we can't link it due to cross-device hardlink, copy
    try:
        os.link(src, dest)
    except OSError as e:
        if e.errno == errno.EXDEV:
            safe_copy(src, dest)
        else:
            raise UtilError("Failed to link '{} -> {}': {}"
                            .format(src, dest, e)) from e


def safe_remove(path):
    """Removes a file or directory

    This will remove a file if it exists, and will
    remove a directory if the directory is not empty.

    Args:
       path (str): The path to remove

    Returns:
       True if `path` was removed or did not exist, False
       if `path` was a non empty directory.

    Raises:
       UtilError: In the case of unexpected system call failures
    """
    if os.path.lexists(path):

        # Try to remove anything that is in the way, but issue
        # a warning instead if it removes a non empty directory
        try:
            os.unlink(path)
        except OSError as e:
            if e.errno != errno.EISDIR:
                raise UtilError("Failed to remove '{}': {}"
                                .format(path, e))

            try:
                os.rmdir(path)
            except OSError as e:
                if e.errno == errno.ENOTEMPTY:
                    return False
                else:
                    raise UtilError("Failed to remove '{}': {}"
                                    .format(path, e))

    return True


def copy_files(src, dest, *, files=None, ignore_missing=False, report_written=False):
    """Copy files from source to destination.

    Args:
       src (str): The source file or directory
       dest (str): The destination directory
       files (list): Optional list of files in `src` to copy
       ignore_missing (bool): Dont raise any error if a source file is missing
       report_written (bool): Add to the result object the full list of files written

    Returns:
       (:class:`~.FileListResult`): The result describing what happened during this file operation

    Raises:
       UtilError: In the case of unexpected system call failures

    .. note::

       Directories in `dest` are replaced with files from `src`,
       unless the existing directory in `dest` is not empty in which
       case the path will be reported in the return value.
    """
    if files is None:
        files = list_relative_paths(src)

    result = FileListResult()
    try:
        _process_list(src, dest, files, safe_copy, result, ignore_missing=ignore_missing,
                      report_written=report_written)
    except OSError as e:
        raise UtilError("Failed to copy '{} -> {}': {}"
                        .format(src, dest, e))
    return result


def link_files(src, dest, *, files=None, ignore_missing=False, report_written=False):
    """Hardlink files from source to destination.

    Args:
       src (str): The source file or directory
       dest (str): The destination directory
       files (list): Optional list of files in `src` to link
       ignore_missing (bool): Dont raise any error if a source file is missing
       report_written (bool): Add to the result object the full list of files written

    Returns:
       (:class:`~.FileListResult`): The result describing what happened during this file operation

    Raises:
       UtilError: In the case of unexpected system call failures

    .. note::

       Directories in `dest` are replaced with files from `src`,
       unless the existing directory in `dest` is not empty in which
       case the path will be reported in the return value.

    .. note::

       If a hardlink cannot be created due to crossing filesystems,
       then the file will be copied instead.
    """
    if files is None:
        files = list_relative_paths(src)

    result = FileListResult()
    try:
        _process_list(src, dest, files, safe_link, result, ignore_missing=ignore_missing,
                      report_written=report_written)
    except OSError as e:
        raise UtilError("Failed to link '{} -> {}': {}"
                        .format(src, dest, e))

    return result


def get_host_tool(name):
    """Get the full path of a host tool

    Args:
       name (str): The name of the program to search for

    Returns:
       The full path to the program, if found

    Raises:
       :class:`.ProgramNotFoundError`
    """
    search_path = os.environ.get('PATH')
    program_path = shutil.which(name, path=search_path)

    if not program_path:
        raise ProgramNotFoundError("Did not find '{}' in PATH: {}".format(name, search_path))

    return program_path


def url_directory_name(url):
    """Normalizes a url into a directory name

    Args:
       url (str): A url string

    Returns:
       A string which can be used as a directory name
    """
    valid_chars = string.digits + string.ascii_letters + '%_'

    def transl(x):
        return x if x in valid_chars else '_'

    return ''.join([transl(x) for x in url])


def get_bst_version():
    """Gets the major, minor release portion of the
    BuildStream version.

    Returns:
       (int): The major version
       (int): The minor version
    """
    package = pkg_resources.require("buildstream")[0]
    versions = package.version.split('.')[:2]

    return (int(versions[0]), int(versions[1]))


# Recursively remove directories, ignoring file permissions as much as
# possible.
def _force_rmtree(rootpath, **kwargs):
    for root, dirs, _ in os.walk(rootpath):
        for d in dirs:
            path = os.path.join(root, d.lstrip('/'))
            if os.path.exists(path) and not os.path.islink(path):
                try:
                    os.chmod(path, 0o755)
                except OSError as e:
                    raise UtilError("Failed to ensure write permission on file '{}': {}"
                                    .format(path, e))

    try:
        shutil.rmtree(rootpath, **kwargs)
    except shutil.Error as e:
        raise UtilError("Failed to remove cache directory '{}': {}"
                        .format(rootpath, e))


# Recursively make directories in target area
def _copy_directories(srcdir, destdir, target):
    this_dir = os.path.dirname(target)
    new_dir = os.path.join(destdir, this_dir)

    if not os.path.lexists(new_dir):
        if this_dir:
            yield from _copy_directories(srcdir, destdir, this_dir)

        old_dir = os.path.join(srcdir, this_dir)
        if os.path.lexists(old_dir):
            dir_stat = os.lstat(old_dir)
            mode = dir_stat.st_mode

            if stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                os.makedirs(new_dir)
                yield (new_dir, mode)
            else:
                raise UtilError('Source directory tree has file where '
                                'directory expected: {}'.format(old_dir))


def _ensure_real_directory(destpath):
    # We assume here that the artifacts we have staged only contain symlinks
    # with relative paths. If 'destpath' has a symlink in its path that points
    # /bin for example then 'realpath' would end up pointing somewhere inside
    # /bin which would cause us to try and write stuff over host OS filesystem.
    #
    # There is too much of a performance cost incurred if we check each symlink
    # here after resolving it, but integration-tests/symlinks-test should catch
    # any regressions on that front.
    realpath = os.path.realpath(destpath)

    # Ensure the real destination path exists before trying to get the mode
    # of the real destination path.
    #
    # It is acceptable that chunks create symlinks inside artifacts which
    # refer to non-existing directories, they will be created on demand here
    # at staging time.
    #
    if not os.path.exists(realpath):
        os.makedirs(realpath)

    return realpath


# _process_list()
#
# Internal helper for copying/moving/linking file lists
#
# This will handle directories, symlinks and special files
# internally, the `actionfunc` will only be called for regular files.
#
# Args:
#    srcdir: The source base directory
#    destdir: The destination base directory
#    filelist: List of relative file paths
#    actionfunc: The function to call for regular files
#    result: The FileListResult
#    ignore_missing: Dont raise any error if a source file is missing
#
#
def _process_list(srcdir, destdir, filelist, actionfunc, result, ignore_missing=False, report_written=False):

    # Keep track of directory permissions, since these need to be set
    # *after* files have been written.
    permissions = []

    # filelist comes in as a generator, and we need to use it more than once.
    filelist = list(filelist)

    # Add to the results the list of files written
    if report_written:
        result.files_written += filelist

    # Note we consume the filelist (which is a generator and not a list)
    # by sorting it, this is necessary to ensure that we processes symbolic
    # links which lead to directories before processing files inside those
    # directories.
    #
    # Be aware that this is a performance sensitive loop. The filelist could
    # easily have 100,000 files and the block below will run for each one.
    # Python's os.path() module is not particularly efficient so the less work
    # we do per-file the better.
    for path in sorted(filelist):
        srcpath = os.path.join(srcdir, path)
        destpath = os.path.join(destdir, path)

        try:
            file_stat = os.lstat(srcpath)
            mode = file_stat.st_mode

        except FileNotFoundError as e:
            # Skip this missing file
            if ignore_missing:
                continue
            else:
                raise UtilError("Source file is missing: {}".format(srcpath))

        # Collect overlaps
        if os.path.lexists(destpath) and not os.path.isdir(destpath):
            result.overwritten.append(path)

        # The destination directory may not have been created separately
        permissions.extend(_copy_directories(srcdir, destdir, path))

        if stat.S_ISDIR(mode):
            # Ensure directory exists in destination. Since we process the
            # filelist in directory-first order, we only need to do this when
            # we encounter a directory.
            #
            # Any symlinks /within/ 'destpath' will be resolved. This is an
            # unusual situation: bear in mind the filelist could be a combined
            # list of the contents of multiple artifacts, and also consider that
            # two artifacts could stage something in the same place. If one
            # puts a symlink at /bin and the other puts a directory at /bin,
            # the symlink could come first and the directory will not overwrite
            # it, so we may have pathnames from the second artifact such as
            # /bin/sh which end up having a symlink as part of their path. The
            # symlink in the path will be resolved when we try and actually
            # create the file, and we need to make sure that its target exists
            # first.
            _ensure_real_directory(destpath)

            dest_stat = os.lstat(os.path.realpath(destpath))
            if not stat.S_ISDIR(dest_stat.st_mode):
                raise UtilError('Destination not a directory. source has {}'
                                ' destination has {}'.format(srcpath, destpath))
            permissions.append((destpath, os.stat(srcpath).st_mode))

        elif stat.S_ISLNK(mode):
            if not safe_remove(destpath):
                result.ignored.append(path)
                continue

            target = os.readlink(srcpath)
            target = _relative_symlink_target(destdir, destpath, target)
            os.symlink(target, destpath)

        elif stat.S_ISREG(mode):
            # Process the file.
            if not safe_remove(destpath):
                result.ignored.append(path)
                continue

            actionfunc(srcpath, destpath, result=result)

        elif stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
            # Block or character device. Put contents of st_dev in a mknod.
            if not safe_remove(destpath):
                result.ignored.append(path)
                continue

            if os.path.lexists(destpath):
                os.remove(destpath)
            os.mknod(destpath, file_stat.st_mode, file_stat.st_rdev)
            os.chmod(destpath, file_stat.st_mode)

        else:
            # Unsupported type.
            raise UtilError('Cannot extract {} into staging-area. Unsupported type.'.format(srcpath))

    # Write directory permissions now that all files have been written
    for d, perms in permissions:
        os.chmod(d, perms)


# _relative_symlink_target()
#
# Fetches a relative path for symlink with an absolute target
#
# @root:    The staging area root location
# @symlink: Location of the symlink in staging area (including the root path)
# @target:  The symbolic link target, which may be an absolute path
#
# If @target is an absolute path, a relative path from the symbolic link
# location will be returned, otherwise if @target is a relative path, it will
# be returned unchanged.
#
# Using relative symlinks helps to keep the target self contained when staging
# files onto the target.
#
def _relative_symlink_target(root, symlink, target):

    if os.path.isabs(target):
        # First fix the input a little, the symlink itself must not have a
        # trailing slash, otherwise we fail to remove the symlink filename
        # from its directory components in os.path.split()
        #
        # The absolute target filename must have its leading separator
        # removed, otherwise os.path.join() will discard the prefix
        symlink = symlink.rstrip(os.path.sep)
        target = target.lstrip(os.path.sep)

        # We want a relative path from the directory in which symlink
        # is located, not from the symlink itself.
        symlinkdir, _ = os.path.split(os.path.realpath(symlink))

        # Create a full path to the target, including the leading staging
        # directory
        fulltarget = os.path.join(os.path.realpath(root), target)

        # now get the relative path from the directory where the symlink
        # is located within the staging root, to the target within the same
        # staging root
        newtarget = os.path.relpath(fulltarget, symlinkdir)

        return newtarget
    else:
        return target


# _generate_key()
#
# Generate an sha256 hex digest from the given value. The value
# can be a simple value or recursive dictionary with lists etc,
# anything simple enough to serialize.
#
# Args:
#    value: A value to get a key for
#
# Returns:
#    (str): An sha256 hex digest of the given value
#
def _generate_key(value):
    ordered = _yaml.node_sanitize(value)
    string = pickle.dumps(ordered)
    return hashlib.sha256(string).hexdigest()


# _set_deterministic_user()
#
# Set the uid/gid for every file in a directory tree to the process'
# euid/guid.
#
# Args:
#    directory (str): The directory to recursively set the uid/gid on
#
def _set_deterministic_user(directory):
    user = os.geteuid()
    group = os.getegid()

    for root, dirs, files in os.walk(directory.encode("utf-8"), topdown=False):
        for filename in files:
            os.chown(os.path.join(root, filename), user, group, follow_symlinks=False)

        for dirname in dirs:
            os.chown(os.path.join(root, dirname), user, group, follow_symlinks=False)


# _set_deterministic_mtime()
#
# Set the mtime for every file in a directory tree to the same.
#
# Args:
#    directory (str): The directory to recursively set the mtime on
#
def _set_deterministic_mtime(directory):
    # The magic number for timestamps: 2011-11-11 11:11:11
    magic_timestamp = calendar.timegm([2011, 11, 11, 11, 11, 11])

    for dirname, _, filenames in os.walk(directory.encode("utf-8"), topdown=False):
        for filename in filenames:
            pathname = os.path.join(dirname, filename)

            # Python's os.utime only ever modifies the timestamp
            # of the target, it is not acceptable to set the timestamp
            # of the target here, if we are staging the link target we
            # will also set its timestamp.
            #
            # We should however find a way to modify the actual link's
            # timestamp, this outdated python bug report claims that
            # it is impossible:
            #
            #   http://bugs.python.org/issue623782
            #
            # However, nowadays it is possible at least on gnuish systems
            # with with the lutimes glibc function.
            if not os.path.islink(pathname):
                os.utime(pathname, (magic_timestamp, magic_timestamp))

        os.utime(dirname, (magic_timestamp, magic_timestamp))


# _tempdir()
#
# A context manager for doing work in a temporary directory.
#
# Args:
#    dir (str): A path to a parent directory for the temporary directory
#    suffix (str): A suffix for the temproary directory name
#    prefix (str): A prefix for the temporary directory name
#
# Yields:
#    (str): The temporary directory
#
# In addition to the functionality provided by python's
# tempfile.TemporaryDirectory() context manager, this one additionally
# supports cleaning up the temp directory on SIGTERM.
#
@contextmanager
def _tempdir(suffix="", prefix="tmp", dir=None):
    tempdir = tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    def cleanup_tempdir():
        if os.path.isdir(tempdir):
            shutil.rmtree(tempdir)

    try:
        with _signals.terminator(cleanup_tempdir):
            yield tempdir
    finally:
        cleanup_tempdir()


# _kill_process_tree()
#
# Brutally murder a process and all of it's children
#
# Args:
#    pid (int): Process ID
#
def _kill_process_tree(pid):
    proc = psutil.Process(pid)
    children = proc.children(recursive=True)

    def kill_proc(p):
        try:
            p.kill()
        except psutil.AccessDenied:
            # Ignore this error, it can happen with
            # some setuid bwrap processes.
            pass

    # Bloody Murder
    for child in children:
        kill_proc(child)
    kill_proc(proc)


# _call()
#
# A wrapper for subprocess.call() supporting suspend and resum
#
# Args:
#    popenargs (list): Popen() arguments
#    terminate (bool): Whether to attempt graceful termination before killing
#    rest_of_args (kwargs): Remaining arguments to subprocess.call()
#
# Returns:
#    (int): The process exit code.
#    (str): The program output.
#
def _call(*popenargs, terminate=False, **kwargs):

    kwargs['start_new_session'] = True

    # Handle termination, suspend and resume
    def kill_proc():
        if process:

            # Some callers know that their subprocess can be
            # gracefully terminated, make an attempt first
            if terminate:
                proc = psutil.Process(process.pid)
                proc.terminate()

                exit_code = None
                try:
                    exit_code = proc.wait(20)
                except psutil.TimeoutExpired:
                    # Did not terminate within the timeout: murder
                    _kill_process_tree(process.pid)

            else:
                # FIXME: This is a brutal but reliable approach
                #
                # Other variations I've tried which try SIGTERM first
                # and then wait for child processes to exit gracefully
                # have not reliably cleaned up process trees and have
                # left orphaned git or ssh processes alive.
                #
                # This cleans up the subprocesses reliably but may
                # cause side effects such as possibly leaving stale
                # locks behind. Hopefully this should not be an issue
                # as long as any child processes only interact with
                # the temp directories which we control and cleanup
                # ourselves.
                #
                _kill_process_tree(process.pid)

    def suspend_proc():
        if process:
            group_id = os.getpgid(process.pid)
            os.killpg(group_id, signal.SIGSTOP)

    def resume_proc():
        if process:
            group_id = os.getpgid(process.pid)
            os.killpg(group_id, signal.SIGCONT)

    with _signals.suspendable(suspend_proc, resume_proc), _signals.terminator(kill_proc):
        process = subprocess.Popen(*popenargs, **kwargs)
        output, _ = process.communicate()
        exit_code = process.poll()

    # Program output is returned as bytes, we want utf8 strings
    if output is not None:
        output = output.decode('UTF-8')

    return (exit_code, output)


# _glob2re()
#
# Function to translate a glob style pattern into a regex
#
# Args:
#    pat (str): The glob pattern
#
# This is a modified version of the python standard library's
# fnmatch.translate() function which supports path like globbing
# a bit more correctly, and additionally supports recursive glob
# patterns with double asterisk.
#
# Note that this will only support the most basic of standard
# glob patterns, and additionally the recursive double asterisk.
#
# Support includes:
#
#   *          Match any pattern except a path separator
#   **         Match any pattern, including path separators
#   ?          Match any single character
#   [abc]      Match one of the specified characters
#   [A-Z]      Match one of the characters in the specified range
#   [!abc]     Match any single character, except the specified characters
#   [!A-Z]     Match any single character, except those in the specified range
#
def _glob2re(pat):
    i, n = 0, len(pat)
    res = ''
    while i < n:
        c = pat[i]
        i = i + 1
        if c == '*':
            # fnmatch.translate() simply uses the '.*' separator here,
            # we only want that for double asterisk (bash 'globstar' behavior)
            #
            if i < n and pat[i] == '*':
                res = res + '.*'
                i = i + 1
            else:
                res = res + '[^/]*'
        elif c == '?':
            # fnmatch.translate() simply uses the '.' wildcard here, but
            # we dont want to match path separators here
            res = res + '[^/]'
        elif c == '[':
            j = i
            if j < n and pat[j] == '!':
                j = j + 1
            if j < n and pat[j] == ']':
                j = j + 1
            while j < n and pat[j] != ']':
                j = j + 1
            if j >= n:
                res = res + '\\['
            else:
                stuff = pat[i:j].replace('\\', '\\\\')
                i = j + 1
                if stuff[0] == '!':
                    stuff = '^' + stuff[1:]
                elif stuff[0] == '^':
                    stuff = '\\' + stuff
                res = '{}[{}]'.format(res, stuff)
        else:
            res = res + re.escape(c)
    return res + '\Z(?ms)'

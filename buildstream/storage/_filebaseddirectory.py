#!/usr/bin/env python3
#
#  Copyright (C) 2018 Bloomberg Finance LP
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
#        Jim MacArthur <jim.macarthur@codethink.co.uk>

"""
FileBasedDirectory
=========

Implementation of the Directory class which backs onto a normal POSIX filing system.

See also: :ref:`sandboxing`.
"""

import os
import stat
import time

from .directory import Directory, VirtualDirectoryError, _FileType
from .. import utils
from ..utils import link_files, copy_files, list_relative_paths, _get_link_mtime, _magic_timestamp
from ..utils import _set_deterministic_user, _set_deterministic_mtime
from ..utils import _ensure_real_directory, _relative_symlink_target, safe_remove
from ..utils import FileListResult

# FileBasedDirectory intentionally doesn't call its superclass constuctor,
# which is meant to be unimplemented.
# pylint: disable=super-init-not-called


class FileBasedDirectory(Directory):
    def __init__(self, external_directory=None):
        self.external_directory = external_directory

    def descend(self, *paths, create=False):
        """ See superclass Directory for arguments """

        current_dir = self

        for path in paths:
            # Skip empty path segments
            if not path:
                continue

            new_path = os.path.join(current_dir.external_directory, path)
            try:
                st = os.lstat(new_path)
                if not stat.S_ISDIR(st.st_mode):
                    raise VirtualDirectoryError("Cannot descend into '{}': '{}' is not a directory"
                                                .format(path, new_path))
            except FileNotFoundError:
                if create:
                    os.mkdir(new_path)
                else:
                    raise VirtualDirectoryError("Cannot descend into '{}': '{}' does not exist"
                                                .format(path, new_path))

            current_dir = FileBasedDirectory(new_path)

        return current_dir

    def import_files(self, external_pathspec, *,
                     filter_callback=None,
                     report_written=True, update_mtime=False,
                     can_link=False):
        """ See superclass Directory for arguments """

        from ._casbaseddirectory import CasBasedDirectory

        if isinstance(external_pathspec, CasBasedDirectory):
            if can_link and not update_mtime:
                actionfunc = utils.safe_link
            else:
                actionfunc = utils.safe_copy

            import_result = FileListResult()
            self._import_files_from_cas(external_pathspec, actionfunc, filter_callback, result=import_result)
        else:
            if isinstance(external_pathspec, Directory):
                source_directory = external_pathspec.external_directory
            else:
                source_directory = external_pathspec

            if can_link and not update_mtime:
                import_result = link_files(source_directory, self.external_directory,
                                           filter_callback=filter_callback,
                                           ignore_missing=False, report_written=report_written)
            else:
                import_result = copy_files(source_directory, self.external_directory,
                                           filter_callback=filter_callback,
                                           ignore_missing=False, report_written=report_written)

        if update_mtime:
            cur_time = time.time()

            for f in import_result.files_written:
                os.utime(os.path.join(self.external_directory, f), times=(cur_time, cur_time))
        return import_result

    def set_deterministic_mtime(self):
        _set_deterministic_mtime(self.external_directory)

    def set_deterministic_user(self):
        _set_deterministic_user(self.external_directory)

    def export_files(self, to_directory, *, can_link=False, can_destroy=False):
        if can_destroy:
            # Try a simple rename of the sandbox root; if that
            # doesnt cut it, then do the regular link files code path
            try:
                os.rename(self.external_directory, to_directory)
                return
            except OSError:
                # Proceed using normal link/copy
                pass

        os.makedirs(to_directory, exist_ok=True)
        if can_link:
            link_files(self.external_directory, to_directory)
        else:
            copy_files(self.external_directory, to_directory)

    # Add a directory entry deterministically to a tar file
    #
    # This function takes extra steps to ensure the output is deterministic.
    # First, it sorts the results of os.listdir() to ensure the ordering of
    # the files in the archive is the same.  Second, it sets a fixed
    # timestamp for each entry. See also https://bugs.python.org/issue24465.
    def export_to_tar(self, tf, dir_arcname, mtime=0):
        # We need directories here, including non-empty ones,
        # so list_relative_paths is not used.
        for filename in sorted(os.listdir(self.external_directory)):
            source_name = os.path.join(self.external_directory, filename)
            arcname = os.path.join(dir_arcname, filename)
            tarinfo = tf.gettarinfo(source_name, arcname)
            tarinfo.mtime = mtime

            if tarinfo.isreg():
                with open(source_name, "rb") as f:
                    tf.addfile(tarinfo, f)
            elif tarinfo.isdir():
                tf.addfile(tarinfo)
                self.descend(*filename.split(os.path.sep)).export_to_tar(tf, arcname, mtime)
            else:
                tf.addfile(tarinfo)

    def is_empty(self):
        it = os.scandir(self.external_directory)
        return next(it, None) is None

    def mark_unmodified(self):
        """ Marks all files in this directory (recursively) as unmodified.
        """
        _set_deterministic_mtime(self.external_directory)

    def list_modified_paths(self):
        """Provide a list of relative paths which have been modified since the
        last call to mark_unmodified.

        Return value: List(str) - list of modified paths
        """
        return [f for f in list_relative_paths(self.external_directory)
                if _get_link_mtime(os.path.join(self.external_directory, f)) != _magic_timestamp]

    def list_relative_paths(self):
        """Provide a list of all relative paths.

        Return value: List(str) - list of all paths
        """

        return list_relative_paths(self.external_directory)

    def get_size(self):
        return utils._get_dir_size(self.external_directory)

    def __str__(self):
        # This returns the whole path (since we don't know where the directory started)
        # which exposes the sandbox directory; we will have to assume for the time being
        # that people will not abuse __str__.
        return self.external_directory

    def _get_underlying_directory(self) -> str:
        """ Returns the underlying (real) file system directory this
        object refers to. """
        return self.external_directory

    def _get_filetype(self, name=None):
        path = self.external_directory

        if name:
            path = os.path.join(path, name)

        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode):
            return _FileType.DIRECTORY
        elif stat.S_ISLNK(st.st_mode):
            return _FileType.SYMLINK
        elif stat.S_ISREG(st.st_mode):
            return _FileType.REGULAR_FILE
        else:
            return _FileType.SPECIAL_FILE

    def _import_files_from_cas(self, source_directory, actionfunc, filter_callback, *, path_prefix="", result):
        """ Import files from a CAS-based directory. """

        filelist = source_directory.list_relative_paths()

        if filter_callback:
            filelist = [path for path in filelist if filter_callback(path)]

        # Sorting the list of files is necessary to ensure that we processes
        # symbolic links which lead to directories before processing files inside
        # those directories.
        filelist = sorted(filelist)

        # Now walk the list
        for path in filelist:
            destpath = os.path.join(self.external_directory, path)

            # Add to the results the list of files written
            result.files_written.append(path)

            # Collect overlaps
            if os.path.lexists(destpath) and not os.path.isdir(destpath):
                result.overwritten.append(path)

            # Ensure that broken symlinks to directories have their targets
            # created before attempting to stage files across broken
            # symlink boundaries
            _ensure_real_directory(self.external_directory, os.path.dirname(destpath))

            entry = source_directory._lightweight_resolve_to_index(path)

            if entry.type == _FileType.DIRECTORY:
                # Ensure directory exists in destination
                if not os.path.exists(destpath):
                    _ensure_real_directory(self.external_directory, destpath)

                dest_stat = os.lstat(os.path.realpath(destpath))
                if not stat.S_ISDIR(dest_stat.st_mode):
                    raise UtilError('Destination not a directory. source has {}'
                                    ' destination has {}'.format(path, destpath))

            elif entry.type == _FileType.SYMLINK:
                if not safe_remove(destpath):
                    result.ignored.append(path)
                    continue

                target = entry.target
                target = _relative_symlink_target(self.external_directory, destpath, target)
                os.symlink(target, destpath)

            elif entry.type == _FileType.REGULAR_FILE:
                # Process the file.
                if not safe_remove(destpath):
                    result.ignored.append(path)
                    continue

                src_path = source_directory.cas_cache.objpath(entry.digest)
                actionfunc(src_path, destpath, result=result)

                if entry.is_executable:
                    os.chmod(destpath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
                             stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

            else:
                # Unsupported type.
                raise UtilError('Cannot extract {} into staging-area. Unsupported type.'.format(path))

#
#  Copyright (C) 2018 Codethink Limited
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
#        Jürg Billeter <juerg.billeter@codethink.co.uk>

from concurrent import futures
from enum import Enum
from typing import Set
import contextlib
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import errno
import random
import stat

import grpc
from google.protobuf.message import DecodeError
import click

from .._protos.build.bazel.remote.execution.v2 import (
    remote_execution_pb2,
    remote_execution_pb2_grpc,
)
from .._protos.google.bytestream import bytestream_pb2_grpc
from .._protos.build.buildgrid import local_cas_pb2, local_cas_pb2_grpc
from .._protos.buildstream.v2 import (
    buildstream_pb2,
    buildstream_pb2_grpc,
    artifact_pb2,
    artifact_pb2_grpc,
    source_pb2,
    source_pb2_grpc,
)
from ..utils import save_file_atomic, get_host_tool


# The default limit for gRPC messages is 4 MiB.
# Limit payload to 1 MiB to leave sufficient headroom for metadata.
_MAX_PAYLOAD_BYTES = 1024 * 1024


# CASRemote:
#
# A class that handles connections to a CAS remote - this is a (very)
# slimmed down version of BuildStream's CASRemote.
#
class CASRemote:
    def __init__(self, url: str):
        self._url = url

        self._local_cas = None
        self._bytestream = None
        self._cas = None

        # FIXME: We should allow setting up a secure channel. This
        # isn't currently required, since we will only proxy to a
        # process on the same host, but if we ever allow proxying to
        # external services this will need to change.
        self._channel = None

    def _initialize_remote(self):
        if self._channel:
            assert self._cas and self._bytestream, "Stubs seem to have disappeared"
            return
        assert not (self._cas or self._bytestream), "Our cas/bytestream stubs should not have been set"

        # Set up the remote channel
        self._channel = grpc.insecure_channel(self._url)

        # Assert that we support all capabilities we need
        capabilities = remote_execution_pb2_grpc.CapabilitiesStub(self._channel)
        start_wait = time.time()
        while True:
            try:
                capabilities.GetCapabilities(remote_execution_pb2.GetCapabilitiesRequest())
                break
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    # If connecting to casd, it may not be ready yet,
                    # try again after a 10ms delay, but don't wait for
                    # more than 15s
                    if time.time() < start_wait + 15:
                        time.sleep(1 / 100)
                        continue

                raise

        # Set up the RPC stubs
        self._local_cas = local_cas_pb2_grpc.LocalContentAddressableStorageStub(self._channel)
        self._bytestream = bytestream_pb2_grpc.ByteStreamStub(self._channel)
        self._cas = remote_execution_pb2_grpc.ContentAddressableStorageStub(self._channel)

    def get_cas(self) -> remote_execution_pb2_grpc.ContentAddressableStorageStub:
        self._initialize_remote()
        assert self._cas is not None, "CAS stub was not initialized"
        return self._cas

    def get_local_cas(self) -> local_cas_pb2_grpc.LocalContentAddressableStorageStub:
        self._initialize_remote()
        assert self._local_cas is not None, "Local CAS stub was not initialized"
        return self._local_cas

    def get_bytestream(self) -> bytestream_pb2_grpc.ByteStreamStub:
        self._initialize_remote()
        assert self._bytestream is not None, "Bytestream stub was not initialized"
        return self._bytestream


# CASCache:
#
# A slimmed down version of `buildstream._cas.cascache.CASCache` -
# exposes exactly the bits of interface we need to update objects on
# access.
#
# Note: This class *is* somewhat specialized and doesn't exactly do
# what `buildstream._cas.cascache.CASCache` does anymore.
#
# Ideally this should be supported by buildbox-casd in the future.
#
class CASCache:
    def __init__(self, root: str):
        self.root = root
        self.casdir = os.path.join(root, "cas")
        self.tmpdir = os.path.join(root, "tmp")

    # ref_path():
    #
    # Get the path to a digest's file.
    #
    # Args:
    #     ref - The ref of the digest.
    #
    # Returns:
    #     str - The path to the digest's file.
    #
    def ref_path(self, ref: str) -> str:
        return os.path.join(self.casdir, 'refs', 'heads', ref)

    # object_path():
    #
    # Get the path to an object's file.
    #
    # Args:
    #     digest - The digest of the object.
    #
    # Returns:
    #     str - The path to the object's file.
    #
    def object_path(self, digest) -> str:
        return os.path.join(self.casdir, 'objects', digest.hash[:2], digest.hash[2:])

    # remove_ref():
    #
    # Remove a digest file.
    #
    # Args:
    #     ref - The ref of the digest.
    #
    # Raises:
    #     FileNotFoundError - If the ref doesn't exist.
    def remove_ref(self, ref: str):
        basedir = os.path.join(self.casdir, 'refs', 'heads')

        os.unlink(self.ref_path(ref))

        # Now remove any leading directories
        components = list(os.path.split(ref))
        while components:
            components.pop()
            refdir = os.path.join(basedir, *components)

            # Break out once we reach the base
            if refdir == basedir:
                break

            try:
                os.rmdir(refdir)
            except FileNotFoundError:
                # The parent directory did not exist, but it's
                # parent directory might still be ready to prune
                pass
            except OSError as e:
                if e.errno == errno.ENOTEMPTY:
                    # The parent directory was not empty, so we
                    # cannot prune directories beyond this point
                    break
                raise

    # set_ref():
    #
    # Create or update a ref with a new digest.
    #
    # Args:
    #     ref - The ref of the digest.
    #     tree - The digest to write.
    #
    def set_ref(self, ref: str, tree):
        ref_path = self.ref_path(ref)

        os.makedirs(os.path.dirname(ref_path), exist_ok=True)
        with save_file_atomic(ref_path, 'wb', tempdir=self.tmpdir) as f:
            f.write(tree.SerializeToString())

    # resolve_ref():
    #
    # Read a digest given its ref.
    #
    # Args:
    #     ref - The ref of the digest.
    #
    # Returns:
    #     remote_execution-pb2.Digest - The digest.
    #
    # Raises:
    #     FileNotFoundError - If the ref doesn't exist.
    def resolve_ref(self, ref: str):
        digest = remote_execution_pb2.Digest()
        with open(self.ref_path(ref), 'rb') as f:
            digest.ParseFromString(f.read())
        return digest

    # resolve_digest():
    #
    # Read the directory corresponding to a digest.
    #
    # Args:
    #     digest - The digest corresponding to a directory.
    #
    # Returns:
    #     remote_execution_pb2.Directory - The directory.
    #
    # Raises:
    #     FileNotFoundError - If the digest object doesn't exist.
    def resolve_digest(self, digest):
        directory = remote_execution_pb2.Directory()
        with open(self.object_path(digest), 'rb') as f:
            directory.ParseFromString(f.read())
        return directory

    # update_tree_mtime():
    #
    # Update the mtimes of all files in a tree.
    #
    # Args:
    #     tree - The digest of the tree to update.
    #
    # Raises:
    #     FileNotFoundError - If any of the tree's objects don't exist.
    def update_tree_mtime(self, tree):
        visited = set()  # type: Set[str]
        os.utime(self.object_path(tree))

        def update_directory_node(node):
            try:
                if node.hash in visited:
                    return
            except AttributeError:
                raise Exception(type(node))

            os.utime(self.object_path(node))
            visited.add(node.hash)

            directory = self.resolve_digest(node)
            for filenode in directory.files:  # pylint: disable=no-member
                os.utime(self.object_path(filenode.digest))
            for dirnode in directory.directories:  # pylint: disable=no-member
                update_directory_node(dirnode.digest)

        # directory = self.resolve_digest(tree)
        # update_directory_node(directory)
        update_directory_node(tree)


# LogLevel():
#
# Represents the buildbox-casd log level.
#
class LogLevel(Enum):
    WARNING = "warning"
    INFO = "info"
    TRACE = "trace"

    @classmethod
    def get_logging_equivalent(cls, level: 'LogLevel') -> int:
        equivalents = {
            cls.WARNING: logging.WARNING,
            cls.INFO: logging.INFO,
            cls.TRACE: logging.DEBUG
        }

        # Yes, logging.WARNING/INFO/DEBUG are ints
        # I also don't know why
        return equivalents[level]


class ClickLogLevel(click.Choice):
    def __init__(self):
        super().__init__([m.lower() for m in LogLevel._member_names_])  # pylint: disable=no-member

    def convert(self, value, param, ctx):
        return LogLevel(super().convert(value, param, ctx))


# CASdRunner():
#
# Manage a buildbox-casd process.
#
# FIXME: Probably better to replace this with the work from !1638
#
class CASdRunner:
    def __init__(self, path: str, *, cache_quota: int = None, log_level: LogLevel = LogLevel.WARNING):
        self.root = path
        self.casdir = os.path.join(path, "cas")
        self.tmpdir = os.path.join(path, "tmp")

        self._casd_process = None
        self._casd_socket_path = None
        self._casd_socket_tempdir = None
        self._log_level = log_level
        self._quota = cache_quota

    # start_casd():
    #
    # Start the CASd process.
    #
    def start_casd(self):
        assert not self._casd_process, "CASd was already started"

        os.makedirs(os.path.join(self.casdir, "refs", "heads"), exist_ok=True)
        os.makedirs(os.path.join(self.casdir, "objects"), exist_ok=True)
        os.makedirs(self.tmpdir, exist_ok=True)

        # Place socket in global/user temporary directory to avoid hitting
        # the socket path length limit.
        self._casd_socket_path = self._make_socket_path(self.root)

        casd_args = [get_host_tool("buildbox-casd")]
        casd_args.append("--bind=unix:" + self._casd_socket_path)
        casd_args.append("--log-level=" + self._log_level.value)

        if self._quota is not None:
            casd_args.append("--quota-high={}".format(int(self._quota)))
            casd_args.append("--quota-low={}".format(int(self._quota / 2)))

        casd_args.append(self.root)

        blocked_signals = signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGINT])

        try:
            self._casd_process = subprocess.Popen(
                casd_args,
                cwd=self.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked_signals)

    # _make_socket_path()
    #
    # Create a path to the CASD socket, ensuring that we don't exceed
    # the socket path limit.
    #
    # Note that we *may* exceed the path limit if the python-chosen
    # tmpdir path is very long, though this should be /tmp.
    #
    # Args:
    #     path (str): The root directory for the CAS repository.
    #
    # Returns:
    #     (str) - The path to the CASD socket.
    #
    def _make_socket_path(self, path):
        self._casd_socket_tempdir = tempfile.mkdtemp(prefix='buildstream')
        # mkdtemp will create this directory in the "most secure"
        # way. This translates to "u+rwx,go-rwx".
        #
        # This is a good thing, generally, since it prevents us
        # from leaking sensitive information to other users, but
        # it's a problem for the workflow for userchroot, since
        # the setuid casd binary will not share a uid with the
        # user creating the tempdir.
        #
        # Instead, we chmod the directory 750, and only place a
        # symlink to the CAS directory in here, which will allow the
        # CASD process RWX access to a directory without leaking build
        # information.
        os.chmod(
            self._casd_socket_tempdir,
            stat.S_IRUSR |
            stat.S_IWUSR |
            stat.S_IXUSR |
            stat.S_IRGRP |
            stat.S_IXGRP,
        )

        os.symlink(path, os.path.join(self._casd_socket_tempdir, "cas"))
        # FIXME: There is a potential race condition here; if multiple
        # instances happen to create the same socket path, at least
        # one will try to talk to the same server as us.
        #
        # There's no real way to avoid this from our side; we'd need
        # buildbox-casd to tell us that it could not create a fresh
        # socket.
        #
        # We could probably make this even safer by including some
        # thread/process-specific information, but we're not really
        # supporting this use case anyway; it's mostly here fore
        # testing, and to help more gracefully handle the situation.
        #
        # Note: this uses the same random string generation principle
        # as cpython, so this is probably a safe file name.
        socket_name = "casserver-{}.sock".format(
            "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789_", k=8)))
        return os.path.join(self._casd_socket_tempdir, "cas", socket_name)

    # stop():
    #
    # Stop and tear down the CASd process.
    #
    def stop(self):
        return_code = self._casd_process.poll()

        if return_code is not None:
            self._casd_process = None
            logging.error(
                "Buildbox-casd died during the run. Exit code: %s", return_code
            )
            logging.error(self._casd_process.stdout.read().decode())
            return

        self._casd_process.terminate()

        try:
            return_code = self._casd_process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress():
                try:
                    return_code = self._casd_process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self._casd_process.kill()
                    self._casd_process.wait(timeout=15)
                    logging.warning(
                        "Buildbox-casd didn't exit in time and has been killed"
                    )
                    logging.error(self._casd_process.stdout.read().decode())
                    self._casd_process = None
                    return

        if return_code != 0:
            logging.error(
                "Buildbox-casd didn't exit cleanly. Exit code: %d", return_code
            )
            logging.error(self._casd_process.stdout.read().decode())

        self._casd_process = None

    # get_socket_path():
    #
    # Get the path to the socket of the CASd process - None if the
    # process has not been started yet.
    #
    def get_socket_path(self) -> str:
        assert self._casd_socket_path is not None, "CASd has not been started"
        return self._casd_socket_path

    # get_casdir():
    #
    # Get the path to the directory managed by CASd.
    #
    def get_casdir(self) -> str:
        return self.casdir


# create_server():
#
# Create gRPC CAS artifact server as specified in the Remote Execution API.
#
# Args:
#     repo (str): Path to CAS repository
#     enable_push (bool): Whether to allow blob uploads and artifact updates
#     index_only (bool): Whether to store CAS blobs or only artifacts
#
@contextlib.contextmanager
def create_server(repo, *, enable_push, quota, index_only, log_level=LogLevel.WARNING):
    logger = logging.getLogger('casserver')
    logger.setLevel(LogLevel.get_logging_equivalent(log_level))
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(LogLevel.get_logging_equivalent(log_level))
    logger.addHandler(handler)

    cas_runner = CASdRunner(os.path.abspath(repo), cache_quota=quota)
    cas_runner.start_casd()
    cas_cache = CASCache(os.path.abspath(repo))
    cas = CASRemote('unix:' + cas_runner.get_socket_path())

    try:
        root = os.path.abspath(repo)
        sourcedir = os.path.join(root, 'source_protos')

        # Use max_workers default from Python 3.5+
        max_workers = (os.cpu_count() or 1) * 5
        server = grpc.server(futures.ThreadPoolExecutor(max_workers))

        if not index_only:
            bytestream_pb2_grpc.add_ByteStreamServicer_to_server(
                _ByteStreamServicer(cas, enable_push=enable_push), server)

            remote_execution_pb2_grpc.add_ContentAddressableStorageServicer_to_server(
                _ContentAddressableStorageServicer(cas, enable_push=enable_push), server)

        remote_execution_pb2_grpc.add_CapabilitiesServicer_to_server(
            _CapabilitiesServicer(), server)

        buildstream_pb2_grpc.add_ReferenceStorageServicer_to_server(
            _ReferenceStorageServicer(cas, cas_cache, enable_push=enable_push), server)

        artifact_pb2_grpc.add_ArtifactServiceServicer_to_server(
            _ArtifactServicer(cas, root, cas_cache, update_cas=not index_only), server)

        source_pb2_grpc.add_SourceServiceServicer_to_server(
            _SourceServicer(sourcedir), server)

        # Create up reference storage and artifact capabilities
        artifact_capabilities = buildstream_pb2.ArtifactCapabilities(
            allow_updates=enable_push)
        source_capabilities = buildstream_pb2.SourceCapabilities(
            allow_updates=enable_push)
        buildstream_pb2_grpc.add_CapabilitiesServicer_to_server(
            _BuildStreamCapabilitiesServicer(artifact_capabilities, source_capabilities),
            server)

        yield server

    finally:
        cas_runner.stop()


@click.command(short_help="CAS Artifact Server")
@click.option('--port', '-p', type=click.INT, required=True, help="Port number")
@click.option('--server-key', help="Private server key for TLS (PEM-encoded)")
@click.option('--server-cert', help="Public server certificate for TLS (PEM-encoded)")
@click.option('--client-certs', help="Public client certificates for TLS (PEM-encoded)")
@click.option('--enable-push', is_flag=True,
              help="Allow clients to upload blobs and update artifact cache")
@click.option('--quota', type=click.INT, default=10e9, show_default=True,
              help="Maximum disk usage in bytes")
@click.option('--index-only', is_flag=True,
              help="Only provide the BuildStream artifact and source services (\"index\"), not the CAS (\"storage\")")
@click.option('--log-level', type=ClickLogLevel(),
              help="The log level to launch with")
@click.argument('repo')
def server_main(repo, port, server_key, server_cert, client_certs, enable_push,
                quota, index_only, log_level):
    # Handle SIGTERM by calling sys.exit(0), which will raise a SystemExit exception,
    # properly executing cleanup code in `finally` clauses and context managers.
    # This is required to terminate buildbox-casd on SIGTERM.
    signal.signal(signal.SIGTERM, lambda signalnum, frame: sys.exit(0))

    with create_server(repo,
                       quota=quota,
                       enable_push=enable_push,
                       index_only=index_only,
                       log_level=log_level) as server:

        use_tls = bool(server_key)

        if bool(server_cert) != use_tls:
            click.echo("ERROR: --server-key and --server-cert are both required for TLS", err=True)
            sys.exit(-1)

        if client_certs and not use_tls:
            click.echo("ERROR: --client-certs can only be used with --server-key", err=True)
            sys.exit(-1)

        if use_tls:
            # Read public/private key pair
            with open(server_key, 'rb') as f:
                server_key_bytes = f.read()
            with open(server_cert, 'rb') as f:
                server_cert_bytes = f.read()

            if client_certs:
                with open(client_certs, 'rb') as f:
                    client_certs_bytes = f.read()
            else:
                client_certs_bytes = None

            credentials = grpc.ssl_server_credentials([(server_key_bytes, server_cert_bytes)],
                                                      root_certificates=client_certs_bytes,
                                                      require_client_auth=bool(client_certs))
            server.add_secure_port('[::]:{}'.format(port), credentials)
        else:
            server.add_insecure_port('[::]:{}'.format(port))

        # Run artifact server
        server.start()
        try:
            while True:
                signal.pause()
        finally:
            server.stop(0)


class _ByteStreamServicer(bytestream_pb2_grpc.ByteStreamServicer):
    def __init__(self, remote, *, enable_push):
        super().__init__()
        self.bytestream = remote.get_bytestream()
        self.enable_push = enable_push
        self.logger = logging.getLogger("casserver")

    def Read(self, request, context):
        self.logger.info("Read")
        return self.bytestream.Read(request)

    def Write(self, request_iterator, context):
        self.logger.info("Write")
        return self.bytestream.Write(request_iterator)


class _ContentAddressableStorageServicer(remote_execution_pb2_grpc.ContentAddressableStorageServicer):
    def __init__(self, remote, *, enable_push):
        super().__init__()
        self.cas = remote.get_cas()
        self.enable_push = enable_push
        self.logger = logging.getLogger("casserver")

    def FindMissingBlobs(self, request, context):
        self.logger.info("FindMissingBlobs")
        self.logger.debug(request.blob_digests)
        return self.cas.FindMissingBlobs(request)

    def BatchReadBlobs(self, request, context):
        self.logger.info("BatchReadBlobs")
        return self.cas.BatchReadBlobs(request)

    def BatchUpdateBlobs(self, request, context):
        self.logger.info("BatchUpdateBlobs")
        self.logger.debug([request.digest for request in request.requests])
        return self.cas.BatchUpdateBlobs(request)


class _CapabilitiesServicer(remote_execution_pb2_grpc.CapabilitiesServicer):
    def __init__(self):
        self.logger = logging.getLogger("casserver")

    def GetCapabilities(self, request, context):
        self.logger.info("GetCapabilities")
        response = remote_execution_pb2.ServerCapabilities()

        cache_capabilities = response.cache_capabilities
        cache_capabilities.digest_function.append(remote_execution_pb2.SHA256)
        cache_capabilities.action_cache_update_capabilities.update_enabled = False
        cache_capabilities.max_batch_total_size_bytes = _MAX_PAYLOAD_BYTES
        cache_capabilities.symlink_absolute_path_strategy = remote_execution_pb2.CacheCapabilities.ALLOWED

        response.deprecated_api_version.major = 2
        response.low_api_version.major = 2
        response.high_api_version.major = 2

        return response


class _ReferenceStorageServicer(buildstream_pb2_grpc.ReferenceStorageServicer):
    def __init__(self, remote, cas_cache, *, enable_push):
        super().__init__()
        self.cas = remote.get_cas()
        self.cas_cache = cas_cache
        self.enable_push = enable_push
        self.logger = logging.getLogger("casserver")

    def GetReference(self, request, context):
        self.logger.debug("GetReference")
        response = buildstream_pb2.GetReferenceResponse()

        request = remote_execution_pb2.FindMissingBlobsRequest()
        d = request.blob_digests.add()
        d.CopyFrom(request.key)

        try:
            ref = self.cas.FindMissingBlobs(request)
        except grpc.RpcError as err:
            context.set_code(err.code())
            if err.code() == grpc.StatusCode.NOT_FOUND:
                self.cas_cache.remove_ref(request.key)
            return response

        response.digest.hash = ref.hash
        response.digest.size_bytes = ref.size_bytes

        return response

    def UpdateReference(self, request, context):
        self.logger.debug("UpdateReference")
        response = buildstream_pb2.UpdateReferenceResponse()

        if not self.enable_push:
            context.set_code(grpc.StatusCode.PERMISSION_DENIED)
            return response

        for key in request.keys:
            self.cas_cache.set_ref(key, request.digest)

        return response

    def Status(self, request, context):
        self.logger.debug("Status")
        response = buildstream_pb2.StatusResponse()

        response.allow_updates = self.enable_push

        return response


class _ArtifactServicer(artifact_pb2_grpc.ArtifactServiceServicer):

    def __init__(self, remote, root, cas_cache, *, update_cas=True):
        super().__init__()
        self.cas = remote.get_cas()
        self.local_cas = remote.get_local_cas()
        self.cas_cache = cas_cache
        self.artifactdir = os.path.join(root, 'artifacts', 'refs')
        self.update_cas = update_cas
        self.logger = logging.getLogger("casserver")

    def GetArtifact(self, request, context):
        self.logger.info("GetArtifact")
        self.logger.debug(request.cache_key)
        artifact_path = os.path.join(self.artifactdir, request.cache_key)
        if not os.path.exists(artifact_path):
            context.abort(grpc.StatusCode.NOT_FOUND, "Artifact proto not found")

        artifact = artifact_pb2.Artifact()
        with open(artifact_path, 'rb') as f:
            artifact.ParseFromString(f.read())

        os.utime(artifact_path)

        # Artifact-only servers will not have blobs on their system,
        # so we can't reasonably update their mtimes. Instead, we exit
        # early, and let the CAS server deal with its blobs.
        #
        # FIXME: We could try to run FindMissingBlobs on the other
        #        server. This is tricky to do from here, of course,
        #        because we don't know who the other server is, but
        #        the client could be smart about it - but this might
        #        make things slower.
        #
        #        It needs some more thought...
        if not self.update_cas:
            return artifact

        # Now update mtimes of files present.
        try:

            if str(artifact.files):
                request = local_cas_pb2.FetchTreeRequest()
                request.root_digest.CopyFrom(artifact.files)
                request.fetch_file_blobs = True
                self.local_cas.FetchTree(request)

            if str(artifact.buildtree):
                try:
                    request = local_cas_pb2.FetchTreeRequest()
                    request.root_digest.CopyFrom(artifact.buildtree)
                    request.fetch_file_blobs = True
                    self.local_cas.FetchTree(request)
                except grpc.RpcError as err:
                    # buildtrees might not be there
                    if err.code() != grpc.StatusCode.NOT_FOUND:
                        raise

            if str(artifact.public_data):
                request = remote_execution_pb2.FindMissingBlobsRequest()
                d = request.blob_digests.add()
                d.CopyFrom(artifact.public_data)
                self.cas.FindMissingBlobs(request)

            request = remote_execution_pb2.FindMissingBlobsRequest()
            for log_file in artifact.logs:
                d = request.blob_digests.add()
                d.CopyFrom(log_file.digest)
            self.cas.FindMissingBlobs(request)

        except grpc.RpcError as err:
            if err.code() == grpc.StatusCode.NOT_FOUND:
                os.unlink(artifact_path)
                context.abort(grpc.StatusCode.NOT_FOUND,
                              "Artifact files incomplete")
            else:
                context.abort(grpc.StatusCode.NOT_FOUND,
                              "Artifact files not valid")

        return artifact

    def UpdateArtifact(self, request, context):
        self.logger.info("UpdateArtifact")
        self.logger.debug(request.cache_key)
        artifact = request.artifact

        if self.update_cas:
            # Check that the files specified are in the CAS
            if str(artifact.files):
                self._check_directory("files", artifact.files, context)

            # Unset protocol buffers don't evaluated to False but do return empty
            # strings, hence str()
            if str(artifact.public_data):
                self._check_file("public data", artifact.public_data, context)

            for log_file in artifact.logs:
                self._check_file("log digest", log_file.digest, context)

        # Add the artifact proto to the cas
        artifact_path = os.path.join(self.artifactdir, request.cache_key)
        os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
        with save_file_atomic(artifact_path, mode='wb') as f:
            f.write(artifact.SerializeToString())

        return artifact

    def ArtifactStatus(self, request, context):
        self.logger.info("ArtifactStatus")
        return artifact_pb2.ArtifactStatusResponse()

    def _check_directory(self, name, digest, context):
        try:
            self.cas_cache.resolve_digest(digest)
        except FileNotFoundError:
            self.logger.warning(
                "Artifact %s specified but no files found (%s)",
                name,
                self.cas_cache.object_path(digest))
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Artifact {} specified but no files found".format(name))
        except DecodeError:
            self.logger.warning(
                "Artifact %s specified but directory not found (%s)",
                name,
                self.cas_cache.object_path(digest))
            context.abort(grpc.StatusCode.FAILED_PRECONDITION,
                          "Artifact {} specified but directory not found".format(name))

    def _check_file(self, name, digest, context):
        if not os.path.exists(self.cas_cache.object_path(digest)):
            context.abort(grpc.StatusCode.FAILED_PRECONDITION,
                          "Artifact {} specified but not found".format(name))


class _BuildStreamCapabilitiesServicer(buildstream_pb2_grpc.CapabilitiesServicer):
    def __init__(self, artifact_capabilities, source_capabilities):
        self.artifact_capabilities = artifact_capabilities
        self.source_capabilities = source_capabilities

    def GetCapabilities(self, request, context):
        response = buildstream_pb2.ServerCapabilities()
        response.artifact_capabilities.CopyFrom(self.artifact_capabilities)
        response.source_capabilities.CopyFrom(self.source_capabilities)
        return response


class _SourceServicer(source_pb2_grpc.SourceServiceServicer):
    def __init__(self, sourcedir):
        self.sourcedir = sourcedir
        self.logger = logging.getLogger("casserver")

    def GetSource(self, request, context):
        try:
            source_proto = self._get_source(request.cache_key)
        except FileNotFoundError:
            context.abort(grpc.StatusCode.NOT_FOUND, "Source not found")
        except DecodeError:
            context.abort(grpc.StatusCode.NOT_FOUND,
                          "Sources gives invalid directory")

        return source_proto

    def UpdateSource(self, request, context):
        self._set_source(request.cache_key, request.source)
        return request.source

    def _get_source(self, cache_key):
        path = os.path.join(self.sourcedir, cache_key)
        source_proto = source_pb2.Source()
        with open(path, 'r+b') as f:
            source_proto.ParseFromString(f.read())
            os.utime(path)
            return source_proto

    def _set_source(self, cache_key, source_proto):
        path = os.path.join(self.sourcedir, cache_key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with save_file_atomic(path, 'w+b') as f:
            f.write(source_proto.SerializeToString())


def _digest_from_download_resource_name(resource_name):
    parts = resource_name.split('/')

    # Accept requests from non-conforming BuildStream 1.1.x clients
    if len(parts) == 2:
        parts.insert(0, 'blobs')

    if len(parts) != 3 or parts[0] != 'blobs':
        return None

    try:
        digest = remote_execution_pb2.Digest()
        digest.hash = parts[1]
        digest.size_bytes = int(parts[2])
        return digest
    except ValueError:
        return None


def _digest_from_upload_resource_name(resource_name):
    parts = resource_name.split('/')

    # Accept requests from non-conforming BuildStream 1.1.x clients
    if len(parts) == 2:
        parts.insert(0, 'uploads')
        parts.insert(1, str(uuid.uuid4()))
        parts.insert(2, 'blobs')

    if len(parts) < 5 or parts[0] != 'uploads' or parts[2] != 'blobs':
        return None

    try:
        uuid_ = uuid.UUID(hex=parts[1])
        if uuid_.version != 4:
            return None

        digest = remote_execution_pb2.Digest()
        digest.hash = parts[3]
        digest.size_bytes = int(parts[4])
        return digest
    except ValueError:
        return None

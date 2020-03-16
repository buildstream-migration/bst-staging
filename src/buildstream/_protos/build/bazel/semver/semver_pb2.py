# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: build/bazel/semver/semver.proto

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor.FileDescriptor(
  name='build/bazel/semver/semver.proto',
  package='build.bazel.semver',
  syntax='proto3',
  serialized_options=None,
  serialized_pb=b'\n\x1f\x62uild/bazel/semver/semver.proto\x12\x12\x62uild.bazel.semver\"I\n\x06SemVer\x12\r\n\x05major\x18\x01 \x01(\x05\x12\r\n\x05minor\x18\x02 \x01(\x05\x12\r\n\x05patch\x18\x03 \x01(\x05\x12\x12\n\nprerelease\x18\x04 \x01(\tb\x06proto3'
)




_SEMVER = _descriptor.Descriptor(
  name='SemVer',
  full_name='build.bazel.semver.SemVer',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  fields=[
    _descriptor.FieldDescriptor(
      name='major', full_name='build.bazel.semver.SemVer.major', index=0,
      number=1, type=5, cpp_type=1, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR),
    _descriptor.FieldDescriptor(
      name='minor', full_name='build.bazel.semver.SemVer.minor', index=1,
      number=2, type=5, cpp_type=1, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR),
    _descriptor.FieldDescriptor(
      name='patch', full_name='build.bazel.semver.SemVer.patch', index=2,
      number=3, type=5, cpp_type=1, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR),
    _descriptor.FieldDescriptor(
      name='prerelease', full_name='build.bazel.semver.SemVer.prerelease', index=3,
      number=4, type=9, cpp_type=9, label=1,
      has_default_value=False, default_value=b"".decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto3',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=55,
  serialized_end=128,
)

DESCRIPTOR.message_types_by_name['SemVer'] = _SEMVER
_sym_db.RegisterFileDescriptor(DESCRIPTOR)

SemVer = _reflection.GeneratedProtocolMessageType('SemVer', (_message.Message,), {
  'DESCRIPTOR' : _SEMVER,
  '__module__' : 'build.bazel.semver.semver_pb2'
  # @@protoc_insertion_point(class_scope:build.bazel.semver.SemVer)
  })
_sym_db.RegisterMessage(SemVer)


# @@protoc_insertion_point(module_scope)

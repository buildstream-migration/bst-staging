kind: manual

depends:
  - filename: base.bst
    type: build

config:
  build-commands:
    - "[ `id -u` = 1024 -a `id -g` = 1048 ]"
  build-uid: 1024
  build-gid: 1048

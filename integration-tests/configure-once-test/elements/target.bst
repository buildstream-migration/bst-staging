kind: manual
description: Dump files whenever build and configure is executed

sources:
- kind: local
  path: target-src

depends:
  - filename: dependencies/base-platform.bst
    type: build


config:
  configure-commands:
  - "date > /buildstream/install/configure_timestamp"
 
  build-commands:
  - "date > /buildstream/install/build_timestamp"

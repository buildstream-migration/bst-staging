kind: manual
description: |
  Test that BuildStream correctly deals with artifacts that contain symlinks.

depends:
  - filename: dependencies/base-platform.bst
    type: build
  - filename: symlinks-test-base.bst

config:
  install-commands:
    # The symlinks-test-base.bst element that we depend on installs a symlink
    # pointing to a non-existent directory at `./opt/orgname`.

    # When we are staged, this directory will be ignored as the symlink will
    # already be in place from symlinks-test-base.bst.
    - mkdir -p "%{install-root}"/opt/orgname/etc/

    # This file has the symlink in its path so when we are staged, it should
    # end up at the symlink's target (`/usr/orgs/orgname`). This requires
    # BuildStream to correctly resolve the link and create its target.
    - echo "example" > "%{install-root}"/opt/orgname/etc/org.conf

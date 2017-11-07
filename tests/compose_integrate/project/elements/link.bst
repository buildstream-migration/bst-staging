kind: fake-integration

depends:
  - filename: import-1.bst

public:
  bst:
    integration-commands:
      - "delete:sub/subfile-A-1"
      - "delete:sub/subfile-B-1"
      - "delete:sub/subfile-A-2"
      - "delete:sub/subfile-B-2"
      - "rmdir:sub"
      - "mkdir:sub2"
      - "add:sub2/subfile-A-1"
      - "add:sub2/subfile-B-1"
      - "add:sub2/subfile-A-2"
      - "add:sub2/subfile-B-2"
      - "link:sub:sub2"


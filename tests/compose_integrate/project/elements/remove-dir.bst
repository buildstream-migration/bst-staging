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

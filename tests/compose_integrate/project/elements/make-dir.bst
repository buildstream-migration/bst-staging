kind: fake-integration

depends:
  - filename: import-1.bst

public:
  bst:
    integration-commands:
      - "mkdir:sub2"
      - "add:sub2/subfile2"

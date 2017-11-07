kind: fake-integration

depends:
  - filename: import-1.bst

public:
  bst:
    integration-commands:
      - "delete:file-A-1"

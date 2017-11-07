kind: fake-integration

depends:
  - filename: import-1.bst

public:
  bst:
    integration-commands:
      - "touch:file-A-1"

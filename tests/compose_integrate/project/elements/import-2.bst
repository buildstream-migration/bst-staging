kind: import
public:
  bst:
    split-rules:
      A:
        - "/file-A-2"
        - "/sub/subfile-A-2"

      B:
        - "/file-B-2"
        - "/sub/subfile-B-2"

sources:
- kind: local
  path: files/2

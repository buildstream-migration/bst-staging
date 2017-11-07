kind: import
public:
  bst:
    split-rules:
      A:
        - "/file-A-1"
        - "/sub/subfile-A-1"

      B:
        - "/file-B-1"
        - "/sub/subfile-B-1"

sources:
- kind: local
  path: files/1

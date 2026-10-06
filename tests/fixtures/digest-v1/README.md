# Digest fixture, contract v1

`tree/` is a plain file tree (not a full package) for checking the exact v1 snapshot digest
(Package Contract §3). Its expected value is in `expected-digest.txt`.

It covers byte-order sorting (`B.txt` < `Zeta/` < `a.txt` < `café/`), an empty file, a space in a
name, NFC non-ASCII names and CRLF bytes inside a file.

The same value can be reproduced with shell tools:

    cd tree
    find . -type f -printf '%P\0' | LC_ALL=C sort -z |
      while IFS= read -r -d '' f; do printf '%s  %s\n' "$(sha256sum < "$f" | cut -c1-64)" "$f"; done |
      sha256sum

This shell pipeline is only a cross-check; the contract text defines the digest.

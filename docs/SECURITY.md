# Security and private data

This application is intended for one user on their own computer. Keep its server
bound to loopback. Do not expose it through a public tunnel or port forwarding.

Investigations and captured pages live in `data/`. API keys, databases, source
captures, logs, model weights, and local setup scripts must not enter the public
repository. Use fictional examples when reporting bugs. Website content is
untrusted input, including when passed to a local model.

Do not put secrets or exploitable vulnerability details into a public issue.
Use the repository's private vulnerability reporting channel once the maintainer
has enabled it. A reporting contact has not yet been configured for this draft.

The public package is a source beta. Windows clean-machine testing, current
dependency auditing, and private vulnerability reporting setup remain release
checks. Passing automated tests is not a security certification.

# ADR-0007: Target Python 3.10+ with 3.12 recommended

- **Status:** Accepted
- **Context**

The specification names Python 3.12+. In practice, many developer machines and CI
base images still ship 3.10/3.11, and the project must be *runnable and testable*
in those environments to satisfy "a new developer can clone and run it".

- **Decision**

Declare `requires-python = ">=3.10"` and write code that runs on 3.10+ (using
`from __future__ import annotations`, avoiding PEP 695 generics and the `type`
statement). Recommend and target **3.12** for production; the Docker image is built
on `python:3.12-slim` and CI runs on 3.12.

- **Consequences**

  - **Positive:** the repo clones and passes its full suite on 3.10, 3.11, and 3.12
    with no changes — maximizing "runs on a new machine".
  - **Positive:** production still gets 3.12 (image + CI), so the recommended runtime
    matches the spec.
  - **Negative:** we forgo 3.12-only syntax sugar (PEP 695). Minor; readability is
    preserved with standard typing.

- **Alternatives considered**

  - *Hard-require 3.12* — rejected: would block clone-and-run on common 3.10/3.11
    environments for no functional benefit, since the code needs no 3.12-only
    features.

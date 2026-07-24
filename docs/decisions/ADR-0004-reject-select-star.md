# ADR-0004: Reject bare `SELECT *` instead of expanding it

- **Status:** Accepted
- **Context**

The policy engine authorizes queries per **column** (classification → role). A bare
`SELECT *` hides which columns are actually returned, so the engine cannot prove a
sensitive column isn't exposed. Two options: (a) expand `*` to concrete columns
using the schema, or (b) reject `*` and require explicit columns.

- **Decision**

Reject bare `SELECT *` (a `Star` projection with no function ancestor) at the
validator. `COUNT(*)` and other star-in-function forms are allowed.

- **Consequences**

  - **Positive:** the policy engine always sees concrete columns; there is no path
    where an unexpanded `*` silently returns a sensitive column. Simpler and
    safer than star-expansion across joins/derived tables.
  - **Positive:** encourages explicit, auditable queries; the prompt and fake
    provider already prefer explicit columns, and the repair loop can fix a stray
    star.
  - **Negative:** a user pasting `SELECT * FROM t` into `/validate` gets a
    rejection rather than a rewrite. Documented in [limitations](../limitations.md).

- **Alternatives considered**

  - *Expand `*` using the schema* — rejected for v1: correct expansion across joins,
    aliases, and derived tables is error-prone; a wrong expansion could *under*-list
    columns and defeat the policy check. Safety favours rejection.

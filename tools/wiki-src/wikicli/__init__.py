"""wikicli — project-local agent-maintained Markdown wiki CLI.

The CLI is the integrity boundary for the wiki. All canonical mutation flows
through it. Markdown is canonical; indexes, manifests and embeddings are
disposable derived state.

See the project plan (plan-v3-final.md) for the authoritative design.
"""

__version__ = "0.1.2"

# Contract version. Skills declare the contract version they support so
# mismatches can be detected. Bumped when the on-disk data model or CLI
# invocation contract changes in a backward-incompatible way.
CONTRACT_VERSION = "1.0.0"

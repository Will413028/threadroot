# Contributing to Threadroot

## Development

Threadroot supports Python 3.11 and newer on macOS and Linux. Runtime code is standard-library-only unless a dependency has an explicit, reviewed justification. Work in an isolated checkout, make focused changes, and use test-first development for observable behavior.

## Tests

Run the complete local gate described in [Testing](docs/testing.md). Add or update a focused `unittest` before changing behavior, observe the expected failure, then make the smallest implementation change that passes it.

Fixtures, examples, logs, and artifacts must be synthetic. Before proposing a change, run the source and artifact public-safety scans; an optional private denylist must remain outside Git.

## Pull requests

Keep each pull request narrow and explain its behavior, trade-offs, and verification evidence. Preserve unrelated worktree changes and stage exact paths. Do not add generated vaults, build output, host configuration, transcripts, or machine-local context.

## Public/private boundary

Never copy a user's vault, notes, paths, identities, company material, credentials, or other private context into this repository. Reproduce problems with synthetic data. If a report needs sensitive evidence, follow [Security](SECURITY.md) rather than posting it publicly.

## License

Submitted contributions are distributed under [Apache-2.0](LICENSE). This contribution license does not cover a contributor's or user's vault content, nor does it grant rights to project trademarks.

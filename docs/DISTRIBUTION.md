# Distribution

lazy-hsa releases are currently distributed as reviewed source through GitHub
Releases. PyPI installation and prebuilt application binaries are not supported.

## Install from source

Use a tagged release and the lockfile committed with it:

```bash
git clone https://github.com/minghsuy/lazy-hsa.git
cd lazy-hsa
git checkout vX.Y.Z
uv sync --frozen
uv run lazy-hsa --help
```

Each release candidate is prepared and tested as a wheel and source
distribution in a clean environment. Those local artifacts and their
`SHA256SUMS` manifest are verification inputs, not a promise that a package has
been published to PyPI. `scripts/release.sh prepare X.Y.Z` creates the version
commit, clean-installs and smoke-tests the retained wheel, and records the
artifacts locally, but deliberately does not push, tag, or publish.

## Release invariants

- The project version and the root package version in `uv.lock` match.
- The public release comes from an exact reviewed commit.
- The built wheel declares each required runtime dependency exactly once.
- A clean environment can install the wheel, start the CLI, import
  `pillow_heif`, and exercise the HEIC conversion path.
- The release tag is created from the exact reviewed merge commit and is never
  moved.

Remote publication is an explicit operator step after the preparation branch is
independently reviewed and merged. The public repository's release helper does
not mutate remote release state.

The installed-wheel check intentionally runs in the default test suite. This
adds a clean build/install step to ordinary CI, but ensures the supported
distribution contract cannot silently become an optional release-time check.
The current CI cost is small relative to the packaging failure it prevents.

PyPI can become a supported channel only through a separate reviewed change
that configures a trusted publisher, uploads the exact verified artifacts, and
performs a post-publication clean install.

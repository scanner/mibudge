# Releasing mibudge

A mibudge release is a signed git tag and the Docker images built from it.
Deployments name the release they run, so moving between releases is a
change of one version string.

## Versions

- The version lives in `pyproject.toml` (`[project] version`) and follows
  [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
- A release's git tag is the bare version (`0.3.0`, no `v` prefix): an
  annotated tag, signed by the person making the release.
- `CHANGELOG.md` has one section per release, dated with the day the
  release's code was finished, and an `[Unreleased]` section collecting
  changes for the next one.
- `make version` prints the version in `pyproject.toml`.

## Images

Pushing a tag runs the Drone pipelines: the full test pipeline, then the
image build. The build publishes to `ghcr.io/scanner/mibudge`:

| Tag                    | Image                                       |
|------------------------|---------------------------------------------|
| `X.Y.Z`, `X.Y`         | production image (`prod` Dockerfile target) |
| `X.Y.Z-dev`, `X.Y-dev` | development image (`dev` target)            |

Every image carries its version in the `org.opencontainers.image.version`
label (`docker inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}'`).
There is no `latest` tag: a deployment always names a version, as the
production template's `VERSION` does (`deployment/production/`).

`make build` builds the same two images locally, tagged `mibudge:X.Y.Z` and
`mibudge:latest`, and `mibudge:X.Y.Z-dev` and `mibudge:dev`.

## Making a release

1. In a pull request against `main`:
   - Rename `## [Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD`
     and start a new, empty `## [Unreleased]` above it. Point the
     `[Unreleased]` link at `X.Y.Z...HEAD` and add an `[X.Y.Z]` compare link
     from the previous release.
   - Set `version = "X.Y.Z"` in `pyproject.toml` and run `uv lock`, which
     updates the project's own entry in `uv.lock`.
   - Say in the CHANGELOG when a release has migrations, so a deployer knows
     whether going back to the previous release needs a database restore.
2. Merge it, update a local `main`, and run `make publish-tag`. It signs the
   tag `X.Y.Z` on `HEAD` (skipping that step when the tag already exists) and
   pushes only that tag.
3. Watch the tag's Drone build. When it is green, the images above are
   published.

## Releasing an earlier commit

A release can be cut from a commit that `main` has moved past:

1. Branch `release-X.Y.Z` from that commit.
2. Make one release commit on it: the version, the CHANGELOG section, and any
   build-file changes the tag build needs. Drone builds a tag with the
   `.drone.yml` and `Dockerfile` of the tagged commit, so the build files on
   the branch are the ones that build the images. Check that the commit
   leaves the application unchanged:
   `git diff <commit> -- app frontend importers` is empty.
3. Push the branch, wait for its test pipeline to pass, then run
   `make publish-tag` on the release commit.
4. Merge the branch back into `main` with a merge commit, never a squash, so
   the tag is reachable from `main` (`git describe` reports it). The merge
   keeps `main`'s code and its `[Unreleased]` changes above the new
   release's section.

## Rolling back

Deploy the previous version. A release with no migrations rolls back by
changing the version alone; one with migrations needs the database restored
from a backup taken before the upgrade (see `deployment/production/README.md`).

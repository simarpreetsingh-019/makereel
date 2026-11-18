# Publishing an update

Everyone running makereel sees a banner ("makereel 0.7.0 is available") once a new GitHub release is
out, and can install it from **System → Updates** with one click. The app restarts itself afterwards,
but only when no reel is being made or recorded.

## One-time setup

1. Put the project on GitHub (public, so the app can read releases without an account).
2. The app always checks `simarpreetsingh-019/makereel`; it isn't a setting, so nobody can redirect updates.

## Each release

1. Bump the version in `src/makereel/__init__.py` and `pyproject.toml` (e.g. `0.7.0`).
2. Move the `Unreleased` notes in `CHANGELOG.md` under the new version.
3. Commit, tag and publish:

   ```bash
   git commit -am "Release 0.7.0"
   git tag v0.7.0
   git push origin main --tags
   gh release create v0.7.0 --title "makereel 0.7.0" --notes-file notes.md
   ```

   The **release** workflow then builds the package and attaches `makereel-0.7.0-py3-none-any.whl` and its
   `.sha256` to the release. In-app updates install only that file, and only if the checksum matches.

The tag must start with `v` and match the version. The release notes are what users see under
"What's new".

## How installs update

- **Installed from a git clone** (`pip install -e .`): the app fetches the tag, checks it out and
  reinstalls. It refuses if someone edited the code locally, so their changes are never overwritten.
- **Installed with the installer or pip**: the app downloads the wheel attached to the release, checks it
  against the published SHA-256, and only then installs it.

Each app checks at most every 6 hours, with one request to GitHub's public API. Nothing about the
user or their computer is sent. Turn it off with **Check for updates when makereel starts**.

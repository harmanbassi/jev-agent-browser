# Release checklist

Publication requires an explicit maintainer decision. Preparing or testing a
release does not change repository visibility, publish a package or create a
public announcement.

Before that decision:

1. Review the exact commit and its changes. Keep the MIT license and upstream
   attribution intact; check wheel/source archives include required notices and
   setup/security documents.
2. Run the documented coverage, build and functional tests. Require green
   Python 3.11/3.14 CI, installed-artifact/MCP checks and a full-history secret
   scan on the reviewed commit. Inspect ignored/untracked artifacts before
   preparing any source archive; never include `.env`, cookies or profile data.
3. Recheck upstream Camofox application releases and image digests. Distinguish
   application releases from browser-binary backups. Audit Python and browser npm
   dependencies and review browser/OS security maintenance separately.
4. Verify a fresh standalone install without a proxy, then the intended existing
   Hermes/proxy configuration with disposable identities. Check pauses, actual
   Jev calls, continued tabs, cleanup and unchanged proxy routing.
5. Confirm README commands, agent registration/credentials, supported platforms,
   known limits, troubleshooting, security-reporting instructions and changelog
   match what was tested. Clearly distinguish CLI one-shot sessions, standalone
   MCP/Python sessions and native Hermes tab sharing.
6. Review the complete tracked tree and every historical commit for private
   operational information as well as credentials. A secret scanner does not
   detect personal design notes, deployment policies or infrastructure maps.
   Deleting a file leaves it in history. Keep the repository private throughout
   cleanup. Either prepare a new repository from a reviewed source snapshot with
   one initial commit and a new Git object database, or explicitly authorize a
   coordinated rewrite of the existing repository's history. For a rewrite,
   remove private files, text and messages from all historical refs; preserve
   and compare the tested source tree; migrate pinned consumers; and refresh
   local checkouts, worktrees and graph caches without restoring old history.
   Audit PR conversations, edit histories and Actions logs/artifacts separately.
   A force push does not purge GitHub-held PR refs or cached commits: complete
   the [GitHub sensitive-data removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
   and verify remaining server-side cleanup before publication. Review author
   metadata according to the maintainer's preferences. Verify all candidate refs
   and both source/wheel archives again before publication.
7. Remove obsolete merged remote branches. Check all candidate refs and ensure
   any private development hooks, environment files and browser profiles are
   excluded. Keep private tooling outside the published tree.
8. Prepare the version/tag and release notes for the reviewed commit. Mark
   untested platforms and breaking changes. Claim a PyPI installation only after
   publishing and independently testing that distribution.

When publication is explicitly approved, publish the reviewed repository only
after verifying that private historical data is no longer accessible, and verify
the intended source can be read without authentication. Review available GitHub
branch-protection/required-check settings and private vulnerability reporting for
the repository's plan and visibility. Publish only the reviewed artifacts and
retain test evidence. None of these actions are performed by this checklist.

## Publishing to PyPI

`.github/workflows/publish.yml` uploads the sdist and wheel when a GitHub
release is published. It uses PyPI trusted publishing, so no token is stored.
One-time setup: on PyPI add a trusted publisher for project `jev-browser` with
this repository, workflow `publish.yml` and environment `pypi`, and create the
`pypi` environment under the repository's Settings → Environments. To release,
bump the version in `pyproject.toml` and `jev_browser/plugin.yaml`, move the
CHANGELOG entries under the new version, merge, then publish a release tagged
`v<version>` on that commit. The workflow fails if the tag and version differ.

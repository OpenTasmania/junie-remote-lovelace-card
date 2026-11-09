<!-- SPDX-License-Identifier: MIT -->

# Frontend publication contract

Run `npm --prefix frontend run build` (or `npm --prefix frontend run dev` for
watch mode). The scripts build in a unique `frontend/.build-stage-*` directory
and publish only after Vite succeeds. These staging directories and the
`frontend/.build-test-*` test fixtures are ignored by Git. Running `vite build`
directly writes to `frontend/dist` and does not publish. The integration serves the tracked
`custom_components/junie_remote/frontend/junie-remote-card.js`; deployments copy
the integration directory, not `frontend/dist`. The Python source-distribution
file list is not the documented HA deployment mechanism.

`.junie-build-manifest.json` records the SHA-256 of every published output. Its
initial entry identifies the pre-existing tracked card bundle; keep the manifest
and bundle together in source control. New outputs may be added, but existing
unrecorded, modified, symlinked or malformed paths are never overwritten or
adopted. Secondary outputs must use a new filename when their bytes change (use
content-hashed names); the fixed card filename is the sole replaceable output.
Only recorded, unchanged obsolete files are removed, and unrelated files remain.
An interrupted publication may leave an unrecorded file or a mismatched manifest;
inspect and reconcile it manually rather than inferring ownership from a name.

The output directory and its ancestors must be real directories, controlled by
the builder: do not modify them concurrently outside these build scripts. The
lock excludes simultaneous publication by cooperating builds and fails immediately
if held, including watch builds. If builds finish at different times, the last
successful publication wins. If a process crashes and leaves `.junie-build.lock`
in the integration output or a `frontend/.build-stage-*` directory, confirm that
no build is running and inspect it before removing it manually. Temporary
`.junie-tmp-*` files left in the integration output by a crash also require
inspection. Symlinks and collisions fail closed, but this is not
a security boundary against a hostile process concurrently replacing paths.
An obsolete file that cannot be safely removed is retained and reported for
manual review. Failed builds leave the published card unchanged; a failed watch
cycle keeps watching for a later successful rebuild.
# Third-party components

## LayaAir 3.4.0 runtime

`vendor/layaair-3.4.0/libs/` contains the JavaScript runtime files required by
the headless renderer. They were copied from the LayaAirIDE 3.4.0 engine build;
the editor itself is not included. LayaAir is maintained by Layabox and its
source is available at <https://github.com/layabox/LayaAir> under the repository
license.

## Playwright

The browser driver is installed from the `playwright` npm package. Its pinned
version is recorded in `package-lock.json`; browser binaries are installed into
the user's Playwright cache and are not committed to this repository.

## Example assets

The fish model, textures, scene, materials, and reference renders under
`examples/` are included solely as the reproducible example dataset for this
project. Replace them with assets you are licensed to use when adapting the
pipeline to another project.

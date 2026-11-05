# Contributing

Thanks for helping. The most useful things right now are reports from other headsets and PCs, and help with new SteamVR builds.

## Reporting a problem

Use the bug report form. Include your SteamVR version and the end of `%LOCALAPPDATA%\CockpitPortal\cockpit_portal.log`. Check the
log first and remove anything you would rather not share, such as addresses.

## Making a change

1. Fork the repository and create a branch.
2. Keep each pull request to one change, and say what you tried and on what hardware.
3. Run the tests: `python -m unittest discover -s tests`. To build the installer: `packaging\build.ps1`
4. Open the pull request. Every change needs a review from the maintainer before it goes in.

Automated checks cannot test a headset. For anything that changes what happens in VR, say that you tried it in the headset. If you
could not, say so and someone else can.

## Rules that keep the project safe to share

- **Never commit Valve's files.** That includes shaders, patched shaders and their disassembly. Numeric ids and hashes needed to
  patch a user's own copy are fine.
- **Everything on the headset stays in the user's home folder.** No changes to `/usr` or `/opt`, and no root unless a maintainer has
  agreed it is needed.
- **Never store or log passwords.**
- **Changes to install scripts or SSH get extra review**, because they run on people's headsets. Explain anything that
  downloads or runs code.

## Supporting a new SteamVR build

`headset/gen_circle_spv.py` only patches a shader whose SHA-256 it knows, because updates can renumber the ids it uses. To add a build:

1. Run `spirv-dis --raw-id` on the new shader on your own headset.
2. Find the matching ids, and check the patched shader passes `spirv-val`.
3. Try it in the headset, and confirm the portal opens and closes and the rest of the image looks normal.
4. Update the hash and ids. Do not include the disassembly in your pull request.

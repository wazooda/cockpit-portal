# Notices

Cockpit Portal is not affiliated with or endorsed by Valve Corporation. Steam, SteamVR and Steam Frame are trademarks of Valve
Corporation. This project does not include Valve's shaders or any patched copy of them. They are read and patched only on the
user's own headset.

## Software downloaded during setup, not included here

- [mr-chroma-frame](https://github.com/spyjacob/steam-frame-chroma-key), MIT licence, copyright (c) 2026 spyjacob. Downloaded and built
  on the user's own headset by the installer. It provides the compositor layer and the shader override this project uses, and this project's approach
  to patching and blending builds on its work.

## Software included in the Windows installer

The source repository does not contain these. The built exe includes them, each under its own licence:

- [Python](https://www.python.org/), PSF licence, including tkinter and Tcl/Tk.
- [pyopenvr](https://github.com/cmbruns/pyopenvr), BSD licence, and Valve's [OpenVR](https://github.com/ValveSoftware/openvr) API library, BSD licence.
- [Pillow](https://python-pillow.org/), MIT-CMU licence.
- [PyInstaller](https://pyinstaller.org/)'s bootloader, GPL with an exception that permits this use.

#!/usr/bin/env python3
"""The start of the Windows program. One exe does four jobs:

    CockpitPortalSetup.exe        the setup wizard
    CockpitPortal.exe             the app, with the arguments in cockpit_portal.py
    CockpitPortal.exe uninstall   the uninstaller
    (run by ssh)                  hands the headset password to ssh, during setup only
"""
import os
import sys

import setup_core


def main():
    if os.environ.get(setup_core.ASKPASS_ENV) is not None:
        return setup_core.answer_askpass()
    if sys.argv[1:] == ["uninstall"]:
        import setup_wizard
        return setup_wizard.uninstall()
    if "setup" in os.path.basename(sys.executable).lower():
        import setup_wizard
        return setup_wizard.setup()
    import cockpit_portal
    return cockpit_portal.main()


if __name__ == "__main__":
    sys.exit(main())

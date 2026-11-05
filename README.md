# Cockpit Portal

See your real hands and controls while flying or driving in PC VR on the Steam Frame.

Cockpit Portal opens a window in your VR view that shows the real room through the headset's passthrough camera. Call up
the window with a hotkey when you need to reach for a radio, a keyboard or a button box, and close it again when you are done.
Set everything up from a page in the SteamVR dashboard.

> **Beta.** So far this has been used on one headset and one PC. It relies on unofficial changes to how the headset draws its
> image, and a SteamVR update can stop it working until the project is updated. Not affiliated with or endorsed by Valve.

## What it does

- Up to four saved portal positions, such as Avionics or Center. Open, close or jump between them with one key.
- A **Cockpit Portal** page in the SteamVR dashboard: move and resize a portal with the laser pointer, fix a double image,
  rename positions and change hotkeys, all without taking the headset off.
- Hotkeys for everything, from about 0.2 seconds to the portal changing.
- Voice control through any voice tool that can press a key. F13-F19 and F22 are always on for this, and for button boxes.

The portal is fixed in your view and moves with your head. It does not track your hands, and it stays where you put it rather
than staying over a real object. A small head movement brings your controls into it.

## What you need

- A Steam Frame with Developer Mode turned on, streaming from a Windows PC with SteamVR
- Python 3.10 or newer on the PC (the installer planned below will remove this step)
- The SteamVR build this release supports. The tools check this before patching anything

## Install

A one-step installer is planned. For now the setup is manual and takes about 15 minutes.

**1. Turn on Developer Mode.** On the headset: **Steam Settings > System > Enable Developer Mode**. Set a password if asked, and
find the headset's IP address in its Wi-Fi settings.

**2. Set up a key so the PC can reach the headset.** In PowerShell on the PC, using your headset's address:

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\id_ed25519_cockpit_portal -N '""'
type $HOME\.ssh\id_ed25519_cockpit_portal.pub | ssh steamos@<headset-ip> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

**3. Install the compositor layer on the headset.** Cockpit Portal is built on
[mr-chroma-frame](https://github.com/spyjacob/steam-frame-chroma-key), which makes the shader change possible. This builds it on
the headset, which already has the tools it needs. Log in with `ssh steamos@<headset-ip>`, then run:

```bash
git clone https://github.com/spyjacob/steam-frame-chroma-key ~/mr-chroma
cd ~/mr-chroma
git checkout 535c5f2
./build.sh && ./install.sh
touch ~/.config/mrchroma/enable-compositor
~/.local/share/mrchroma/mrctl set-bool camera forceSceneAlphaBlending 1
```

Then restart SteamVR on the headset.

**4. Copy Cockpit Portal to the headset.** From this project's folder on the PC:

```powershell
ssh steamos@<headset-ip> "mkdir -p ~/cockpit-portal"
scp headset\* steamos@<headset-ip>:cockpit-portal/
ssh steamos@<headset-ip> "chmod +x ~/cockpit-portal/portal.sh"
```

**5. Set up the PC.**

```powershell
pip install -r requirements.txt
mkdir $env:LOCALAPPDATA\CockpitPortal
copy config.example.json $env:LOCALAPPDATA\CockpitPortal\config.json
notepad $env:LOCALAPPDATA\CockpitPortal\config.json
```

Put your headset's address in `hosts`. You can list more than one, such as its streaming-link address and its Wi-Fi address. They
are tried in order, so it keeps working if one is down.

**6. Run it.**

```powershell
pythonw pc\cockpit_portal.py
```

Start streaming, open the SteamVR dashboard and look for **Cockpit Portal**. To start it with Windows, put a shortcut to that
command in your Startup folder. To close it: `python pc\cockpit_portal.py quit`.

## Using it

| Default key | What it does |
|---|---|
| Ctrl+Alt+0 | Portal on or off, at the last position used |
| Ctrl+Alt+1, 2, 3, 4 | Open a position. Again closes it, and another jumps there |
| Ctrl+Alt+arrows | Move the open portal |
| Ctrl+Alt+Page Up / Page Down | Bigger or smaller, 10% a step |
| Ctrl+Alt+I, K, J, L | Fix a double image (moves the right eye's circle) |
| Ctrl+Alt+S | Save the open position and size |

F13-F16 open the four positions, F17 and F18 change size, F19 saves and F22 is on or off.

Tones tell you what happened: high is on, low is off, two high is saved, and three short means it failed.

**Your first portal will probably look double.** Positions start from one person's measurements, and eyes and fit differ. Open a
position, go to **Adjust**, tap the arrows under **Looks double?** until you see one circle, then tap **Save**.

## Known problems

- **After a SteamVR update, the portal may refuse to open.** The patch only applies to a shader it has been checked against, so it stops
  rather than guessing. Please open an issue.
- **The streaming dongle sometimes will not connect after a headset restart.** This comes from the headset's own link service, not
  from this project: it can fail once at startup and not retry. To fix it, switch the headset's Wi-Fi to a network on another band
  and back. Reconnecting to the same network does not help.
- **Dashboard icons may show as a question mark on the Frame.** This affects other programs' buttons too.
- **Very low positions** can be hard to see, because they fall at the edge of what the lenses show.
- **Green-tinted passthrough** was seen once after a long sleep. Restarting SteamVR cleared it.
- **Performance cost** in a heavy sim has not been measured properly yet.

## Removing it

```powershell
python pc\cockpit_portal.py quit
ssh steamos@<headset-ip> "~/cockpit-portal/portal.sh off; rm -rf ~/cockpit-portal; cd ~/mr-chroma && ./uninstall.sh"
```

On the PC, delete `%LOCALAPPDATA%\CockpitPortal` and your Startup shortcut. The layer installs for your user only, and leaves
`/usr` and `/opt` unchanged.

## How it works

The headset's compositor loads the [mr-chroma-frame](https://github.com/spyjacob/steam-frame-chroma-key) layer, which can swap one of its
shaders as it loads. `headset/gen_circle_spv.py` makes a patched copy of that shader **on your own headset**, adding a circle where
the scene goes transparent. A hidden setting then makes the compositor draw the passthrough camera behind the scene. The hotkeys
reach the headset over one SSH connection that stays open, which is why they respond quickly.

This project does not include Valve's shader or any patched copy of it.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). Steam, SteamVR and Steam Frame are trademarks of Valve Corporation.

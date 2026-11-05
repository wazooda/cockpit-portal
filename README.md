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

## What you are installing

You should know what this puts on your equipment before you run it. All the code is here for you to read.

**On your PC**

- A small background program written in Python. You run it directly, so there is no service or driver.
- Global hotkeys. Windows sends it only the keys it has registered, and they stop reaching other programs while it runs. It is not a key logger: it
  checks other keys only while the Hotkeys page is waiting for you to press a new one.
- Your settings and log, in `%LOCALAPPDATA%\CockpitPortal`.
- An SSH key, and an entry in your `known_hosts` file for the headset.

**On your headset**

- Developer Mode turned on, which you do yourself, and your PC's SSH key. That key can log in to the headset as your user, so keep your PC secure.
- [mr-chroma-frame](https://github.com/spyjacob/steam-frame-chroma-key), a third-party program built on your headset from its source code. It loads
  inside the compositor, the part of SteamVR that draws everything you see.
- A hidden SteamVR setting, `camera/forceSceneAlphaBlending`, turned on.
- The scripts in `~/cockpit-portal`, and a patched copy of one SteamVR shader, made on your headset.

These all stay in your home folder. SteamVR's and SteamOS's own files are not changed.

**What it connects to**

Only your headset, over SSH on your own network. There are no accounts, analytics or update checks. The one other download is fetching
mr-chroma-frame from GitHub when you install it.

**What could go wrong**

- This changes how the headset draws its image, in a way Valve does not support. If the image looks wrong, `portal.sh off` or turning the portal off
  returns to the normal shader, and the [removal steps](#removing-it) take everything out.
- A SteamVR or SteamOS update can stop it working, or may remove parts of it.
- The portal only shows what the cameras see, with some delay. Do not rely on it for anything to do with safety.

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

## Technical details

### The problem

SteamVR gives a PC-streamed game no official way to show the Frame's passthrough camera. The game's image also reaches the headset
as a video stream with no transparency, so nothing on the PC can mark part of the picture as see-through. Patching the sim would not help
for the same reason. The cut-out has to happen on the headset, after the stream is decoded.

### The signal path

```text
Hotkey or voice tool  ->  RegisterHotKey on the PC  ->  queue  ->  long-lived SSH session
                                                                            |
SteamVR dashboard page (OpenVR overlay)  ->  same queue                     v
                                                               slots.py  ->  portal.sh
                                                                            |
              gen_circle_spv.py builds the patched shader, if its values changed
                                                                            |
              config updated  ->  vrcmd --reload-shaders  ->  layer swaps the shader
                                                                            |
              vrcompositor draws the scene with a hole  ->  camera shows through
```

### Cutting the hole

Three pieces work together on the headset:

1. **A Vulkan layer.** mr-chroma-frame installs a user-scope implicit Vulkan layer into `vrcompositor`. It intercepts
   `vkCreateShaderModule`, and when the compositor loads a shader named in `~/.config/mrchroma/mrchroma.conf`, it supplies a different
   SPIR-V file. Nothing under `/usr` or `/opt` changes.
2. **A hidden setting.** With `camera/forceSceneAlphaBlending` on, the compositor draws the passthrough camera and blends the scene over
   it using the scene's alpha. Where alpha is below 1, the camera shows through.
3. **A patched shader.** Streamed scenes here go through `distort_ps_achromatic_se2.spv`. `gen_circle_spv.py` disassembles the user's own copy
   with `spirv-dis --raw-id`, replaces the instruction that stores the final colour, reassembles it with `spirv-as`, and checks the result
   with `spirv-val`.

The inserted code does this for each pixel:

```text
alpha = 1
for each eye's centre:
    d     = distance(gl_FragCoord.xy, centre)
    alpha = min(alpha, smoothstep(radius - soft, radius + soft, d))
output = vec4(rgb * alpha, alpha)     // premultiplied
```

`gl_FragCoord` was a useful find: the stock shader declares it as an input but does not use it, so the patch can place a circle in output
pixels. The colour is premultiplied, and the soft edge avoids a hard line around the portal.

The patch relies on the shader's internal numeric ids, which a SteamVR update can renumber. So the generator checks the stock shader's
SHA-256 and refuses any file it has not been checked against. `portal.sh` also records that hash, and refuses to apply an old patch if the
stock shader has changed. An override is matched by file name alone, so without this a stale patch could be applied to a different shader.

### Placing a circle in each eye

The compositor renders to one 4320x2160 target, with the left eye on the left half. So one portal is two circles in that image, and
`--centers` takes both. In this target a larger x moves a circle **left** in view, in both eyes, and a larger y moves it **up**.

We first calculated centres from OpenVR's eye and projection data. That worked straight ahead, at a 50 cm focus distance, but drifted
off-axis. We then measured it directly: a person moved the right eye's circle at seven positions until it looked like one circle:

- Every position could be made to look like one circle.
- The vertical difference between the eyes grew steadily with sideways angle, about 7 pixels per degree. The calculation predicted about
  2.5. We have not established why.
- Horizontal differences showed no simple pattern, which is expected because the eyes fuse them as a change in depth.

That was one person in one run, so it is not a calibration. It is why each position has its own **Looks double?** adjustment instead of relying on a formula,
and why the defaults are only starting points.

### Making it fast

The first version took a second or more per press, mostly from opening a new SSH connection. It now works like this:

- One SSH session stays open to `slots.py serve`, and is proved alive with a ping before each command.
- The layer notices config changes by whole-second file time, so `portal.sh` waits only if the previous change was in the same second.
- `portal.sh` confirms each change from the layer's log, which records whether the compositor got the override. You get a success
  tone only after that confirmation.

Opening or closing took about 0.2 to 0.3 seconds from key press to confirmation in our tests, and about 0.4 seconds from releasing a push-to-talk button
with a voice tool. Because of the whole-second rule, rapid adjustments can take 1 to 2 seconds to catch up, so they are added together and
applied as one.

### The Windows side

- **Hotkeys:** `RegisterHotKey` on the main thread, which is the thread that owns them. Keys with no modifier are provided because a sim
  reading Raw Input sees a modifier even when another program takes the hotkey. Shift is refused because, alone, it is the VR recenter key in MSFS.
- **Dashboard page:** an OpenVR dashboard overlay using [pyopenvr](https://github.com/cmbruns/pyopenvr). Pages are drawn with Pillow,
  and saved in turn to two PNG files so SteamVR never reads one half written. Clicks arrive as overlay mouse events, counted from the bottom.
- **Avoiding unwanted starts:** it attaches only while `vrmonitor.exe` runs and `isHmdPresent()` is true. A sim can start `vrserver` for a moment, and
  connecting then could bring up the whole SteamVR interface.
- **VR keyboard:** `KeyboardFlag_Minimal` is needed for key-by-key events, which is the only way to detect Enter. In that mode the keyboard's own
  text only held the last key in our tests, so the page keeps its own copy. pyopenvr 2.12's `getKeyboardText` also passes its buffer as the
  length and raises an error, so the page calls the function directly.
- **Key capture:** hotkeys are paused while waiting for a new key, and `GetAsyncKeyState` reads it from any window.
- **SSH:** `HostKeyAlias` gives the headset one identity across its addresses. The key is trusted on first connection and refused if it later changes.

### What we tried and set aside

- **Following the hands.** Quest-style hand tracking was the original goal. An on-headset tracker looked possible but heavy, so it is parked. It
  probably needs support from Valve.
- **Following the eyes.** The headset's eye data did follow natural looks. We dropped it because of how pilots work: glance up at a screen
  while working a radio, and a portal following your eyes would open over that screen.
- **Moving the portal with a controller.** A background program on the headset could read controller positions during a stream, but none of
  the five buttons we tried registered. Holding a controller at the spot and using a command could still work, but that has not been built.

### What the stream's network does

The dongle joins a private hidden network that the headset creates (`softapmanager` running `hostapd`). SteamVR's link can also use your home network
at the same time, and in our measurements both paths carried stream traffic. The private network uses the opposite band from your home
Wi-Fi.

The dongle startup failure under [Known problems](#known-problems) comes from here. `hostapd` can exit about a second after boot with
`Device or resource busy`. `softapmanager` then only logs a failure every 20 seconds, and starts it again only when the Wi-Fi frequency changes.
That is why changing band fixes it and reconnecting to the same network does not.

### Not yet known

- The frame-time cost in a heavy sim, including the cost of `forceSceneAlphaBlending`
- Why the two eyes' vertical difference is larger than calculated
- Why the Wi-Fi radio is busy at startup on some boots
- Why dashboard icons show a question mark on the Frame
- How well any of this holds up on other headsets, faces and PCs

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). Steam, SteamVR and Steam Frame are trademarks of Valve Corporation.

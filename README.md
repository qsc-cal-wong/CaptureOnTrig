# CaptureOnTrig
Capture images from scope for every trigger.

## Starting and stopping

The program displays its introductory instructions before asking for an IP
address. Configure the channels, timebase, trigger source, and trigger level
on the scope's front panel first. Press Enter to continue, or Q then Enter
to quit without connecting.

During capture, Q or Ctrl+C stops acquisition and releases the connection.
After stopping (including a timeout or reported error), press Enter to exit.
This keeps the console open so you can review the output.

## Supported scopes

- Rigol DS1000Z
- Tektronix DPO4000/B (including DPO4034 and DPO4054B), using Ethernet hardcopy
- Tektronix MSO5/B (MSO54, MSO56, MSO58 and B variants), using image-file transfer
- Tektronix MSO6/B (MSO64, MSO66, MSO68 and B variants), using image-file transfer
- LeCroy WaveRunner 8108HD

Tektronix setup disables SCPI response headers so acquisition-state polling
receives numeric replies. Trigger source and level are preserved.

The DPO4054B was hardware-validated with two software-forced triggers, one
normal signal trigger, and valid 1024x768 PNG captures. The MSO68B was
hardware-validated with two software-forced triggers and valid 1920x1080 PNG
captures, with trigger source and levels unchanged. MSO5/B file-transfer
commands are regression-tested; the MSO54 was also successfully tested
by the user. Rigol DS1000Z and LeCroy WaveRunner 8108HD were previously
reported as successfully tested.

Run the console-flow and Tektronix regression tests with
`python -m unittest -v`. The seven tests cover startup instructions and
cancellation, cleanup before exit confirmation, closed-input reporting,
model-family routing, header-free trigger polling, and unsupported models.

## Building the Windows executable

From the project directory, with your Python environment activated:

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm CaptureOnTrig.spec
```

The spec produces a single-file console executable and includes
`--hidden-import pyvisa_py`. To regenerate it from the script instead:

```powershell
python -m PyInstaller --clean --noconfirm --onefile --console --hidden-import pyvisa_py CaptureOnTrig.py
```

Before deploying, run the executable from a terminal and check for errors:

```powershell
Set-Location .\dist
.\CaptureOnTrig.exe
```

The executable requires a console for its input
prompts, status messages, and Q/Ctrl+C controls. Do not build with `--windowed`
or `--noconsole`: without standard input, prompts fail with
`RuntimeError: input(): lost sys.stdin`.

The spec also bundles the dynamically loaded `pyvisa_py` backend required by
`ResourceManager("@py")`.

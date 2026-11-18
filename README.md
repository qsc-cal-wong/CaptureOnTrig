# CaptureOnTrig
Capture images from scope for every trigger.

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

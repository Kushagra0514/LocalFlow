# Third-party notices

LocalFlow packages the following third-party software and model artifacts.
Complete license texts and required notices are in the `licenses` directory;
the Windows package additionally exports licenses for its frozen Python
dependencies.

| Component | Pinned version or artifact | License / notice |
| --- | --- | --- |
| whisper.cpp | Windows x64 CPU build `b4938` | MIT; see `licenses/WHISPER_CPP_LICENSE.txt` |
| Whisper `base.en` Q5 | `ggml-base.en-q5_1.bin` | MIT; see `licenses/WHISPER_MODEL_LICENSE.txt` |
| PortAudio | bundled through sounddevice | PortAudio license; see `licenses/PORTAUDIO_LICENSE.txt` |
| Microsoft Visual C++ Runtime | bundled unmodified with native executables | Microsoft redistribution notice; see `licenses/MICROSOFT_VISUAL_CPP_RUNTIME_NOTICE.txt` |
| CPython, certifi, NumPy, keyboard, pyperclip, sounddevice, PyInstaller | pinned in `uv.lock` | License copies exported into packaged `licenses/python-packages` |

## Model and runtime integrity

The application verifies first-run model downloads by exact byte length and
SHA-256 before installing them. The packaging script similarly verifies its
pinned native-runtime archives before extraction.

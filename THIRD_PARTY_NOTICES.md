# Third-party notices

LocalFlow packages the following third-party software and model artifacts.
Complete license texts and required notices are in the `licenses` directory;
the Windows package additionally exports licenses for its frozen Python
dependencies.

| Component | Pinned version or artifact | License / notice |
| --- | --- | --- |
| whisper.cpp | Windows x64 CPU build `b4938` | MIT; see `licenses/WHISPER_CPP_LICENSE.txt` |
| llama.cpp | Windows x64 CPU build `b10516` | MIT; see `licenses/LLAMA_CPP_LICENSE.txt` |
| Whisper `base.en` Q5 | `ggml-base.en-q5_1.bin` | MIT; see `licenses/WHISPER_MODEL_LICENSE.txt` |
| S1-mini by Superwhisper Q4_K_M | `s1-mini-q4_k_m.gguf` | Apache-2.0 derivative terms and required naming notice; see `licenses/S1_MINI_LICENSE.txt` and `licenses/S1_MINI_NOTICE.txt` |
| PortAudio | bundled through sounddevice | PortAudio license; see `licenses/PORTAUDIO_LICENSE.txt` |
| Microsoft Visual C++ Runtime | bundled unmodified with native executables | Microsoft redistribution notice; see `licenses/MICROSOFT_VISUAL_CPP_RUNTIME_NOTICE.txt` |
| CPython, NumPy, keyboard, pyperclip, sounddevice, PyInstaller | pinned in `uv.lock` | License copies exported into packaged `licenses/python-packages` |

## Model and runtime integrity

The application verifies first-run model downloads by exact byte length and
SHA-256 before installing them. The packaging script similarly verifies its
pinned native-runtime archives before extraction.

The product and documentation preserve the required spelling **S1-mini by
Superwhisper**.

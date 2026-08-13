# effective-octo-dollop

## PS2 emulator scaffold

This repository now includes a minimal PlayStation 2 emulator scaffold in
`ps2_emulator.py`.

Current capabilities:
- Load BIOS bytes from a file
- Power-on/reset lifecycle
- Execute pseudo-instructions via `step()`
- Run instruction batches with `run_frame()`
- Report state using `status()`

Run tests:

```bash
python -m unittest discover -s tests
```

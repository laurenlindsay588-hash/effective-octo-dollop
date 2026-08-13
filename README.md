# effective-octo-dollop

## PS2 emulator milestone architecture

This repository now includes a milestone-1 PlayStation 2 hardware architecture in
`ps2_emulator.py`.

Current capabilities:
- EE core reset and step cycle skeleton
- Memory-map region routing (EE RAM, IOP RAM, BIOS, scratchpad)
- MMU KSEG translation helpers for EE virtual addresses
- Read-only BIOS region enforcement
- Event scheduler cycle tracking
- Facade API (`PS2Emulator`) for loading BIOS and running instruction frames

Run tests:

```bash
python -m unittest discover -s tests
```

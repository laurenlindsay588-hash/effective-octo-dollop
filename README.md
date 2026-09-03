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
- Timer and interrupt-controller memory-mapped device stubs
- Facade API (`PS2Emulator`) for loading BIOS and running instruction frames
- ELF32 PT_LOAD segment loading scaffold for future homebrew execution

Run emulator scaffold:

```bash
python ps2_emulator.py --bios /absolute/path/to/bios.bin --instructions 3 --frames 1 --status-json
```

Controlled run options:
- `--max-cycles N` stop once total executed cycles reaches `N`
- `--trace` print per-instruction trace lines
- `--status-every N` print periodic JSON status snapshots every `N` instructions
- `--elf /absolute/path/to/program.elf` load ELF32 PT_LOAD segments into memory
- `--boot-elf` start PC from ELF entry point (requires `--elf`)

Run tests:

```bash
python -m unittest discover -s tests
```

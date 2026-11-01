# Diagnostic tools

These are the scripts used to find and confirm the bug. They are plain Python 3
with `ctypes` (no third-party packages, except `tools/disasm.py` which needs
`capstone`).

| script | what it does |
|---|---|
| `attachwatch.py` | prints the per-thread input state of the game process whenever it changes. The key diagnostic: two threads reporting the same active window means a stuck `AttachThreadInput`. |
| `window_state.py` | dumps the game window's geometry, style, `WM_NCHITTEST` results and `GetGUIThreadInfo` — proves the window itself is healthy. |
| `iatdump.py <pid>` | reads the live import table of `system.dll` / the exe, resolving each import to its runtime address (used to set accurate breakpoints on a 32-bit target). |
| `disasm.py <rva> [count]` | minimal PE-aware disassembler for `system.dll`: annotates IAT references as `dll!Function` and internal branches as target RVAs. Path to the DLL is at the top of the file. |

Typical use while the game is wedged:

```
python tools/attachwatch.py
```

Expected healthy output:

```
tid 2804  (MAIN) active=0x180C18 [OCGameApplicationWindow] focus=0x180C18
=> single thread
```

Expected broken output:

```
tid 2804  (MAIN) active=0x180C18 [OCGameApplicationWindow] focus=0x180C18
tid 20872        active=0x180C18 [OCGameApplicationWindow] focus=0x180C18
=> ATTACHED! {1575960: [2804, 20872]}
```

`attachwatch.py` and `window_state.py` locate the game by window class
`OCGameApplicationWindow`, so they work for any Nitroplus title using it.

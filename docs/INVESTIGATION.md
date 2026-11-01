# Investigation notes — how this bug was found

This document is the full record of the debugging session, including the dead
ends. If you only want the fix, read the [README](../README.md).

Everything below was done on a retail Japanese copy of *Gekkou no Carnevale* on
Windows 11 (Italian locale), 64-bit OS, 32-bit game.

---

## 1. What we knew at the start

Player reports: after using the menus, the game "freezes" — it keeps rendering
and playing music, Windows does not grey it out, but mouse and keyboard do
nothing. Alt-tabbing away and back does not help. Restarting does.

First suspicion was a deadlock in the render/present thread, which is the usual
cause for a VN that looks alive but is deaf.

## 2. The engine

`GekkounoCarnevale.exe` is a 32-bit PE that loads `system.dll` — the Nitroplus
engine module — at a fixed base `0x10000000`, size `0x104000`.

Relevant facts established by reading the PE import table:

* no `GetAsyncKeyState`, no DirectInput, no raw input, no `SetWindowsHookEx`:
  **all input arrives as window messages**;
* no `SetCapture`, no `ReleaseCapture`, no `ClipCursor`, no `BlockInput`,
  no `SetActiveWindow` — the engine cannot be leaving a mouse capture behind;
* it imports `DialogBoxParamA`, `CreateDialogParamA`, `EndDialog`,
  `TrackPopupMenu`, `ShowWindow`, `SetWindowPos`, `SetWindowLongA`,
  `EnableWindow`, `SetForegroundWindow`, `CreateWindowExA`, `DestroyWindow`,
  `MessageBoxA`, `SetCursorPos`, `SetFocus` and DirectDraw/DirectSound/DirectShow.

### Finding the window procedure

Breakpoint on `user32!RegisterClassExA` at process start gave the window class
`OCGameApplicationWindow` and `lpfnWndProc = system.dll+0x48900`.

Disassembling it shows it is only a thunk:

```
0x10048900  push lParam / wParam / msg / hwnd
            mov  ecx, [0x100e6fcc]      ; application singleton
            mov  eax, [ecx]             ; vtable
            call dword ptr [eax + 0x68] ; app->WndProc(hwnd, msg, wp, lp)
            ret  0x10
```

Reading the singleton in the live process gave the real object (`0x00194570`),
its vtable (`0x100C7880`) and therefore the real window procedure:
`system.dll + 0x495A0`.

### The message dispatch

`0x495A0` is a plain switch:

| message | target |
|---|---|
| `WM_ERASEBKGND` 0x14 | inline |
| `WM_ACTIVATEAPP` 0x1C | `vtable+0x8C` |
| `WM_KEYDOWN` 0x100 | `vtable+0x48` (`0x49F40`) |
| `WM_KEYUP` 0x101 | `vtable+0x44` |
| `WM_COMMAND` 0x111 | notification 0 → `+0x84`, 1 → `+0x88` |
| `WM_MOUSEMOVE` 0x200 | `vtable+0x4C` (`0x4A000`) |
| `WM_LBUTTONDOWN` 0x201 | `vtable+0x54` (`0x4A0B0`) |
| 0x202…0x206 (button up / dblclk) | jump table at `0x10049CD4` |
| `WM_MOUSEWHEEL` 0x20A | separate |
| **everything else**, including `WM_NCHITTEST`, `WM_MOUSEACTIVATE`, all `WM_NC*` | `DefWindowProcA` |

The handlers themselves are trivial — for example `WM_LBUTTONDOWN` at
`0x1004A0B0`:

```
[this+0xD4] = 1              ; "button event = down"
[this+0xCC] = lParam & 0xFFFF    ; mouse x
[this+0xD0] = lParam >> 16       ; mouse y
call [this+0x110] + 0xC          ; input subsystem vtable call
call [this+0x104] + 0xC          ; another subsystem
```

So input handling is completely ordinary, and hit-testing is stock
`DefWindowProc`. There is no engine-level input filtering to find.

### The modal dialogs

`DialogBoxParamA` has exactly two call sites in the whole module; the one behind
Settings is a small wrapper at `rva 0x17C30`:

```
mov  [eax+0x1C], 0
call DialogBoxParamA          ; rva 0x17C49
cmp  eax, -1
jne  short
call GetLastError
ret
```

Nothing suspicious around it — the engine does not touch window state when the
dialog closes.

## 3. Ruling out the obvious

Every one of these was measured on the *wedged* process:

| hypothesis | method | result |
|---|---|---|
| deadlock | per-thread CPU usage over 3 s | all 23 threads ≈ 0 ms |
| stuck in a nested loop | stack of the UI thread | parked in `GetMessageA` in the main loop |
| message filter | `GetMessageA` arguments read off the stack | `hwnd = NULL`, `min = max = 0` |
| hung | `IsHungAppWindow` | `FALSE` |
| disabled / hidden window | `IsWindowEnabled`, `IsWindowVisible`, `IsIconic`, `IsCloaked` | visible, enabled, normal |
| stuck mouse capture | `GetGUIThreadInfo` on **every** GUI thread of **every** process | `hwndCapture = 0` everywhere |
| menu loop | `GetGUIThreadInfo` flags | `0x0` (no `GUI_INMENUMODE`/`GUI_SYSTEMMENUMODE`) |
| move/size loop | `GetGUIThreadInfo.hwndMoveSize` | `0` |
| hit-testing broken | `SendMessage(WM_NCHITTEST)` on caption/client | `HTCAPTION` / `HTCLIENT`, correct |
| global input broken | own topmost window overlapping the game | received mouse input and could be dragged |
| window re-created | full-session message log | one `WM_CREATE`, zero `WM_DESTROY` |

Note on the last one: stale handles from `Get-Process` made it *look* as if the
engine re-created its window (the handle kept changing). The debugger log
disproved it — the window is created once and never destroyed. Lesson: trust the
message log, not handle values collected at different times.

## 4. The decisive experiment

Breakpoint on the window procedure, then the user moved the mouse and pressed
keys while the game was wedged. The trace contained **only** `WM_GETICON` (the
shell asking for the taskbar icon, i.e. *sent* messages):

```
0x7f WM_GETICON  0x7f WM_GETICON  0x7f WM_GETICON ...   (34 of them, nothing else)
```

Meanwhile, from another process, `PostMessage(hwnd, WM_LBUTTONDOWN/WM_LBUTTONUP)`
was processed by the game instantly — it even advanced two lines of dialogue.

Conclusion: the message loop works, the queue works, **hardware input is not
reaching the queue**.

## 5. Tracing the dialog lifecycle

Next: breakpoints on every window-state API the engine imports, then reproduce
the wedge (right-click → Settings → close). The trace (message tokens `M` from
the window procedure, `CALL` tokens from the breakpoints):

```
[857] CALL DialogBoxParamA       <- settings opened
[862] WM_ENABLE wp=0             <- game window disabled (modal)
[866] CALL CreateDialogParamA
[869] CALL ShowWindow            <- dialog shown
[870] CALL SetWindowPos
 ... dialog interaction ...
[978] CALL EndDialog             <- user closes it
[979] WM_ENABLE wp=1             <- game window re-enabled
[982] WM_NCACTIVATE wp=1
[983] WM_ACTIVATE  wp=1 (ACTIVE)
[986] WM_SETFOCUS  wp=<dialog>
[987] CALL DestroyWindow         <- dialog destroyed
[988] CALL DestroyWindow
[989+] ... WM_GETICON forever. No input messages, ever again.
```

Everything user32-visible is correct at the end: the main window is re-enabled,
re-activated and focused. Yet input dies at the exact instant the dialog window is
destroyed.

A negative result from the same trace, worth recording: during an ordinary
right-click that does *not* open a dialog, the engine makes **no** window-state API
calls at all. Its menus are pure DirectDraw.

## 6. The breakthrough

`GetGUIThreadInfo` for the game's main thread looked perfect. The bug only shows
up when you ask **every thread of the process**:

```
tid 2804   active=0x180C18[OCGameApplicationWindow] focus=0x180C18
tid 20872  active=0x180C18[OCGameApplicationWindow] focus=0x180C18
```

Two threads reporting the same active window means their **input queues are
attached** (`AttachThreadInput`). Normally only the thread that owns the focus
window reports it.

Calling

```c
AttachThreadInput(20872, 2804, FALSE);   // returned TRUE - there *was* an attachment
```

restored mouse and keyboard input instantly and completely. The reverse call
returned `FALSE` with `ERROR_INVALID_PARAMETER`, confirming there was nothing
left to detach.

## 7. Why the attachment is left behind

The engine opens the dialog from a helper thread; the modal machinery joins that
thread's input queue to the queue of the thread that owns the game window, and
Windows normally undoes it when the dialog closes.

Observed behaviour (reproducible): this goes wrong **once per game session**,
typically the first mouse-opened modal dialog; after a manual detach it stops
happening until the game is restarted. That is consistent with the attachment
racing against the helper thread's creation/teardown the first time it is used,
and with the dialog then running on an already-existing thread afterwards.

The precise ordering inside win32k was not instrumented (that would need kernel
debugging), and it is not required for the fix: the *symptom state* is easy to
recognise and the repair is a single documented API call.

## 8. Verifying the fix

`tools/attachwatch.py` prints the per-thread input state whenever it changes.
Healthy run (dialog opened and properly cleaned up):

```
 8.74s  tid 2804 (MAIN) active=0x180C18[OCGameApplicationWindow] => single thread
11.62s  tid 2804 + tid 20872 both active=0x180C18               => ATTACHED
11.74s  tid 2804 + tid 20872 both active=0x1F0BE8[#32770]       => ATTACHED (dialog, legit)
12.71s  tid 2804 only                                            => single thread
```

Broken run: the last block never appears.

The shipped tool watches for exactly that state (plus "no visible `#32770`" and a
persistence requirement) and detaches it. First field test on a fresh game
session, with the tool running unattended:

```
[17:53:01] GekkouInputFix started
[17:53:27] repaired: detached input queue of thread 16236 from game thread 6292 (hwnd 0xEF09F2)
```

The player noticed nothing: the game was deaf for roughly 200 ms.

## 9. Tooling

* **WinDbg / cdb (x86)** — attaching to the 32-bit game. Note that cdb is the
  parent of the debuggee: force-killing the debugger kills the game.
* **Python + ctypes** for all userland probing (`GetGUIThreadInfo`,
  `SendMessageTimeout`, `AttachThreadInput`, import-table reading via
  `ReadProcessMemory`).
* **Capstone** for offline disassembly of `system.dll`
  (`tools/disasm.py`, resolves IAT slots to `dll!Function` names).

## 10. Reproducing from scratch

1. Start the game, get in-game, right-click → Settings, close the dialog.
2. If the game now ignores input: `python tools/attachwatch.py` should show two
   threads sharing the game window as active window.
3. `GekkouInputFix.exe --repair-now` (or Ctrl+Alt+F with the tool running) should
   fix it immediately and add one `repaired:` line to the log.
4. If `attachwatch.py` shows the attach happening *and* being released on a run
   where the bug did not occur, compare the two runs — that difference is the
   race.

## 11. Open questions

* Which exact code path issues the unmatched `AttachThreadInput`? (`DialogBoxParamA`
  on a helper thread is the prime suspect; the engine never calls
  `AttachThreadInput` itself.)
* Whether the same bug affects other Nitroplus titles — the tool keys off the
  window class `OCGameApplicationWindow`, so it will try, and reports are welcome.
* Whether a proper engine-side fix (opening dialogs on the UI thread, or calling
  `AttachThreadInput(..., FALSE)` after each dialog) would remove the need for a
  helper process in future releases.

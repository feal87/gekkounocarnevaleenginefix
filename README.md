# GekkouInputFix

A community fix for the **"game stops responding to mouse and keyboard"** bug in
*Gekkou no Carnevale* (`GekkounoCarnevale.exe`, Nitroplus engine) on modern
Windows.

> The game keeps animating and playing audio, Windows does not mark it "Not
> Responding", and it is not crashed or deadlocked — it simply ignores every
> mouse click, mouse movement and keypress until you restart it.

`GekkouInputFix.exe` is a 9.7 KB silent background helper that detects the broken
state and repairs it in a fraction of a second. No DLL injection, no game-file
modification, no patching, no synthetic clicks, no network access.

---

## Quick start

1. Download `GekkouInputFix.exe` from [`dist/`](dist/GekkouInputFix.exe)
   (or build it yourself, see [Building](#building)).
2. Put it next to `GekkounoCarnevale.exe` — or anywhere, it does not care.
3. Run it before or after starting the game. It has no window and no tray icon.
4. Play.

`PlayWithFix.cmd` is a convenience launcher that starts the helper and then the
game.

Manual repair any time: **Ctrl+Alt+F**. One-shot repair from a script:
`GekkouInputFix.exe --repair-now`.

A log file (`GekkouInputFix.log`) is written next to the exe. It normally
contains only the start line:

```
[2026-11-01 17:53:01] GekkouInputFix started (Ctrl+Alt+F forces a repair, ...)
```

When it repairs the bug you will see:

```
[2026-11-01 17:53:27] repaired: detached input queue of thread 16236 from game thread 6292 (hwnd 0xEF09F2)
```

That line is the whole point of this repository. Please attach the log to any bug
report.

### Workarounds without running the tool

* Open save/load/settings with the **keyboard** shortcuts instead of the mouse —
  keyboard-opened menus do not trigger the bug.
* The **first** mouse-opened dialog of a session is the one that hangs. If the
  game locks up, restart it and it usually behaves for the rest of the session.
* Clicking another window and then back on the game helps on some systems.

---

## The bug

Reproduction (100% deterministic on affected systems, once per session):

1. Right-click in game → open the menu.
2. Choose **Settings** (or save/load) → a modal Win32 dialog opens.
3. Close the dialog.
4. The game keeps running, but the mouse and the keyboard are dead.

What makes this bug so confusing is what it is *not*:

* not a deadlock — every thread sits at ~0 ms CPU, and the main thread is parked
  in a perfectly normal `GetMessageA` loop;
* not a hang — `IsHungAppWindow()` is `FALSE`;
* not a disabled or hidden window — the window is visible, enabled, active,
  focused and foreground;
* not a stuck mouse capture or menu loop — `GetGUIThreadInfo()` reports no
  capture, no `GUI_INMENUMODE`, no move/size loop, for every thread of every
  process;
* not the engine ignoring input — the window procedure receives **zero** input
  messages.

The decisive measurement: with a debugger breakpoint on the game's window
procedure, while the user moved the mouse and pressed keys, the only messages the
window received were shell `WM_GETICON` queries. **No `WM_MOUSEMOVE`, no
`WM_NCHITTEST`, no `WM_KEYDOWN`, nothing.** At the same time, messages *posted*
into the window from another process were processed normally — a posted
`WM_LBUTTONDOWN`/`WM_LBUTTONUP` pair even advanced the dialogue.

So: the game's **thread input queue** was alive and pumping, but no longer
receiving *hardware* input.

## The root cause

The engine opens its configuration dialogs with `DialogBoxParamA`. Modal dialogs
made the engine (or the modal machinery it uses) call `AttachThreadInput()` to
join the **dialog thread's input queue** with the queue of the thread that owns
the game window.

Windows is supposed to undo that attachment when the dialog closes. In this
engine it sometimes does not. The game thread's input queue then remains attached
to a thread that no longer owns the input focus, and win32k stops routing
hardware input to the game window. Posted messages are unaffected, which is why
the process looks perfectly healthy from the outside.

Watching every GUI thread of the game process while the dialog opens and closes
makes the failure obvious. Healthy run:

```
 8.74s  tid 2804  (MAIN) active=0x180C18 [OCGameApplicationWindow] focus=0x180C18
        => single thread
11.62s  tid 2804  (MAIN) active=0x180C18 [OCGameApplicationWindow] focus=0x180C18
        tid 20872        active=0x180C18 [OCGameApplicationWindow] focus=0x180C18
        => ATTACHED {2804, 20872}
11.74s  tid 2804  (MAIN) active=0x1F0BE8 [#32770] focus=0x570C12
        tid 20872        active=0x1F0BE8 [#32770] focus=0x570C12
        => ATTACHED {2804, 20872}          (the modal dialog, legitimate)
12.71s  tid 2804  (MAIN) active=0x180C18 [OCGameApplicationWindow] focus=0x180C18
        => single thread                     (attachment released - healthy)
```

Failing run: the last block never happens. Both threads keep reporting the game
window as their active window, and input is dead.

## The fix

```c
AttachThreadInput(stuckThread, gameThread, FALSE);
```

Detaching the stale attachment restores hardware input **immediately** and
permanently for that session.

`GekkouInputFix.exe` does that automatically:

* it finds the process that owns a visible window of class
  `OCGameApplicationWindow`;
* every 60 ms it asks `GetGUIThreadInfo()` for every thread of that process;
* if the game thread's active window is the game window itself, and another
  thread of the same process reports that *same* active window, and **no dialog**
  (`#32770`) is visible, then a stuck attachment exists;
* the state must persist for 3 consecutive polls (~180 ms) so that the legitimate
  short window between "dialog thread attached" and "dialog created" is never
  disturbed;
* it then calls `AttachThreadInput(t, main, FALSE)` for every stuck thread.

Because the check runs against the *active window*, a legitimately open modal
dialog (whose active window is the dialog, not the game) is never affected.

### Safety

* Every call is a **detach**. A wrong guess fails harmlessly with
  `ERROR_INVALID_PARAMETER`.
* Only threads of the process that owns an `OCGameApplicationWindow` are touched.
* Nothing is attached, injected, patched or renamed.
* The only file written is its own log.

## Verification

`tools/attachwatch.py` prints the per-thread input state live, which is how the
bug and the fix were confirmed:

```
python tools/attachwatch.py
```

Then open and close the Settings dialog and watch the `ATTACHED!` lines appear and
(should) disappear. If they stay, the game is in the broken state — start the
fixer (or press Ctrl+Alt+F) and they go away together with the bug.

`tools/window_state.py` dumps the window geometry/style, `WM_NCHITTEST` results
and `GetGUIThreadInfo()` for the game window — useful to prove the window itself
is innocent.

## Building

The tool is C# 5 with no dependencies beyond the .NET Framework 4.x that ships
with Windows 10 and 11:

```
cd src\GekkouInputFix
build.cmd
```

or directly:

```
csc -nologo -target:winexe -optimize+ -out:..\..\dist\GekkouInputFix.exe main.cs
```

## Other Nitroplus games

The tool locates the game by window class, not by executable name, so it should
also work for other Nitroplus-engine titles suffering from the same bug. Reports
and confirmations are welcome.

## Background

This was found by reverse-engineering `system.dll` (the Nitroplus engine module)
and tracing the live process: the window procedure is a thunk to a virtual
method, the message dispatch table was mapped, the modal dialog call sites were
located, and the actual Win32 calls made during the dialog lifecycle were
breakpointed. The full story — including every dead end, which is the interesting
part — is in [`docs/INVESTIGATION.md`](docs/INVESTIGATION.md).

## License

MIT-0 — public domain equivalent. Do whatever you want with it.

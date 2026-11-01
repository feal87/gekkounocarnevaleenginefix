// GekkouInputFix - input recovery tool for Gekkou no Carnevale (Nitroplus engine)
//
// ROOT CAUSE (verified by tracing the live process with WinDbg):
//   Opening a modal Win32 dialog (Settings / save-load, window class "#32770")
//   makes the engine attach the dialog thread's input queue to the thread that
//   owns the game window (AttachThreadInput).  Windows normally detaches them
//   again when the dialog closes, but in this engine that detach sometimes never
//   happens.  The game thread's input queue is then permanently attached to a
//   thread that no longer owns the input focus, and win32k stops delivering
//   *hardware* input (mouse and keyboard) to the game window - while messages
//   posted by other processes are still processed.  The game looks frozen but is
//   running fine.
//
// FIX:
//   Detect that stuck attachment and undo it with AttachThreadInput(t, main, FALSE).
//   Hardware input returns immediately and stays working for the whole session.
//
// SAFETY:
//   * only ever detaches (false); a wrong guess is a harmless no-op (error 87)
//   * only touches threads of the process that owns a window of class
//     "OCGameApplicationWindow"
//   * only acts when the shared active window IS the game window and no dialog
//     is visible, and only after the state has persisted for several polls, so a
//     legitimately open modal dialog is never disturbed
//   * Ctrl+Alt+F forces a repair (belt and braces)
//
// BUILD:  csc /target:winexe /optimize+ /out:GekkouInputFix.exe main.cs

using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

static class GekkouInputFix
{
    const string GameClass   = "OCGameApplicationWindow";
    const string DialogClass = "#32770";

    const int PollMs       = 60;   // how often we look
    const int PersistPolls = 3;    // stuck state must persist this many polls before we act

    const int  HotkeyId = 0xB10;
    const uint ModAlt = 0x0001, ModControl = 0x0002, VkF = 0x46;
    const uint WmHotkey = 0x0312;
    const uint Th32csSnapThread = 0x00000004;
    const uint PmRemove = 0x0001;

    [StructLayout(LayoutKind.Sequential)]
    struct RECT { public int left, top, right, bottom; }

    [StructLayout(LayoutKind.Sequential)]
    struct GUITHREADINFO
    {
        public uint cbSize;
        public uint flags;
        public IntPtr hwndActive;
        public IntPtr hwndFocus;
        public IntPtr hwndCapture;
        public IntPtr hwndMenuOwner;
        public IntPtr hwndMoveSize;
        public IntPtr hwndCaret;
        public RECT rcCaret;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct THREADENTRY32
    {
        public uint dwSize;
        public uint cntUsage;
        public uint th32ThreadID;
        public uint th32OwnerProcessID;
        public int tpBasePri;
        public int tpDeltaPri;
        public uint dwFlags;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct MSG
    {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public int ptX, ptY;
        public uint lPrivate;
    }

    delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int GetClassName(IntPtr hWnd, StringBuilder buf, int max);
    [DllImport("user32.dll")]
    static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")]
    static extern bool GetGUIThreadInfo(uint tid, ref GUITHREADINFO gti);
    [DllImport("user32.dll")]
    static extern bool AttachThreadInput(uint attach, uint attachTo, bool attachFlag);
    [DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
    [DllImport("user32.dll")]
    static extern bool PeekMessage(out MSG msg, IntPtr hWnd, uint min, uint max, uint remove);

    [DllImport("kernel32.dll")]
    static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
    [DllImport("kernel32.dll")]
    static extern bool Thread32First(IntPtr snapshot, ref THREADENTRY32 te);
    [DllImport("kernel32.dll")]
    static extern bool Thread32Next(IntPtr snapshot, ref THREADENTRY32 te);
    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr h);

    // ------------------------------------------------------------------ helpers

    static string ClassOf(IntPtr h)
    {
        var sb = new StringBuilder(128);
        GetClassName(h, sb, sb.Capacity);
        return sb.ToString();
    }

    static string LogPath
    {
        get
        {
            string dir = AppDomain.CurrentDomain.BaseDirectory;
            return Path.Combine(dir, "GekkouInputFix.log");
        }
    }

    static void Log(string line)
    {
        try
        {
            File.AppendAllText(LogPath,
                string.Format("[{0:yyyy-MM-dd HH:mm:ss}] {1}\r\n", DateTime.Now, line));
        }
        catch { }
    }

    static List<IntPtr> EnumByClass(string cls, bool visibleOnly, uint pid)
    {
        var found = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr l)
        {
            if (visibleOnly && !IsWindowVisible(h)) return true;
            if (ClassOf(h) != cls) return true;
            if (pid != 0)
            {
                uint p;
                GetWindowThreadProcessId(h, out p);
                if (p != pid) return true;
            }
            found.Add(h);
            return true;
        }, IntPtr.Zero);
        return found;
    }

    static bool FindGame(out IntPtr hwnd, out uint pid, out uint tid)
    {
        hwnd = IntPtr.Zero; pid = 0; tid = 0;
        var wins = EnumByClass(GameClass, true, 0);
        if (wins.Count == 0) return false;
        hwnd = wins[0];
        uint p;
        tid = GetWindowThreadProcessId(hwnd, out p);
        pid = p;
        return tid != 0;
    }

    static List<uint> ThreadsOf(uint pid)
    {
        var list = new List<uint>();
        IntPtr snap = CreateToolhelp32Snapshot(Th32csSnapThread, 0);
        if (snap == (IntPtr)(-1)) return list;
        try
        {
            var te = new THREADENTRY32();
            te.dwSize = (uint)Marshal.SizeOf(typeof(THREADENTRY32));
            if (Thread32First(snap, ref te))
            {
                do
                {
                    if (te.th32OwnerProcessID == pid) list.Add(te.th32ThreadID);
                } while (Thread32Next(snap, ref te));
            }
        }
        finally { CloseHandle(snap); }
        return list;
    }

    static bool GuiInfo(uint tid, out GUITHREADINFO gti)
    {
        gti = new GUITHREADINFO();
        gti.cbSize = (uint)Marshal.SizeOf(typeof(GUITHREADINFO));
        return GetGUIThreadInfo(tid, ref gti);
    }

    // ------------------------------------------------------------- the repair

    // Detach every thread of `pid` whose input queue is stuck to the game thread's
    // queue while that queue's active window is the game window itself.
    static int Repair(IntPtr hwnd, uint pid, uint mainTid)
    {
        GUITHREADINFO main;
        if (!GuiInfo(mainTid, out main)) return 0;
        if (main.hwndActive == IntPtr.Zero || main.hwndActive != hwnd) return 0;
        // a genuinely open dialog owns a different active window; belt and braces:
        if (EnumByClass(DialogClass, true, pid).Count > 0) return 0;

        int undone = 0;
        foreach (uint tid in ThreadsOf(pid))
        {
            if (tid == mainTid) continue;
            GUITHREADINFO g;
            if (!GuiInfo(tid, out g)) continue;
            if (g.hwndActive != main.hwndActive) continue;

            bool ok = AttachThreadInput(tid, mainTid, false);
            if (!ok) ok = AttachThreadInput(mainTid, tid, false);
            if (ok)
            {
                undone++;
                Log(string.Format(
                    "repaired: detached input queue of thread {0} from game thread {1} (hwnd 0x{2:X})",
                    tid, mainTid, hwnd.ToInt64()));
            }
        }
        return undone;
    }

    static bool HotkeyPressed()
    {
        bool pressed = false;
        MSG msg;
        while (PeekMessage(out msg, IntPtr.Zero, 0, 0, PmRemove))
        {
            if (msg.message == WmHotkey && (int)msg.wParam.ToUInt64() == HotkeyId) pressed = true;
        }
        return pressed;
    }

    static void Main(string[] args)
    {
        bool repairNow = false;
        foreach (string a in args)
            if (a == "--repair-now") repairNow = true;

        IntPtr hwnd; uint pid, tid;

        if (repairNow)
        {
            if (!FindGame(out hwnd, out pid, out tid)) { Log("--repair-now: game not running"); return; }
            SetForegroundWindow(hwnd);
            Thread.Sleep(120);
            int n = Repair(hwnd, pid, tid);
            Log(string.Format("--repair-now: {0} attachment(s) undone", n));
            return;
        }

        RegisterHotKey(IntPtr.Zero, HotkeyId, ModControl | ModAlt, VkF);
        Log(string.Format("GekkouInputFix started (Ctrl+Alt+F forces a repair, log: {0})", LogPath));

        int streak = 0;
        while (true)
        {
            if (HotkeyPressed())
            {
                if (FindGame(out hwnd, out pid, out tid))
                {
                    SetForegroundWindow(hwnd);
                    Thread.Sleep(120);
                    int n = Repair(hwnd, pid, tid);
                    Log(string.Format("hotkey: {0} attachment(s) undone", n));
                }
            }

            if (FindGame(out hwnd, out pid, out tid) && IsWindow(hwnd))
            {
                GUITHREADINFO main;
                int stuck = 0;
                if (GuiInfo(tid, out main) && main.hwndActive == hwnd)
                {
                    foreach (uint t in ThreadsOf(pid))
                    {
                        if (t == tid) continue;
                        GUITHREADINFO g;
                        if (GuiInfo(t, out g) && g.hwndActive == hwnd) stuck++;
                    }
                }

                if (stuck > 0)
                {
                    streak++;
                    if (streak >= PersistPolls)
                    {
                        if (Repair(hwnd, pid, tid) > 0) streak = 0;
                    }
                }
                else streak = 0;
            }
            else streak = 0;

            Thread.Sleep(PollMs);
        }
    }
}

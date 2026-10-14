param([int]$TargetProcessId, [ValidateSet('state', 'close', 'shortcut')] [string]$Action = 'state')
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class GeneratedWindow {
    public delegate bool EnumProc(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr window, uint message, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint from, uint to, bool attach);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr CreateWindowEx(uint ex, string cls, string title, uint style, int x, int y, int w, int h, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern bool DestroyWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, System.Text.StringBuilder text, int size);
    public static IntPtr Find(uint pid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows((window, data) => {
            uint owner; GetWindowThreadProcessId(window, out owner);
            var title = new System.Text.StringBuilder(256); GetWindowText(window, title, 256);
            if (owner == pid && title.ToString() == "Vault Unified generated test") { found = window; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static void Shortcut() {
        var window = CreateWindowEx(0, "STATIC", "Vault generated shortcut target", 0x00cf0000, 20, 20, 320, 150, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (window == IntPtr.Zero) throw new Exception("Could not create isolated shortcut target");
        try {
            uint owner;
            var foregroundThread = GetWindowThreadProcessId(GetForegroundWindow(), out owner);
            var currentThread = GetCurrentThreadId();
            var attached = foregroundThread != 0 && foregroundThread != currentThread && AttachThreadInput(currentThread, foregroundThread, true);
            try { ShowWindow(window, 5); SetForegroundWindow(window); }
            finally { if (attached) AttachThreadInput(currentThread, foregroundThread, false); }
            System.Threading.Thread.Sleep(200);
            if (GetForegroundWindow() != window) throw new Exception("Isolated shortcut target could not take focus");
            try {
                keybd_event(0x11, 0, 0, UIntPtr.Zero); keybd_event(0x10, 0, 0, UIntPtr.Zero); keybd_event(0x20, 0, 0, UIntPtr.Zero);
            } finally {
                keybd_event(0x20, 0, 2, UIntPtr.Zero); keybd_event(0x10, 0, 2, UIntPtr.Zero); keybd_event(0x11, 0, 2, UIntPtr.Zero);
            }
            System.Threading.Thread.Sleep(200);
        } finally { DestroyWindow(window); }
    }
}
'@
$window = [GeneratedWindow]::Find($TargetProcessId)
if ($window -eq [IntPtr]::Zero) { throw 'Generated application window was not found for this process' }
if ($Action -eq 'close') { [GeneratedWindow]::PostMessage($window, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
if ($Action -eq 'shortcut') { [GeneratedWindow]::Shortcut() }
@{ visible = [GeneratedWindow]::IsWindowVisible($window) } | ConvertTo-Json -Compress

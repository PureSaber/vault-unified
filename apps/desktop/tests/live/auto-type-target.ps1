# Isolated native test window. All field data travels through redirected pipes.
$ErrorActionPreference = 'Stop'
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing,System.Web.Extensions -TypeDefinition @'
using System;
using System.Drawing;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
public static class GeneratedTypeTarget {
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint from, uint to, bool attach);
    static void Focus(Form form, Control field) {
        uint owner; var foreign = GetWindowThreadProcessId(GetForegroundWindow(), out owner);
        var own = GetCurrentThreadId();
        bool attached = foreign != 0 && foreign != own && AttachThreadInput(own, foreign, true);
        try { form.Show(); form.Activate(); field.Focus(); SetForegroundWindow(form.Handle); }
        finally { if (attached) AttachThreadInput(own, foreign, false); }
    }
    public static void Run() {
        // Redirected PowerShell pipes inherit the machine's legacy code page.
        // Pin UTF-8 so Unicode text typed correctly is also compared correctly.
        Console.InputEncoding = new System.Text.UTF8Encoding(false);
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        Application.EnableVisualStyles();
        var form = new Form { Text="Vault generated auto-type target", Size=new Size(420,240), StartPosition=FormStartPosition.Manual, Location=new Point(30,30) };
        var user = new TextBox { Top=30, Left=20, Width=340, TabIndex=0 };
        var pass = new TextBox { Top=70, Left=20, Width=340, TabIndex=1, UseSystemPasswordChar=true };
        var button = new Button { Top=115, Left=20, Width=150, Text="Generated submit", TabIndex=2 };
        form.Controls.AddRange(new Control[] { user, pass, button }); form.AcceptButton=button;
        int submissions=0; bool divert=false;
        button.Click += (s,e) => submissions++;
        var other = new Form { Text="Vault generated distraction", Size=new Size(400,180), StartPosition=FormStartPosition.Manual, Location=new Point(60,300) };
        var sink = new TextBox { Top=20, Left=20, Width=300 }; other.Controls.Add(sink);
        pass.TextChanged += (s,e) => { if (divert && pass.TextLength >= 3) { divert=false; Focus(other,sink); } };
        var json = new JavaScriptSerializer();
        var commands = new System.Collections.Concurrent.BlockingCollection<string>();
        var reader = new System.Threading.Thread(() => { string line; while ((line=Console.ReadLine()) != null) commands.Add(line); commands.Add("exit"); });
        reader.IsBackground=true; reader.Start();
        var timer = new Timer { Interval=20 };
        timer.Tick += (s,e) => {
            string command; if (!commands.TryTake(out command)) return;
            if (command == "exit") { timer.Stop(); other.Close(); form.Close(); return; }
            if (command == "focus" || command == "divert") {
                divert=false; user.Clear(); pass.Clear(); sink.Clear(); submissions=0;
                other.Hide(); Focus(form,user); divert=command == "divert";
                Console.WriteLine(json.Serialize(new { focused=GetForegroundWindow() == form.Handle }));
            } else if (command == "read") {
                Console.WriteLine(json.Serialize(new { username=user.Text, password=pass.Text, other=sink.Text, submissions=submissions, field=user.Focused ? "username" : pass.Focused ? "password" : button.Focused ? "button" : "none", focused=GetForegroundWindow() == form.Handle }));
            } else if (command == "rename") {
                form.Text="Vault generated changed target"; Console.WriteLine("{\"renamed\":true}");
            }
        };
        form.Shown += (s,e) => { timer.Start(); Console.WriteLine(json.Serialize(new { ready=true, unicode="\u751f\u6210" })); };
        Application.Run(form); timer.Dispose(); other.Dispose(); form.Dispose();
    }
}
'@
[GeneratedTypeTarget]::Run()

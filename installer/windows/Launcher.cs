// VSubStudio.exe — trình khởi động VSub Studio trên Windows.
// Đặt cạnh run.py (thư mục mã nguồn). Lần đầu chạy: cài thư viện bằng uv sync; sau đó khởi động
// server FastAPI (uv run python run.py), chờ server sẵn sàng rồi mở trình duyệt.
// Biên dịch bằng csc của .NET Framework 4 (có sẵn trên Windows 10/11) — xem build_exe.ps1.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: System.Reflection.AssemblyTitle("VSub Studio")]
[assembly: System.Reflection.AssemblyProduct("VSub Studio")]
[assembly: System.Reflection.AssemblyDescription("Lồng tiếng video tự động đa nhân vật")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.0.0")]

namespace VSubStudio
{
    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string dir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            foreach (string a in args)
            {
                if (a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase)) return Uninstall.Run(dir);
            }
            if (!File.Exists(Path.Combine(dir, "run.py")))
            {
                MessageBox.Show("Không thấy run.py cạnh VSubStudio.exe.\nHãy đặt file exe trong thư mục mã nguồn VSub Studio.",
                    "VSub Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            bool created;
            using (var mutex = new Mutex(true, "VSubStudioLauncher_" + dir.GetHashCode().ToString("x"), out created))
            {
                if (!created)
                {
                    MessageBox.Show("VSub Studio đang chạy rồi (xem cửa sổ VSub Studio trên thanh tác vụ).",
                        "VSub Studio", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return 0;
                }
                Application.Run(new MainForm(dir));
            }
            return 0;
        }
    }

    class MainForm : Form
    {
        // Gói "đầy đủ" khớp hướng dẫn cài trong báo cáo (Phụ lục 1); gói "gọn" bỏ các nhóm cần torch.
        static readonly string FULL = "--extra cuda --extra ai --extra offline --extra tts --extra clone --extra diarize --extra separate";
        static readonly string LIGHT = "--extra cuda --extra ai --extra tts";

        static readonly Color BG = Color.FromArgb(0xFA, 0xF8, 0xF3);
        static readonly Color INK = Color.FromArgb(0x1C, 0x19, 0x17);
        static readonly Color MUTED = Color.FromArgb(0x57, 0x53, 0x4E);
        static readonly Color ACCENT = Color.FromArgb(0xA1, 0x62, 0x07);

        readonly string dir;
        string uv;
        int port;
        bool lan;
        bool opened;
        bool closing;
        Process proc;
        Label status, hint;
        TextBox log;
        Button openBtn, stopBtn;
        CheckBox lanBox;

        public MainForm(string dir)
        {
            this.dir = dir;
            Text = "VSub Studio";
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            BackColor = BG;
            Font = new Font("Segoe UI", 10f);
            ClientSize = new Size(720, 520);
            MinimumSize = new Size(560, 420);
            StartPosition = FormStartPosition.CenterScreen;

            var title = new Label { Text = "VSub Studio", Font = new Font("Segoe UI Semibold", 20f), ForeColor = INK, AutoSize = true, Location = new Point(20, 14) };
            var sub = new Label { Text = "Lồng tiếng video tự động đa nhân vật", ForeColor = MUTED, AutoSize = true, Location = new Point(23, 54) };
            status = new Label { Text = "Đang chuẩn bị…", Font = new Font("Segoe UI Semibold", 11f), ForeColor = ACCENT, AutoSize = true, Location = new Point(23, 86) };
            openBtn = MakeButton("Mở VSub Studio", true);
            openBtn.Location = new Point(22, 118);
            openBtn.Enabled = false;
            openBtn.Click += delegate { OpenBrowser(); };
            stopBtn = MakeButton("Dừng và thoát", false);
            stopBtn.Location = new Point(212, 118);
            stopBtn.Click += delegate { Close(); };
            lanBox = new CheckBox { Text = "Cho điện thoại cùng Wi-Fi kết nối", ForeColor = INK, AutoSize = true, Location = new Point(404, 126) };
            lanBox.CheckedChanged += delegate { lan = lanBox.Checked; Restart(); };
            hint = new Label { ForeColor = MUTED, AutoSize = false, Location = new Point(23, 168), Size = new Size(680, 40), Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right };
            log = new TextBox
            {
                Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, WordWrap = true,
                BackColor = Color.FromArgb(0xF1, 0xEC, 0xE0), ForeColor = INK, BorderStyle = BorderStyle.None,
                Font = new Font("Consolas", 9f), Location = new Point(22, 214), Size = new Size(676, 290),
                Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
            };
            Controls.AddRange(new Control[] { title, sub, status, openBtn, stopBtn, lanBox, hint, log });
            Shown += delegate { new Thread(Boot) { IsBackground = true }.Start(); };
            FormClosing += delegate { closing = true; StopServer(); };
        }

        Button MakeButton(string text, bool primary)
        {
            var b = new Button
            {
                Text = text, Size = new Size(176, 40), FlatStyle = FlatStyle.Flat, Cursor = Cursors.Hand,
                BackColor = primary ? INK : Color.White, ForeColor = primary ? BG : INK,
                Font = new Font("Segoe UI Semibold", 10f)
            };
            b.FlatAppearance.BorderColor = primary ? INK : Color.FromArgb(0xC8, 0xC3, 0xB9);
            return b;
        }

        // ------------------------------------------------------------ luồng khởi động

        void Boot()
        {
            uv = FindUv();
            if (uv == null)
            {
                SetStatus("Chưa có uv — công cụ cài Python và thư viện.");
                Log("Cài uv bằng lệnh sau trong PowerShell rồi mở lại VSubStudio.exe:");
                Log("  powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\"");
                Log("(Bộ cài VSubStudio_Setup.exe đã kèm sẵn uv trong thư mục tools.)");
                return;
            }
            Log("uv: " + uv);
            if (!Directory.Exists(Path.Combine(dir, ".venv")))
            {
                string extras = null;
                Invoke((MethodInvoker)delegate { extras = AskExtras(); });
                if (extras == null) { Invoke((MethodInvoker)Close); return; }
                SetStatus("Lần đầu chạy: đang cài Python và thư viện (có thể mất 5–30 phút)…");
                Log("> uv sync " + extras);
                int code = RunAndWait("sync " + extras);
                if (code != 0)
                {
                    SetStatus("Cài thư viện thất bại (mã " + code + "). Xem nhật ký bên dưới.");
                    try { Directory.Delete(Path.Combine(dir, ".venv"), true); } catch { }
                    return;
                }
                Log("Cài xong.");
            }
            StartServer();
        }

        string AskExtras()
        {
            var r = MessageBox.Show(this,
                "Lần đầu chạy cần tải Python và các thư viện.\n\n" +
                "Có  = bản ĐẦY ĐỦ (~6 GB): nhận dạng, dịch Google/AI/NLLB ngoại tuyến, lồng tiếng, nhân bản giọng, tách vai, tách nhạc nền.\n\n" +
                "Không = bản GỌN (~1,5 GB): nhận dạng, dịch Google/AI, lồng tiếng giọng có sẵn.\n\n" +
                "Huỷ = thoát.",
                "VSub Studio — chọn gói cài", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question);
            if (r == DialogResult.Yes) return FULL;
            if (r == DialogResult.No) return LIGHT;
            return null;
        }

        void StartServer()
        {
            port = FreePort(8000);
            string host = lan ? "0.0.0.0" : "127.0.0.1";
            SetStatus("Đang khởi động server…");
            Log("> uv run python run.py --host " + host + " --port " + port);
            proc = Spawn("run --no-sync python run.py --no-browser --host " + host + " --port " + port);
            if (proc == null) { SetStatus("Không chạy được uv."); return; }
            var p = proc;
            string url = "http://127.0.0.1:" + port + "/";
            for (int i = 0; i < 360 && !closing; i++)
            {
                if (p.HasExited)
                {
                    if (p == proc) SetStatus("Server dừng bất ngờ (mã " + p.ExitCode + "). Xem nhật ký bên dưới.");
                    return;
                }
                if (Ping(url))
                {
                    if (p != proc) return;
                    SetStatus("Đang chạy tại " + url);
                    Invoke((MethodInvoker)delegate
                    {
                        openBtn.Enabled = true;
                        hint.Text = lan
                            ? "Điện thoại: mở app VSub Studio (Android) hoặc trình duyệt, nhập " + string.Join("  hoặc  ", LanAddresses()) + "\nWindows hỏi tường lửa cho python thì chọn Allow. Chỉ bật trong mạng tin cậy — hệ thống không có mật khẩu."
                            : "Đóng cửa sổ này sẽ dừng VSub Studio.";
                    });
                    if (!opened) { opened = true; OpenBrowser(); }
                    return;
                }
                Thread.Sleep(500);
            }
            if (!closing) SetStatus("Server chưa phản hồi sau 3 phút. Xem nhật ký bên dưới.");
        }

        void Restart()
        {
            if (uv == null || proc == null) return;
            openBtn.Enabled = false;
            new Thread(delegate () { StopServer(); StartServer(); }) { IsBackground = true }.Start();
        }

        // ------------------------------------------------------------ tiến trình

        Process Spawn(string args)
        {
            var psi = new ProcessStartInfo(uv, args)
            {
                WorkingDirectory = dir, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            psi.EnvironmentVariables["PYTHONUTF8"] = "1";
            psi.EnvironmentVariables["NO_COLOR"] = "1";
            psi.EnvironmentVariables["UV_NO_PROGRESS"] = "1";
            try
            {
                var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
                p.OutputDataReceived += (s, e) => { if (e.Data != null) Log(e.Data); };
                p.ErrorDataReceived += (s, e) => { if (e.Data != null) Log(e.Data); };
                p.Start();
                p.BeginOutputReadLine();
                p.BeginErrorReadLine();
                return p;
            }
            catch (Exception ex)
            {
                Log("Lỗi: " + ex.Message);
                return null;
            }
        }

        int RunAndWait(string args)
        {
            var p = Spawn(args);
            if (p == null) return -1;
            proc = p;
            p.WaitForExit();
            proc = null;
            return p.ExitCode;
        }

        void StopServer()
        {
            var p = proc;
            proc = null;
            if (p == null) return;
            try
            {
                if (!p.HasExited)
                {
                    // uv chạy python ở tiến trình con → dừng cả cây tiến trình
                    var k = Process.Start(new ProcessStartInfo("taskkill", "/T /F /PID " + p.Id) { CreateNoWindow = true, UseShellExecute = false });
                    k.WaitForExit(5000);
                }
            }
            catch { }
        }

        // ------------------------------------------------------------ tiện ích

        string FindUv()
        {
            var cands = new List<string> { Path.Combine(dir, "tools", "uv.exe") };
            foreach (string d in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                if (d.Trim().Length > 0) cands.Add(Path.Combine(d.Trim().Trim('"'), "uv.exe"));
            }
            cands.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "bin", "uv.exe"));
            cands.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".cargo", "bin", "uv.exe"));
            foreach (string c in cands)
            {
                try { if (File.Exists(c)) return c; } catch { }
            }
            return null;
        }

        static int FreePort(int start)
        {
            for (int p = start; p < start + 50; p++)
            {
                try
                {
                    // Dò trên 127.0.0.1: mở cổng trên mọi mạng sẽ làm tường lửa Windows hỏi quyền
                    var l = new TcpListener(IPAddress.Loopback, p);
                    l.Start();
                    l.Stop();
                    return p;
                }
                catch { }
            }
            return start;
        }

        static bool Ping(string url)
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = 1500;
                req.Proxy = null;
                using (var res = (HttpWebResponse)req.GetResponse()) return (int)res.StatusCode < 500;
            }
            catch { return false; }
        }

        List<string> LanAddresses()
        {
            var list = new List<string>();
            foreach (var ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (ni.OperationalStatus != OperationalStatus.Up || ni.NetworkInterfaceType == NetworkInterfaceType.Loopback) continue;
                if (ni.GetIPProperties().GatewayAddresses.Count == 0) continue;
                foreach (var a in ni.GetIPProperties().UnicastAddresses)
                {
                    if (a.Address.AddressFamily == AddressFamily.InterNetwork) list.Add(a.Address + ":" + port);
                }
            }
            if (list.Count == 0) list.Add("<IP máy tính>:" + port);
            return list;
        }

        void OpenBrowser()
        {
            try { Process.Start("http://127.0.0.1:" + port + "/"); } catch { }
        }

        void SetStatus(string s)
        {
            if (IsDisposed) return;
            try { BeginInvoke((MethodInvoker)delegate { status.Text = s; }); } catch { }
        }

        void Log(string s)
        {
            if (IsDisposed || closing) return;
            try
            {
                BeginInvoke((MethodInvoker)delegate
                {
                    if (log.TextLength > 200000) log.Text = log.Text.Substring(100000);
                    log.AppendText(s + Environment.NewLine);
                });
            }
            catch { }
        }
    }

    // Gỡ cài đặt (bộ cài ghi lệnh "VSubStudio.exe /uninstall" vào mục Ứng dụng của Windows)
    static class Uninstall
    {
        public const string KEY = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\VSubStudio";

        public static int Run(string dir)
        {
            // Chỉ gỡ thư mục do bộ cài tạo ra (có tệp đánh dấu) — không bao giờ xoá thư mục mã nguồn đang phát triển
            if (!File.Exists(Path.Combine(dir, ".vsub_installed")))
            {
                MessageBox.Show("Thư mục này không do bộ cài VSub Studio tạo ra nên không gỡ tự động:\n" + dir,
                    "Gỡ cài đặt VSub Studio", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 1;
            }
            var r = MessageBox.Show(
                "Gỡ VSub Studio khỏi máy?\n\nThư mục sẽ bị xoá: " + dir + "\n(gồm cả dự án phim, video và mô hình đã tải trong thư mục data)",
                "Gỡ cài đặt VSub Studio", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (r != DialogResult.Yes) return 1;
            foreach (var p in Process.GetProcesses())
            {
                try
                {
                    if (p.Id != Process.GetCurrentProcess().Id && p.MainModule.FileName.StartsWith(dir, StringComparison.OrdinalIgnoreCase)) p.Kill();
                }
                catch { }
            }
            string[] links = {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "VSub Studio.lnk"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "VSub Studio.lnk"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Gỡ VSub Studio.lnk"),
            };
            foreach (string l in links) { try { File.Delete(l); } catch { } }
            try { Registry.CurrentUser.DeleteSubKeyTree(KEY, false); } catch { }
            // Không xoá được thư mục đang chứa chính exe này → nhờ cmd xoá sau khi thoát
            Process.Start(new ProcessStartInfo("cmd.exe", "/c timeout /t 2 /nobreak >nul & rmdir /s /q \"" + dir + "\"")
            {
                CreateNoWindow = true, UseShellExecute = false, WorkingDirectory = Path.GetTempPath()
            });
            MessageBox.Show("Đã gỡ VSub Studio.", "Gỡ cài đặt VSub Studio");
            return 0;
        }
    }
}

// VSubStudio_Setup.exe — bộ cài VSub Studio cho Windows (không cần quyền quản trị).
// Gói mã nguồn + uv.exe + VSubStudio.exe nằm trong tài nguyên nhúng "payload.zip" (build_exe.ps1 tạo ra).
// Cài vào %LOCALAPPDATA%\Programs\VSubStudio (đổi được), tạo lối tắt, đăng ký mục gỡ cài đặt trong
// Cài đặt → Ứng dụng của Windows. Thư viện Python (vài GB) được tải ở lần chạy đầu bằng VSubStudio.exe.
//   VSubStudio_Setup.exe [/S] [/D=<thư mục>] [/noshortcut] [/noreg]
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Cài đặt VSub Studio")]
[assembly: AssemblyProduct("VSub Studio")]
[assembly: AssemblyDescription("Bộ cài VSub Studio — lồng tiếng video tự động đa nhân vật")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace VSubStudioSetup
{
    static class Installer
    {
        public const string KEY = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\VSubStudio";
        public const string EXE = "VSubStudio.exe";

        public static string DefaultDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "VSubStudio");
        }

        /// Giải nén gói vào dir; giữ nguyên data\ và .venv\ nếu đã cài trước đó (cập nhật phiên bản).
        /// Trả về cảnh báo (null nếu không có) — lỗi tạo lối tắt không làm hỏng cả lần cài.
        public static string Install(string dir, bool shortcut, bool reg, Action<int, string> progress)
        {
            string warn = null;
            Directory.CreateDirectory(dir);
            using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
            {
                int n = zip.Entries.Count, i = 0;
                long total = 0;
                foreach (ZipArchiveEntry e in zip.Entries)
                {
                    i++;
                    string target = Path.GetFullPath(Path.Combine(dir, e.FullName.Replace('/', '\\')));
                    if (!target.StartsWith(Path.GetFullPath(dir), StringComparison.OrdinalIgnoreCase)) continue;
                    if (e.FullName.EndsWith("/")) { Directory.CreateDirectory(target); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    using (Stream src = e.Open())
                    using (FileStream dst = File.Create(target)) src.CopyTo(dst);
                    total += e.Length;
                    if (i % 10 == 0 || i == n) progress(i * 90 / n, e.FullName);
                }
                File.WriteAllText(Path.Combine(dir, ".vsub_installed"), "Cài bằng VSubStudio_Setup.exe " + DateTime.Now.ToString("s"));
                string exe = Path.Combine(dir, EXE);
                if (shortcut)
                {
                    progress(94, "Tạo lối tắt…");
                    string[,] links = {
                        { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "VSub Studio.lnk"), "" },
                        { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "VSub Studio.lnk"), "" },
                        { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Gỡ VSub Studio.lnk"), "/uninstall" },
                    };
                    for (int k = 0; k < links.GetLength(0); k++)
                    {
                        try { Link(links[k, 0], exe, links[k, 1], dir); }
                        catch (Exception ex) { warn = "không tạo được lối tắt " + Path.GetFileName(links[k, 0]) + " (" + ex.Message + ")"; }
                    }
                }
                if (reg)
                {
                    progress(97, "Đăng ký mục gỡ cài đặt…");
                    using (RegistryKey k = Registry.CurrentUser.CreateSubKey(KEY))
                    {
                        k.SetValue("DisplayName", "VSub Studio");
                        k.SetValue("DisplayVersion", "1.0");
                        k.SetValue("Publisher", "VSub Studio");
                        k.SetValue("InstallLocation", dir);
                        k.SetValue("DisplayIcon", exe);
                        k.SetValue("UninstallString", "\"" + exe + "\" /uninstall");
                        k.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                        k.SetValue("EstimatedSize", (int)(total / 1024), RegistryValueKind.DWord);
                    }
                }
                progress(100, "Xong.");
            }
            return warn;
        }

        // Tạo lối tắt .lnk qua IShellLinkW (COM có sẵn của Windows, nhận Unicode). Không dùng WScript.Shell: nó lưu
        // đường dẫn theo bảng mã ANSI nên tên có chữ Việt như "Gỡ VSub Studio.lnk" làm Save() báo lỗi.
        static void Link(string lnk, string target, string args, string workdir)
        {
            var link = (IShellLinkW)new ShellLink();
            link.SetPath(target);
            link.SetArguments(args);
            link.SetWorkingDirectory(workdir);
            link.SetIconLocation(target, 0);
            link.SetDescription("VSub Studio — lồng tiếng video tự động");
            ((IPersistFile)link).Save(lnk, false);
            Marshal.FinalReleaseComObject(link);
        }
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class ShellLink { }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
    interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cch, IntPtr pfd, int fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cch);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cch);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cch);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cch, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, int dwReserved);
        void Resolve(IntPtr hwnd, int fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            bool silent = false, shortcut = true, reg = true;
            string dir = Installer.DefaultDir();
            foreach (string a in args)
            {
                if (a.Equals("/S", StringComparison.OrdinalIgnoreCase)) silent = true;
                else if (a.StartsWith("/D=", StringComparison.OrdinalIgnoreCase)) dir = a.Substring(3).Trim('"');
                else if (a.Equals("/noshortcut", StringComparison.OrdinalIgnoreCase)) shortcut = false;
                else if (a.Equals("/noreg", StringComparison.OrdinalIgnoreCase)) reg = false;
            }
            if (silent)
            {
                try
                {
                    string w = Installer.Install(dir, shortcut, reg, (p, m) => { });
                    if (w != null) Console.Error.WriteLine("Cảnh báo: " + w);
                    return 0;
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine(ex);
                    return 1;
                }
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm(dir));
            return 0;
        }
    }

    class SetupForm : Form
    {
        static readonly Color BG = Color.FromArgb(0xFA, 0xF8, 0xF3);
        static readonly Color INK = Color.FromArgb(0x1C, 0x19, 0x17);
        static readonly Color MUTED = Color.FromArgb(0x57, 0x53, 0x4E);
        static readonly Color ACCENT = Color.FromArgb(0xA1, 0x62, 0x07);

        TextBox path;
        CheckBox desk, runNow;
        Button go, browse;
        ProgressBar bar;
        Label status;
        bool done;

        public SetupForm(string dir)
        {
            Text = "Cài đặt VSub Studio";
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
            BackColor = BG;
            Font = new Font("Segoe UI", 10f);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            ClientSize = new Size(600, 450);
            StartPosition = FormStartPosition.CenterScreen;

            var title = new Label { Text = "VSub Studio", Font = new Font("Segoe UI Semibold", 22f), ForeColor = INK, AutoSize = true, Location = new Point(24, 16) };
            var sub = new Label { Text = "Lồng tiếng video tự động đa nhân vật — phiên bản 1.0", ForeColor = MUTED, AutoSize = true, Location = new Point(27, 60) };
            var info = new Label
            {
                ForeColor = INK, Location = new Point(27, 96), Size = new Size(550, 126),
                Text = "Bộ cài chép mã nguồn VSub Studio và công cụ uv vào máy, tạo lối tắt trên màn hình nền.\n\n" +
                       "Lần đầu mở VSub Studio, chương trình tự tải Python và thư viện AI (khoảng 1,5–6 GB, cần Internet). " +
                       "Nên có card đồ hoạ NVIDIA; không có vẫn chạy được nhưng chậm hơn nhiều."
            };
            var lbl = new Label { Text = "Thư mục cài đặt", ForeColor = INK, Font = new Font("Segoe UI Semibold", 10f), AutoSize = true, Location = new Point(27, 232) };
            path = new TextBox { Text = dir, Location = new Point(28, 258), Size = new Size(440, 26) };
            browse = new Button { Text = "Chọn…", Location = new Point(478, 256), Size = new Size(96, 30), FlatStyle = FlatStyle.Flat, BackColor = Color.White };
            browse.Click += delegate
            {
                using (var d = new FolderBrowserDialog { Description = "Chọn thư mục cài VSub Studio" })
                {
                    if (d.ShowDialog(this) == DialogResult.OK) path.Text = Path.Combine(d.SelectedPath, "VSubStudio");
                }
            };
            desk = new CheckBox { Text = "Tạo lối tắt trên màn hình nền và menu Start", Checked = true, AutoSize = true, ForeColor = INK, Location = new Point(28, 298) };
            runNow = new CheckBox { Text = "Mở VSub Studio sau khi cài", Checked = true, AutoSize = true, ForeColor = INK, Location = new Point(28, 324) };
            bar = new ProgressBar { Location = new Point(28, 362), Size = new Size(546, 10) };
            status = new Label { ForeColor = MUTED, AutoSize = false, Location = new Point(27, 378), Size = new Size(400, 40) };
            go = new Button
            {
                Text = "Cài đặt", Location = new Point(434, 392), Size = new Size(140, 42), FlatStyle = FlatStyle.Flat,
                BackColor = INK, ForeColor = BG, Font = new Font("Segoe UI Semibold", 11f)
            };
            go.FlatAppearance.BorderColor = INK;
            go.Click += delegate { if (done) Finish(); else Start(); };
            Controls.AddRange(new Control[] { title, sub, info, lbl, path, browse, desk, runNow, bar, status, go });
            AcceptButton = go;
        }

        void Start()
        {
            string dir = path.Text.Trim();
            if (dir.Length < 4 || !Path.IsPathRooted(dir))
            {
                MessageBox.Show(this, "Thư mục cài đặt không hợp lệ.", Text);
                return;
            }
            dir = Path.GetFullPath(dir);
            if (Directory.Exists(dir) && Directory.GetFileSystemEntries(dir).Length > 0
                && !File.Exists(Path.Combine(dir, ".vsub_installed")))
            {
                MessageBox.Show(this, "Thư mục đã có tệp khác. Hãy chọn thư mục trống hoặc thư mục VSub Studio đã cài trước đó.", Text);
                return;
            }
            go.Enabled = browse.Enabled = path.Enabled = desk.Enabled = false;
            bool sc = desk.Checked;
            var th = new Thread(delegate ()
            {
                try
                {
                    string w = Installer.Install(dir, sc, true, (p, m) => BeginInvoke((MethodInvoker)delegate { bar.Value = p; status.Text = m; }));
                    BeginInvoke((MethodInvoker)delegate
                    {
                        done = true;
                        path.Text = dir;
                        status.Text = "Đã cài vào " + dir + (w != null ? "\n(" + w + ")" : "");
                        status.ForeColor = ACCENT;
                        go.Text = "Hoàn tất";
                        go.Enabled = true;
                    });
                }
                catch (Exception ex)
                {
                    BeginInvoke((MethodInvoker)delegate
                    {
                        status.Text = "Lỗi: " + ex.Message;
                        status.ForeColor = Color.FromArgb(0xB4, 0x23, 0x18);
                        go.Enabled = browse.Enabled = path.Enabled = desk.Enabled = true;
                    });
                }
            }) { IsBackground = true };
            th.SetApartmentState(ApartmentState.STA);   // lối tắt tạo qua COM của Shell
            th.Start();
        }

        void Finish()
        {
            if (runNow.Checked)
            {
                string exe = Path.Combine(path.Text, Installer.EXE);
                try { Process.Start(new ProcessStartInfo(exe) { WorkingDirectory = path.Text }); } catch { }
            }
            Close();
        }
    }
}

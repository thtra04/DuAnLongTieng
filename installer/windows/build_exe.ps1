# Dựng VSubStudio.exe (trình khởi động) và VSubStudio_Setup.exe (bộ cài) bằng csc của .NET Framework 4,
# có sẵn trên Windows 10/11 — không cần cài Visual Studio.
#   powershell -ExecutionPolicy Bypass -File installer\windows\build_exe.ps1
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = (Resolve-Path "$here\..\..").Path
$dist = Join-Path $here 'dist'
New-Item -ItemType Directory -Force $dist | Out-Null
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$fw = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319"
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = 'uv'; $pyArgs = @('run', '--no-sync', 'python') } else { $pyArgs = @() }

$ico = Join-Path $here 'vsub.ico'
if (-not (Test-Path $ico)) { & $py @pyArgs "$here\make_payload.py" icon $ico }

$launcher = Join-Path $dist 'VSubStudio.exe'
& $csc /nologo /codepage:65001 /optimize+ /target:winexe /platform:anycpu "/win32icon:$ico" "/out:$launcher" `
    /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll "$here\Launcher.cs"
if ($LASTEXITCODE -ne 0) { throw 'Biên dịch VSubStudio.exe lỗi' }

$uv = (Get-Command uv).Source
$payload = Join-Path $dist 'payload.zip'
& $py @pyArgs "$here\make_payload.py" payload $payload $launcher $uv
if ($LASTEXITCODE -ne 0) { throw 'Tạo payload.zip lỗi' }

$setup = Join-Path $dist 'VSubStudio_Setup.exe'
& $csc /nologo /codepage:65001 /optimize+ /target:winexe /platform:anycpu "/win32icon:$ico" "/out:$setup" `
    "/resource:$payload,payload.zip" /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll `
    "/r:$fw\System.IO.Compression.dll" "$here\Setup.cs"
if ($LASTEXITCODE -ne 0) { throw 'Biên dịch VSubStudio_Setup.exe lỗi' }
Remove-Item $payload

# Bản để bấm đúp ngay trong thư mục mã nguồn (đã có trong .gitignore)
Copy-Item $launcher (Join-Path $root 'VSubStudio.exe') -Force
Get-ChildItem $dist | ForEach-Object { '{0}  {1:N1} MB' -f $_.Name, ($_.Length / 1MB) }

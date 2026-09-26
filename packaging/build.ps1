param([switch]$DevelopmentBuild, [switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Create .venv and install requirements-dev.txt first. See README.md.' }
if (-not $DevelopmentBuild -and -not (Test-Path -LiteralPath (Join-Path $projectRoot 'oauth-client.json'))) {
    throw 'A release needs the publisher Desktop OAuth client configuration at oauth-client.json. Use -DevelopmentBuild for an unconfigured preview.'
}
& $pythonExe -c "from run import tray_image; tray_image().save('packaging/locin.ico', sizes=[(16,16),(32,32),(48,48),(64,64)])"
if ($LASTEXITCODE -ne 0) { throw 'Could not create the application icon.' }
& $pythonExe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $pythonExe -m PyInstaller --noconfirm packaging/locin.spec
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
$previousDataDirectory = $env:LOCIN_DATA_DIR
try {
    $env:LOCIN_DATA_DIR = Join-Path $projectRoot 'data\build-smoke'
    $smoke = Start-Process -FilePath (Join-Path $projectRoot 'dist\locin\locin.exe') -ArgumentList '--smoke-test' -PassThru -WindowStyle Hidden
    if (-not $smoke.WaitForExit(30000)) { $smoke.Kill(); throw 'Packaged startup timed out.' }
    if ($smoke.ExitCode -ne 0) { throw 'Packaged startup failed. See data/build-smoke/smoke.log.' }
} finally {
    $env:LOCIN_DATA_DIR = $previousDataDirectory
}
if (-not $SkipInstaller) {
    $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $projectCompiler = Join-Path $projectRoot '.tools\InnoSetup\ISCC.exe'
    $compilerPath = if ($compiler) { $compiler.Source } elseif (Test-Path -LiteralPath $projectCompiler) { $projectCompiler } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
    if (-not (Test-Path -LiteralPath $compilerPath)) { throw 'Portable app built in dist/locin. Install Inno Setup 6 to compile loc.in Setup.exe.' }
    & $compilerPath packaging/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
}

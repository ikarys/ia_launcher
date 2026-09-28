# Lance l'IA Launcher (WSL) et ouvre sa page : http://127.0.0.1:8090
# Fenetre = launcher : la fermer (ou Ctrl+C) arrete le launcher ET les modeles
# qu'il a lances. Tant qu'elle est ouverte, la mise en veille est bloquee.
#   ia-launcher.ps1 -AllowSleep     laisse la veille se declencher

param([switch]$AllowSleep)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$url = "http://127.0.0.1:8090"

# Deja lance : on ouvre juste la page
try {
    $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$url/api/status"
    Start-Process $url
    exit 0
} catch { }

# Meme mecanisme que start-ninfer.ps1 : liberee automatiquement a la fin du processus
$sleepBlocked = $false
if (-not $AllowSleep) {
    try {
        if (-not ("Win32.Power" -as [type])) {
            Add-Type -Namespace Win32 -Name Power -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
        }
        $flags = [uint32]"0x80000000" -bor [uint32]"0x00000001"   # CONTINUOUS | SYSTEM_REQUIRED
        if ([Win32.Power]::SetThreadExecutionState($flags) -ne 0) { $sleepBlocked = $true }
    } catch { }
}

Write-Host ""
Write-Host "  IA Launcher" -ForegroundColor Cyan
Write-Host ("  " + ("-" * 58)) -ForegroundColor DarkGray
Write-Host "  Page    : $url" -ForegroundColor Green
if ($sleepBlocked) { Write-Host "  Veille  : bloquee tant que cette fenetre est ouverte" -ForegroundColor Green }
else { Write-Host "  Veille  : NON bloquee" -ForegroundColor DarkYellow }
Write-Host "  Fermer cette fenetre = arret du launcher et des modeles lances depuis la page."
Write-Host ""

# Ouvre la page des que le launcher repond
Start-Process powershell -WindowStyle Hidden -ArgumentList @('-NoProfile', '-Command',
    "for (`$i = 0; `$i -lt 60; `$i++) { try { `$null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '$url/api/status'; Start-Process '$url'; break } catch { Start-Sleep -Seconds 1 } }")

try {
    wsl -d Ubuntu --cd ~ -e bash workspace/ia_launcher/run.sh
}
finally {
    if ($sleepBlocked) { [void][Win32.Power]::SetThreadExecutionState([uint32]"0x80000000") }
}

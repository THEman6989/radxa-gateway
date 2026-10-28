<#
  Haupt-PC (Windows-Seite des CachyOS/Windows-Dual-Boots): SSH-Zugang fuer das
  Radxa-ROCK-2A-Gateway einrichten, damit "Windows schlafen / neustarten /
  herunterfahren" in der PC-Steuerung funktionieren.

  Was das Skript macht (idempotent, mehrfach ausfuehrbar):
    1. OpenSSH-Server installieren (Windows-Feature, Fallback: offizielles MSI)
    2. Dienst sshd starten + Autostart
    3. Oeffentlichen Gateway-Schluessel in administrators_authorized_keys
       eintragen (ACL per SID, sprachunabhaengig)
    4. Firewall: SSH (TCP 22) und Ping NUR aus Tailscale (100.64.0.0/10) und
       Heimnetz (192.168.2.0/24) erlauben
    5. Pruefen und Ergebnis nach C:\Users\Public\radxa-ssh-setup-result.txt
       schreiben

  Es wird NICHTS neu gestartet, keine Bootreihenfolge geaendert, keine
  Sicherheitsfunktion abgeschaltet.

  Ausfuehren (Administrator-PowerShell):
    powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-haupt-pc-ssh.ps1
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$GatewayKey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL3n9+plPmfo/DK6L5NyZsr3FitEKZ+8iyHprNUgYd4z radxa-gateway->haupt-pc-windows'
$AllowedRemote = @('100.64.0.0/10', '192.168.2.0/24')
$ResultFile = 'C:\Users\Public\radxa-ssh-setup-result.txt'
$Log = New-Object System.Collections.Generic.List[string]
function Say($m) { $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; Write-Host $line; $Log.Add($line) }

# --- 0. Adminrechte -------------------------------------------------------
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'FEHLER: Bitte als Administrator ausfuehren (Rechtsklick -> Als Administrator ausfuehren).' -ForegroundColor Red
    exit 1
}
Say "Rechner: $env:COMPUTERNAME  Benutzer: $($id.Name)"

# --- 1. OpenSSH-Server ----------------------------------------------------
$svc = Get-Service sshd -ErrorAction SilentlyContinue
if (-not $svc) {
    Say 'OpenSSH-Server nicht vorhanden - installiere Windows-Feature (max. 10 Minuten) ...'
    $job = Start-Job { Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null }
    if (-not (Wait-Job $job -Timeout 600)) { Stop-Job $job; Say 'Windows-Feature haengt - nutze offizielles MSI.' }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    $svc = Get-Service sshd -ErrorAction SilentlyContinue
}
if (-not $svc) {
    $rel = Invoke-RestMethod 'https://api.github.com/repos/PowerShell/Win32-OpenSSH/releases/latest' -Headers @{ 'User-Agent' = 'radxa-setup' }
    $asset = $rel.assets | Where-Object { $_.name -like 'OpenSSH-Win64-v*.msi' } | Select-Object -First 1
    if (-not $asset) { throw 'Kein OpenSSH-MSI im offiziellen Release gefunden.' }
    $msi = Join-Path $env:TEMP $asset.name
    Invoke-WebRequest $asset.browser_download_url -OutFile $msi -UseBasicParsing
    $sig = Get-AuthenticodeSignature $msi
    if ($sig.Status -ne 'Valid') { throw "MSI-Signatur ungueltig: $($sig.Status)" }
    Say "Installiere $($asset.name) (Signatur: $($sig.SignerCertificate.Subject))"
    $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList "/i `"$msi`" /qn /norestart ADDLOCAL=Server"
    if ($p.ExitCode -ne 0) { throw "MSI-Installation fehlgeschlagen, Exitcode $($p.ExitCode)" }
    $svc = Get-Service sshd -ErrorAction Stop
}
Set-Service sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne 'Running') { Start-Service sshd }
Say "sshd: $((Get-Service sshd).Status), Starttyp Automatic"

# --- 2. Gateway-Schluessel -------------------------------------------------
$keyFile = 'C:\ProgramData\ssh\administrators_authorized_keys'
if (-not (Test-Path $keyFile)) { New-Item -ItemType File -Path $keyFile -Force | Out-Null }
$existing = Get-Content $keyFile -ErrorAction SilentlyContinue
if ($existing -notcontains $GatewayKey) {
    Add-Content -Path $keyFile -Value $GatewayKey -Encoding ascii
    Say 'Gateway-Schluessel eingetragen.'
} else { Say 'Gateway-Schluessel war bereits eingetragen.' }
# ACL nur SYSTEM + Administratoren, per SID (deutsche Gruppennamen brechen sonst ab)
& icacls.exe $keyFile /inheritance:r /grant '*S-1-5-18:F' /grant '*S-1-5-32-544:F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'icacls fehlgeschlagen' }
Say 'Rechte auf administrators_authorized_keys gesetzt.'

# --- 3. Firewall -----------------------------------------------------------
foreach ($r in @('Radxa Gateway SSH', 'Radxa Gateway Ping')) { Get-NetFirewallRule -DisplayName $r -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
New-NetFirewallRule -DisplayName 'Radxa Gateway SSH' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -RemoteAddress $AllowedRemote -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'Radxa Gateway Ping' -Direction Inbound -Action Allow -Protocol ICMPv4 -IcmpType 8 -RemoteAddress $AllowedRemote -Profile Any | Out-Null
Say "Firewall: SSH + Ping nur aus $($AllowedRemote -join ', ')."

# --- 4. Pruefung -----------------------------------------------------------
$listen = Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue
$ts = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -like '100.*' } | Select-Object -First 1).IPAddress
$priv = (whoami /priv | Select-String 'SeShutdownPrivilege') -ne $null
$admins = (Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ', '
$nic = Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up' | Select-Object -First 1
Say "Port 22 lauscht: $([bool]$listen)"
Say "Tailscale-IP: $ts   (erwartet 100.105.45.44)"
Say "Adapter: $($nic.Name) MAC $($nic.MacAddress)"
Say "Administratoren: $admins"
Say "Shutdown-Recht vorhanden: $priv"
$ok = [bool]$listen -and ($existing -contains $GatewayKey -or (Get-Content $keyFile) -contains $GatewayKey)
Say ($(if ($ok) { 'ERGEBNIS: OK - SSH fuer das Gateway ist eingerichtet.' } else { 'ERGEBNIS: FEHLER - siehe Zeilen oben.' }))
$Log | Set-Content -Path $ResultFile -Encoding utf8
Write-Host "Ergebnis gespeichert in $ResultFile"
if (-not $ok) { exit 2 }

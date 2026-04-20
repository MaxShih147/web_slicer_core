# Trust the local dev TLS certificate for SSL (CurrentUser\Root). web_slicer_core helper.
# Aligns with scripts/dev-setup-tls.ps1: certutil -user (usually no Administrator), thumbprint idempotency.
# Does not create or modify PEM files under tls/.
# Comments and user-facing messages are in English per project convention.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

function Write-Skip([string]$Message) { Write-Host "==> $Message (skip — already satisfied)" }
function Write-Do([string]$Message) { Write-Host "==> $Message" }

function Resolve-AgentCertPath {
    $c = $env:AGENT_TLS_CERTFILE
    if ($c) {
        if (Test-Path -LiteralPath $c) { return $c }
        Write-Warning "AGENT_TLS_CERTFILE set but file not found: $c (trying other locations)"
    }
    $c = $env:BUNDLE_TLS_CERT_PATH
    if ($c) {
        if (Test-Path -LiteralPath $c) { return $c }
        Write-Warning "BUNDLE_TLS_CERT_PATH set but file not found: $c (trying other locations)"
    }
    $c = $env:SSL_CERTFILE
    if ($c) {
        if (Test-Path -LiteralPath $c) { return $c }
        Write-Warning "SSL_CERTFILE set but file not found: $c (trying other locations)"
    }
    $candidates = @(
        (Join-Path $RepoRoot 'agent\tls\localhost.crt'),
        (Join-Path $RepoRoot 'tls\localhost.crt'),
        (Join-Path $RepoRoot '..\Bundle-Launcher\bundle-mac\agent\tls\localhost.crt'),
        (Join-Path $RepoRoot '..\Bundle-Launcher\bundle-win\agent\tls\localhost.crt')
    )
    foreach ($p in $candidates) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Get-CertificateThumbprintFromFile([string]$CertPath) {
    $resolved = (Resolve-Path -LiteralPath $CertPath).Path
    $x509 = $null
    try {
        try {
            $x509 = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($resolved)
        } catch {
            $bytes = [System.IO.File]::ReadAllBytes($resolved)
            $x509 = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes)
        }
        return $x509.Thumbprint
    } catch {
        Write-Host "Could not load certificate for thumbprint (PEM/DER or .NET version?): $resolved"
        throw
    } finally {
        if ($null -ne $x509) { $x509.Dispose() }
    }
}

function Test-CertInCurrentUserRoot([string]$Thumbprint) {
    $found = Get-ChildItem Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $Thumbprint }
    return [bool]$found
}

function Ensure-WindowsTrust([string]$CertPath) {
    $thumb = Get-CertificateThumbprintFromFile $CertPath
    if (Test-CertInCurrentUserRoot $thumb) {
        Write-Skip "Windows CurrentUser\Root already contains this certificate (thumbprint match)"
        return
    }

    Write-Do "certutil: add to CurrentUser\Root (usually no Administrator required)"
    Write-Host "    $CertPath"
    # Invoke certutil without piping first so $LASTEXITCODE reflects certutil (not Out-Host).
    $resolvedCert = (Resolve-Path -LiteralPath $CertPath).Path
    $certOut = & certutil.exe -user -f -addstore Root $resolvedCert 2>&1
    $certExit = $LASTEXITCODE
    $certOut | Out-Host
    if ($certExit -ne 0) {
        if (Test-CertInCurrentUserRoot $thumb) {
            Write-Skip "Windows trust (certificate already in store)"
            return
        }
        Write-Host "certutil failed. Install the .crt manually: certmgr.msc -> Trusted Root Certification Authorities -> Certificates."
        exit $certExit
    }
}

# --- main ---

$certPath = Resolve-AgentCertPath
if (-not $certPath) {
    Write-Host "TLS certificate not found."
    Write-Host "  Place PEM at: $(Join-Path $RepoRoot 'agent\tls\localhost.crt') (or $(Join-Path $RepoRoot 'tls\localhost.crt'))"
    Write-Host "  Or set AGENT_TLS_CERTFILE, BUNDLE_TLS_CERT_PATH, or SSL_CERTFILE to an existing .crt/.pem."
    exit 1
}

Ensure-WindowsTrust $certPath

Write-Host ""
Write-Host "Restart the browser, then try https://127.0.0.1:5179 and https://127.0.0.1:5180"
Write-Host "Optional for Node:"
Write-Host "  `$env:NODE_EXTRA_CA_CERTS='$certPath'"

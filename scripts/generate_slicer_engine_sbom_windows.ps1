#Requires -Version 5.1
<#
.SYNOPSIS
  Generate minimal SPDX 2.3 JSON SBOM for a packaged slicer-engine artifact (tasks 6.4 / D10a).
#>
param(
    [Parameter(Mandatory = $true)][string]$ArtifactRoot,
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$ArtifactRoot = (Resolve-Path -LiteralPath $ArtifactRoot).Path
$manifestPath = Join-Path $ArtifactRoot "engine-artifact-manifest.json"
if (-not (Test-Path $manifestPath)) { $manifestPath = Join-Path $ArtifactRoot "artifact-manifest.json" }
if (-not (Test-Path $manifestPath)) { throw "Missing manifest under $ArtifactRoot" }
$man = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

if (-not $OutPath) { $OutPath = Join-Path $ArtifactRoot "sbom.spdx.json" }

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

$packages = [System.Collections.Generic.List[object]]::new()
$relationships = [System.Collections.Generic.List[object]]::new()
$docName = "slicer-engine-$($man.engine_build_id)"
$docSpdxId = "SPDXRef-DOCUMENT"

$packages.Add([ordered]@{
    SPDXID           = "SPDXRef-Package-slicer-engine"
    name             = "slicer-engine"
    versionInfo      = [string]$man.engine_build_id
    downloadLocation = "NOASSERTION"
    filesAnalyzed    = $false
    supplier         = "Organization: Phrozen Technology"
    copyrightText    = "NOASSERTION"
    licenseConcluded = "AGPL-3.0-only"
    licenseDeclared  = "AGPL-3.0-only"
    comment          = "Modified PrusaSlicer-derived CLI; see legal/SOURCE_OFFER.md"
    externalRefs     = @(
        [ordered]@{
            referenceCategory = "OTHER"
            referenceType     = "buildId"
            referenceLocator  = [string]$man.engine_build_id
        },
        [ordered]@{
            referenceCategory = "OTHER"
            referenceType     = "gitCommit"
            referenceLocator  = [string]$man.engine_commit
        }
    )
})
$relationships.Add([ordered]@{
    spdxElementId      = $docSpdxId
    relationshipType   = "DESCRIBES"
    relatedSpdxElement = "SPDXRef-Package-slicer-engine"
})

$idx = 0
Get-ChildItem -LiteralPath (Join-Path $ArtifactRoot "bin") -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -match '\.(exe|dll)$' } |
    ForEach-Object {
        $idx++
        $sha = Get-Sha256 $_.FullName
        $spdxId = "SPDXRef-File-$idx"
        $packages.Add([ordered]@{
            SPDXID             = $spdxId
            name               = $_.Name
            versionInfo        = [string]$man.engine_build_id
            downloadLocation   = "NOASSERTION"
            filesAnalyzed      = $false
            checksums          = @([ordered]@{ algorithm = "SHA256"; checksumValue = $sha })
            licenseConcluded   = "NOASSERTION"
            licenseDeclared    = "NOASSERTION"
            copyrightText      = "NOASSERTION"
        })
        $relationships.Add([ordered]@{
            spdxElementId      = "SPDXRef-Package-slicer-engine"
            relationshipType   = "CONTAINS"
            relatedSpdxElement = $spdxId
        })
    }

$sbom = [ordered]@{
    spdxVersion        = "SPDX-2.3"
    dataLicense        = "CC0-1.0"
    SPDXID             = $docSpdxId
    name               = $docName
    documentNamespace  = "https://phrozen3d.com/spdx/slicer-engine/$($man.engine_build_id)"
    creationInfo       = [ordered]@{
        created  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        creators = @("Tool: package_slicer_engine_windows.ps1", "Organization: Phrozen Technology")
    }
    packages           = @($packages)
    relationships      = @($relationships)
    comment            = "REQ-DEID-011/6.4: binary SHA-256 ↔ engine_build_id ↔ engine_commit. Corresponding Source via legal/SOURCE_OFFER.md (email/written offer)."
}

$sbom | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutPath -Encoding utf8
Write-Host "Wrote SPDX 2.3 SBOM: $OutPath" -ForegroundColor Green

# Chain evidence sidecar
$chain = [ordered]@{
    schema                 = "slicer-engine-source-chain/1.0"
    engine_build_id        = [string]$man.engine_build_id
    engine_commit          = [string]$man.engine_commit
    flavor                 = [string]$man.flavor
    exe_post_strip_sha256  = [string]$man.post_strip_sha256
    sbom_path              = "sbom.spdx.json"
    sbom_format            = "SPDX-2.3-JSON"
    source_offer           = "legal/SOURCE_OFFER.md"
    generated_at_utc       = (Get-Date).ToUniversalTime().ToString("o")
}
$chainPath = Join-Path $ArtifactRoot "source-chain.json"
$chain | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $chainPath -Encoding utf8
Write-Host "Wrote source chain: $chainPath" -ForegroundColor Green

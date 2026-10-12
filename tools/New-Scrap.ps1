param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[a-z0-9]+(?:-[a-z0-9]+)*$')]
  [string]$Slug
)

$dir = Join-Path $PSScriptRoot "../scraps/$Slug"
$dir = [System.IO.Path]::GetFullPath($dir)

if (Test-Path -LiteralPath $dir) {
  Write-Error "already exists: $dir"
  exit 1
}

New-Item -ItemType Directory -Path $dir | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "../templates/scrap.md") -Destination (Join-Path $dir "README.md")

Write-Output "created: $dir"

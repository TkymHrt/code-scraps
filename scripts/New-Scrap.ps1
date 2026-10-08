param(
  [Parameter(Mandatory = $true)]
  [string]$Slug
)

$today = Get-Date
$dir = Join-Path $PSScriptRoot ("../{0}/{1:MM-dd}/{2}" -f $today.Year, $today, $Slug)
$dir = [System.IO.Path]::GetFullPath($dir)

if (Test-Path $dir) {
  Write-Error "already exists: $dir"
  exit 1
}

New-Item -ItemType Directory -Path $dir | Out-Null
Copy-Item (Join-Path $PSScriptRoot "../_template/README.md") (Join-Path $dir "README.md")

Write-Output "created: $dir"

param([Parameter(Mandatory=$true)][string]$Names, [string]$PropsOnly = "0")
$p = Join-Path $PSScriptRoot '..\idb\macos26-25G325-x86_64-frameworks\metal-objc.json'
$raw = Get-Content $p -Raw
$lines = $raw -split "`n"
$starts = @{}
for ($i=0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match '^@interface\s+(\w+)') { $starts[$Matches[1]] = $i }
}
foreach ($n in ($Names -split ',')) {
  $n = $n.Trim()
  if ($n -eq '') { continue }
  if (-not $starts.ContainsKey($n)) { "### $n  -- NOT FOUND"; continue }
  $s = $starts[$n]
  $e = $s
  while ($e -lt $lines.Count -and $lines[$e].TrimEnd() -ne '@end') { $e++ }
  "### $n  (lines $($s+1)..$($e+1))"
  for ($k=$s; $k -le $e; $k++) {
    $l = $lines[$k].TrimEnd()
    if ($PropsOnly -eq "1") {
      if ($l -match '^@property' -or $l -match '^@interface' -or $l -match '^@end') { $l }
    } else { $l }
  }
  ""
}

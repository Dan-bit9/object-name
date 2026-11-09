param([string]$LogDir = "$PWD\deployment-logs", [string]$StopFile = "$PWD\monitor.stop", [int]$PostSeconds = 30)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$image = Join-Path $LogDir 'fixed-test.png'
[IO.File]::WriteAllBytes($image, [Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
$log = Join-Path $LogDir 'requests.jsonl'
$start = Get-Date
$stopSeen = $false; $postUntil = $null
while ($true) {
  $t0 = Get-Date; $status = 0; $ok = $false; $version = ''; $body = ''
  try {
    $body = & curl.exe -sS --max-time 20 -X POST -F "file=@$image" http://127.0.0.1:8000/api/identify
    $status = if ($LASTEXITCODE -eq 0) { 200 } else { 0 }
    $json = $body | ConvertFrom-Json
    $ok = ($json.ok -eq $true); $version = [string]$json.model_version
  } catch { $body = $_.Exception.Message }
  $t1 = Get-Date
  $record = [ordered]@{ start=$t0.ToUniversalTime().ToString('o'); end=$t1.ToUniversalTime().ToString('o'); response_ms=[math]::Round(($t1-$t0).TotalMilliseconds,2); status=$status; analysis_ok=$ok; model_version=$version; response=$body }
  ($record | ConvertTo-Json -Compress) | Out-File -FilePath $log -Append -Encoding utf8
  if (Test-Path $StopFile) {
    if (-not $stopSeen) { $stopSeen = $true; $postUntil = (Get-Date).AddSeconds($PostSeconds) }
    if ((Get-Date) -ge $postUntil) { break }
  }
  Start-Sleep -Seconds 1
}
$rows = @(Get-Content $log -Encoding utf8 | ForEach-Object { $_ | ConvertFrom-Json })
$okCount = @($rows | Where-Object analysis_ok -eq $true).Count
$failCount = $rows.Count - $okCount
$versions = (($rows | Select-Object -ExpandProperty model_version -Unique) -join ', ')
@("# Deployment verification summary", "", "- Address: http://127.0.0.1:8000", "- Started (UTC): $($start.ToUniversalTime().ToString('o'))", "- Finished (UTC): $((Get-Date).ToUniversalTime().ToString('o'))", "- Requests: $($rows.Count)", "- Success: $okCount", "- Failure: $failCount", "- Observed versions: $versions", "- Interval target: 1 second; unobserved gaps are not claimed as zero-downtime", "", "## Representative responses", "", ('```json'), (($rows | Select-Object -First 1 | ConvertTo-Json -Depth 5)), (($rows | Select-Object -Last 1 | ConvertTo-Json -Depth 5)), ('```')) | Out-File (Join-Path $LogDir 'summary.md') -Encoding utf8

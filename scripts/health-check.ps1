$ErrorActionPreference = 'Stop'

$endpoints = [ordered]@{
    'Config' = 'http://localhost:8888/actuator/health'
    'Discovery' = 'http://localhost:8761/actuator/health'
    'Gateway' = 'http://localhost:8080/actuator/health'
    'User via Gateway' = 'http://localhost:8080/api/v1/users/status'
    'Product via Gateway' = 'http://localhost:8080/api/v1/products/status'
    'Try-On via Gateway' = 'http://localhost:8080/api/v1/tryon/status'
    'Recommendation via Gateway' = 'http://localhost:8080/api/v1/recommendations/status'
}

$failed = $false
foreach ($entry in $endpoints.GetEnumerator()) {
    try {
        $response = Invoke-WebRequest -Uri $entry.Value -UseBasicParsing -TimeoutSec 5
        Write-Host "[OK] $($entry.Key) ($($response.StatusCode))" -ForegroundColor Green
    }
    catch {
        Write-Host "[FAIL] $($entry.Key): $($_.Exception.Message)" -ForegroundColor Red
        $failed = $true
    }
}

if ($failed) { exit 1 }

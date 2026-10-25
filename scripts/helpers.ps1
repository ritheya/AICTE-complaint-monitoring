$base = "http://127.0.0.1:8000"

function Login($email) {
  $b = @{ email = $email; password = "Demo@123" } | ConvertTo-Json
  $r = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" -Body $b
  return @{ Authorization = "Bearer $($r.access_token)" }
}

function Call($method, $path, $headers) {
  try { return Invoke-RestMethod -Method $method -Uri "$base$path" -Headers $headers }
  catch { Write-Host "  -> HTTP $([int]$_.Exception.Response.StatusCode)  ($method $path)" -ForegroundColor Yellow }
}

function Send($method, $path, $headers, $body) {
  try { return Invoke-RestMethod -Method $method -Uri "$base$path" -Headers $headers -ContentType "application/json" -Body ($body | ConvertTo-Json) }
  catch { Write-Host "  -> HTTP $([int]$_.Exception.Response.StatusCode)  ($method $path)" -ForegroundColor Yellow }
}

function HistCount($id, $headers) { return @((Call Get "/complaints/$id" $headers).action_history).Count }
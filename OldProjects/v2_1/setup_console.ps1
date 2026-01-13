# Setup PowerShell console for UTF-8 encoding
# Run this before using check scripts if you see encoding issues

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

Write-Host "Console encoding set to UTF-8" -ForegroundColor Green


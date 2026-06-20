# ============================================================
# fix_ssh_window.ps1
# Убирает всплывающее окно OpenSSH при подключении Antigravity IDE
#
# Запусти в PowerShell от АДМИНИСТРАТОРА:
#   powershell -ExecutionPolicy Bypass -File fix_ssh_window.ps1
# ============================================================

$sshWrapperDir = "$env:USERPROFILE\.ssh"
$wrapperPath = "$sshWrapperDir\ssh-wrapper.bat"
$vbsPath = "$sshWrapperDir\ssh-hidden.vbs"

# Создаём .ssh директорию если нет
if (-not (Test-Path $sshWrapperDir)) {
    New-Item -ItemType Directory -Path $sshWrapperDir -Force | Out-Null
    Write-Host "[+] Создана директория: $sshWrapperDir" -ForegroundColor Green
}

# --- VBS обёртка: запускает ssh.exe БЕЗ окна ---
$vbsContent = @'
' ssh-hidden.vbs — запускает OpenSSH без видимого окна
' Antigravity IDE вызывает этот скрипт вместо ssh.exe напрямую

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Собираем аргументы в одну строку
strArgs = ""
For i = 0 To WScript.Arguments.Count - 1
    arg = WScript.Arguments(i)
    ' Оборачиваем в кавычки если есть пробелы
    If InStr(arg, " ") > 0 Then
        arg = """" & arg & """"
    End If
    If strArgs <> "" Then strArgs = strArgs & " "
    strArgs = strArgs & arg
Next

' Запускаем ssh.exe скрыто (0 = vbHide), но ждём завершения (True)
strCommand = "C:\Windows\System32\OpenSSH\ssh.exe " & strArgs
objShell.Run strCommand, 0, False
'@

# --- BAT обёртка: вызывает VBS (для совместимости с IDE) ---
$batContent = @"
@echo off
wscript.exe "%~dp0ssh-hidden.vbs" %*
"@

# Записываем файлы
Set-Content -Path $vbsPath -Value $vbsContent -Encoding ASCII
Write-Host "[+] Создан: $vbsPath" -ForegroundColor Green

Set-Content -Path $wrapperPath -Value $batContent -Encoding ASCII
Write-Host "[+] Создан: $wrapperPath" -ForegroundColor Green

# --- Настраиваем SSH config (keepalive) ---
$configPath = "$sshWrapperDir\config"
$keepaliveBlock = @"

# =========================================================================
# Глобальные настройки - keepalive для ВСЕХ подключений
# Предотвращает обрывы SSH и всплывающие окна переподключения
# =========================================================================

Host *
    ServerAliveInterval 30
    ServerAliveCountMax 10
    TCPKeepAlive yes

"@

if (Test-Path $configPath) {
    $existing = Get-Content $configPath -Raw
    if ($existing -match "ServerAliveInterval") {
        Write-Host "[=] SSH keepalive уже настроен" -ForegroundColor Yellow
    } else {
        $newContent = $keepaliveBlock + $existing
        Set-Content -Path $configPath -Value $newContent -Encoding UTF8
        Write-Host "[+] SSH keepalive добавлен" -ForegroundColor Green
    }
} else {
    Set-Content -Path $configPath -Value $keepaliveBlock.Trim() -Encoding UTF8
    Write-Host "[+] Создан SSH config с keepalive" -ForegroundColor Green
}

# --- Итог ---
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  ГОТОВО! Теперь настрой Antigravity IDE:" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Открой Settings (Ctrl+,)" -ForegroundColor White
Write-Host "  2. Найди: remote.SSH.path" -ForegroundColor White
Write-Host "  3. Укажи путь:" -ForegroundColor White
Write-Host ""
Write-Host "     $vbsPath" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Или добавь в settings.json:" -ForegroundColor White
Write-Host ""
Write-Host "     ""remote.SSH.path"": ""$($vbsPath -replace '\\','\\')"" " -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. Перезапусти IDE" -ForegroundColor White
Write-Host ""
Read-Host "Нажми Enter для выхода"

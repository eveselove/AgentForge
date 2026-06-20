# ============================================================
# fix_ssh_complete.ps1
# Полная настройка SSH для Antigravity IDE
# Убирает окно OpenSSH + настраивает keepalive
#
# Запусти: powershell -ExecutionPolicy Bypass -File fix_ssh_complete.ps1
# ============================================================

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  Antigravity IDE — SSH Fix (окно + keepalive)" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# --- 1. SSH Config: keepalive ---
$sshDir = "$env:USERPROFILE\.ssh"
if (-not (Test-Path $sshDir)) {
    New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
    Write-Host "[+] Создана директория: $sshDir" -ForegroundColor Green
}

$configPath = "$sshDir\config"
$existing = if (Test-Path $configPath) { Get-Content $configPath -Raw } else { "" }

if ($existing -notmatch "ServerAliveInterval") {
    $keepalive = "Host *`r`n    ServerAliveInterval 30`r`n    ServerAliveCountMax 10`r`n    TCPKeepAlive yes`r`n`r`n"
    Set-Content -Path $configPath -Value ($keepalive + $existing) -Encoding UTF8 -NoNewline
    Write-Host "[+] SSH keepalive настроен" -ForegroundColor Green
} else {
    Write-Host "[=] SSH keepalive уже есть" -ForegroundColor Yellow
}

# --- 2. Найти Git SSH или скачать ---
$gitSshPaths = @(
    "C:\Program Files\Git\usr\bin\ssh.exe",
    "C:\Program Files (x86)\Git\usr\bin\ssh.exe",
    "${env:LOCALAPPDATA}\Programs\Git\usr\bin\ssh.exe"
)

$gitSsh = $null
foreach ($p in $gitSshPaths) {
    if (Test-Path $p) {
        $gitSsh = $p
        Write-Host "[+] Найден Git SSH: $p" -ForegroundColor Green
        break
    }
}

if (-not $gitSsh) {
    Write-Host "[!] Git for Windows не найден. Устанавливаю..." -ForegroundColor Yellow
    
    # Скачиваем Git for Windows (portable, минимальная установка)
    $gitInstaller = "$env:TEMP\git-installer.exe"
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe"
    
    try {
        Write-Host "    Скачиваю Git for Windows..." -ForegroundColor Gray
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $gitUrl -OutFile $gitInstaller -UseBasicParsing
        
        Write-Host "    Устанавливаю Git (тихая установка)..." -ForegroundColor Gray
        Start-Process -FilePath $gitInstaller -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=""gitlfs""" -Wait -NoNewWindow
        
        # Проверяем после установки
        foreach ($p in $gitSshPaths) {
            if (Test-Path $p) {
                $gitSsh = $p
                Write-Host "[+] Git установлен! SSH: $p" -ForegroundColor Green
                break
            }
        }
        
        Remove-Item $gitInstaller -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "[!] Не удалось скачать Git автоматически: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "    Скачай вручную: https://git-scm.com/download/win" -ForegroundColor Yellow
    }
}

# --- 3. Настроить Antigravity IDE ---
$ideSettingsPaths = @(
    "$env:APPDATA\antigravity-ide\User\settings.json",
    "$env:APPDATA\Antigravity IDE\User\settings.json",
    "$env:USERPROFILE\.antigravity-ide\settings.json"
)

$settingsFile = $null
foreach ($p in $ideSettingsPaths) {
    if (Test-Path $p) {
        $settingsFile = $p
        break
    }
}

# Если не нашли - ищем по паттерну
if (-not $settingsFile) {
    $found = Get-ChildItem "$env:APPDATA" -Recurse -Filter "settings.json" -ErrorAction SilentlyContinue | 
             Where-Object { $_.FullName -match "antigravity" -and $_.FullName -match "User" } | 
             Select-Object -First 1
    if ($found) { $settingsFile = $found.FullName }
}

if ($gitSsh -and $settingsFile) {
    Write-Host ""
    Write-Host "[*] Настраиваю IDE settings: $settingsFile" -ForegroundColor Cyan
    
    $settings = Get-Content $settingsFile -Raw -ErrorAction SilentlyContinue
    if ($settings) {
        $settingsObj = $settings | ConvertFrom-Json
    } else {
        $settingsObj = @{}
    }
    
    # Устанавливаем путь к SSH
    $sshPathEscaped = $gitSsh -replace '\\', '\\'
    
    if ($settings -match "remote.SSH.path") {
        # Заменяем существующий путь
        $settings = $settings -replace '"remote\.SSH\.path"\s*:\s*"[^"]*"', """remote.SSH.path"": ""$sshPathEscaped"""
    } else {
        # Добавляем перед последней }
        $settings = $settings.TrimEnd()
        if ($settings.EndsWith("}")) {
            $settings = $settings.Substring(0, $settings.Length - 1).TrimEnd()
            if (-not $settings.EndsWith(",") -and -not $settings.EndsWith("{")) {
                $settings += ","
            }
            $settings += "`r`n    ""remote.SSH.path"": ""$sshPathEscaped""`r`n}"
        }
    }
    
    Set-Content -Path $settingsFile -Value $settings -Encoding UTF8
    Write-Host "[+] IDE настроен: remote.SSH.path = $gitSsh" -ForegroundColor Green
    
} elseif ($gitSsh) {
    Write-Host ""
    Write-Host "[!] Файл настроек IDE не найден автоматически." -ForegroundColor Yellow
    Write-Host "    Открой IDE -> Settings (Ctrl+,) -> найди 'remote.SSH.path'" -ForegroundColor Yellow
    Write-Host "    И укажи: $gitSsh" -ForegroundColor Yellow
    
    # Ищем все возможные пути настроек для подсказки
    Write-Host ""
    Write-Host "    Поиск возможных файлов настроек..." -ForegroundColor Gray
    Get-ChildItem "$env:APPDATA" -Recurse -Filter "settings.json" -ErrorAction SilentlyContinue | 
        Where-Object { $_.FullName -match "antigravity|vscode|code" } |
        ForEach-Object { Write-Host "    Найден: $($_.FullName)" -ForegroundColor Gray }
} else {
    Write-Host ""
    Write-Host "[!] Git SSH не найден. Установи Git for Windows вручную:" -ForegroundColor Red
    Write-Host "    https://git-scm.com/download/win" -ForegroundColor Yellow
    Write-Host "    Затем перезапусти этот скрипт." -ForegroundColor Yellow
}

# --- Итог ---
Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  РЕЗУЛЬТАТ:" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  SSH keepalive:  $(if($existing -match 'ServerAliveInterval'){'уже был'}else{'настроен'})" -ForegroundColor White
Write-Host "  Git SSH:        $(if($gitSsh){$gitSsh}else{'НЕ НАЙДЕН — установи Git'})" -ForegroundColor $(if($gitSsh){'Green'}else{'Red'})
Write-Host "  IDE settings:   $(if($settingsFile -and $gitSsh){'настроен'}else{'настрой вручную (Ctrl+,)'})" -ForegroundColor $(if($settingsFile -and $gitSsh){'Green'}else{'Yellow'})
Write-Host ""
Write-Host "  После этого ПЕРЕЗАПУСТИ Antigravity IDE!" -ForegroundColor Yellow
Write-Host ""
Read-Host "Нажми Enter для выхода"

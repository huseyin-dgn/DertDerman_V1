param(
    [string]$ProjectPath = ""
)

$ErrorActionPreference = "Stop"

function Resolve-DjangoProjectPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        $candidate = (Resolve-Path $RequestedPath).Path
        if (Test-Path (Join-Path $candidate "manage.py")) {
            return $candidate
        }
        throw "Belirtilen klasörde manage.py bulunamadı: $RequestedPath"
    }

    $current = (Get-Location).Path

    if (Test-Path (Join-Path $current "manage.py")) {
        return $current
    }

    $nested = Join-Path $current "dertderman"
    if (Test-Path (Join-Path $nested "manage.py")) {
        return $nested
    }

    throw "Django proje klasörü bulunamadı."
}

$target = Resolve-DjangoProjectPath $ProjectPath
$bundle = $PSScriptRoot

Write-Host "A4.2 HOTFIX hedefi: $target"

$files = @(
    "assistant\actions.py",
    "assistant\views.py",
    "assistant\test_widget.py",
    "assistant\test_button_only_a42.py",
    "templates\components\assistant_widget.html",
    "static\css\assistant-widget.css",
    "static\js\assistant-widget.js"
)

foreach ($rel in $files) {
    $source = Join-Path $bundle $rel
    $dest = Join-Path $target $rel
    $destDir = Split-Path $dest -Parent
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    Copy-Item $source $dest -Force
    Write-Host "Güncellendi: $rel"
}

$obsolete = @(
    "assistant\intents.py",
    "assistant\test_intents_a4.py",
    "assistant\test_intents_a41.py"
)

foreach ($rel in $obsolete) {
    $path = Join-Path $target $rel
    if (Test-Path $path) {
        Remove-Item $path -Force
        Write-Host "Silindi: $rel"
    }
}

# Remove stale pyc files for intents if present.
$pycache = Join-Path $target "assistant\__pycache__"
if (Test-Path $pycache) {
    Get-ChildItem $pycache -Filter "intents*.pyc" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Kontrol: views.py artık intents import ediyor mu?"
$views = Get-Content (Join-Path $target "assistant\views.py") -Raw
if ($views -match "from \.intents") {
    throw "HOTFIX uygulanamadı: views.py hâlâ intents import ediyor."
}

Write-Host "OK: intents importu yok."
Write-Host ""
Write-Host "Şimdi:"
Write-Host "python manage.py check"
Write-Host "python manage.py test assistant -v 2"
Write-Host "python manage.py makemigrations --check"
Write-Host "git diff --check"

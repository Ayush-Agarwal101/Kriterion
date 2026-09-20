$ErrorActionPreference = "Stop"

$Dockerfile = Join-Path $PSScriptRoot "Dockerfile.rootfs"
$Assets = Join-Path $PSScriptRoot "assets"
$TarPath = Join-Path $Assets "rootfs.tar"
$Finch = "C:\Program Files\Finch\bin\finch.exe"
$Image = "kriterion-firecracker-rootfs:local"
$Container = "kriterion-firecracker-rootfs-export"
$BuildContext = $PSScriptRoot

Write-Host "==> Building Firecracker rootfs with Finch..."

& $Finch build `
    --platform linux/amd64 `
    -f $Dockerfile `
    -t $Image `
    $BuildContext

if ($LASTEXITCODE -ne 0) {
    throw "Finch image build failed."
}

Write-Host "==> Creating temporary container..."

& $Finch rm -f $Container 2>$null

& $Finch create `
    --name $Container `
    $Image

if ($LASTEXITCODE -ne 0) {
    throw "Finch container creation failed."
}

Write-Host "==> Exporting rootfs..."

if (Test-Path $TarPath) {
    Remove-Item $TarPath -Force
}

& $Finch export `
    $Container `
    -o $TarPath

if ($LASTEXITCODE -ne 0) {
    throw "Finch export failed."
}

Write-Host "==> Removing temporary container..."

& $Finch rm $Container

if ($LASTEXITCODE -ne 0) {
    throw "Failed to remove temporary Finch container."
}

Write-Host ""
Write-Host "Rootfs export created:"
Write-Host "  $TarPath"
Write-Host ""
Write-Host "Next step: convert this tar into firecracker/assets/rootfs.ext4 from WSL."
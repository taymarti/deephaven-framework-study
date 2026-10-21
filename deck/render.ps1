# Render every slide of a deck to PNG through PowerPoint (visual QA).
#   powershell -File render.ps1 <deck.pptx> <out_dir>
param([string]$Deck, [string]$Out)
$Deck = (Resolve-Path $Deck).Path
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
Get-ChildItem $Out -Filter *.png | Remove-Item
$app = New-Object -ComObject PowerPoint.Application
try {
    $p = $app.Presentations.Open($Deck, $true, $false, $false)  # read-only, no window
    foreach ($s in $p.Slides) {
        $s.Export((Join-Path $Out ("slide{0:D2}.png" -f $s.SlideIndex)), "PNG", 1600, 900)
    }
    "{0} slides -> {1}" -f $p.Slides.Count, $Out
    $p.Close()
} finally {
    $app.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}

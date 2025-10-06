param(
  [string]$FlagPath = ([System.IO.Path]::Combine($env:TEMP,'landing_judge_ready.flag'))
)

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase

$win = New-Object System.Windows.Window
$win.WindowStyle = 'None'
$win.ResizeMode = 'NoResize'
$win.AllowsTransparency = $true
$win.Background = (New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromArgb(230, 21, 21, 24)))
$win.Width = 420
$win.Height = 160
$win.Topmost = $true
$win.ShowInTaskbar = $false
$win.WindowStartupLocation = 'CenterScreen'
$win.Title = 'Landing Judge'

$grid = New-Object System.Windows.Controls.Grid
$grid.Margin = '20'
$stack = New-Object System.Windows.Controls.StackPanel
$stack.HorizontalAlignment = 'Center'
$stack.VerticalAlignment = 'Center'

$title = New-Object System.Windows.Controls.TextBlock
$title.Text = 'Preparing Landing Judge…'
$title.FontSize = 20
$title.Foreground = 'White'
$title.FontWeight = 'Bold'
$title.Margin = '0,0,0,8'
$title.TextAlignment = 'Center'

$desc = New-Object System.Windows.Controls.TextBlock
$desc.Text = 'Starting services, please wait'
$desc.FontSize = 12
$desc.Foreground = (New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromRgb(204,204,204)))
$desc.TextAlignment = 'Center'

$bar = New-Object System.Windows.Controls.ProgressBar
$bar.IsIndeterminate = $true
$bar.Height = 6
$bar.Margin = '0,16,0,0'
$bar.Foreground = (New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromRgb(95,176,255)))
$bar.Background = (New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromRgb(51,51,51)))

[void]$stack.Children.Add($title)
[void]$stack.Children.Add($desc)
[void]$stack.Children.Add($bar)
[void]$grid.Children.Add($stack)
$win.Content = $grid

$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(400)
$timer.Add_Tick({
    if (Test-Path -LiteralPath $FlagPath) {
        try { Remove-Item -LiteralPath $FlagPath -Force -ErrorAction SilentlyContinue } catch {}
        $timer.Stop()
        $win.Close()
    }
})

$win.SourceInitialized += {
    $timer.Start()
}

[void]$win.ShowDialog()
using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using LandingJudge.Services;

namespace LandingJudge;

public partial class OverlayColourWindow : Window
{
    private readonly EnvService? _env;
    private readonly VoteService? _voteService;
    private static readonly int[] PresetHues = { 0, 30, 60, 120, 157, 202, 220, 280, 320 };

    public OverlayColourWindow(EnvService? env, VoteService? voteService)
    {
        InitializeComponent();
        WindowThemeHelper.EnableDarkTitleBar(this);
        _env = env;
        _voteService = voteService;

        BuildSwatches();

        var currentHue = _env?.GetInt("OVERLAY_HUE_DEG", 0) ?? 0;
        HueSlider.Value = Math.Clamp(currentHue, 0, 359);
        UpdatePreview(HueSlider.Value);
    }

    private void BuildSwatches()
    {
        foreach (var hue in PresetHues)
        {
            var border = new Border
            {
                Width = 26,
                Height = 26,
                Margin = new Thickness(0, 0, 6, 6),
                CornerRadius = new CornerRadius(4),
                BorderBrush = (Brush)new BrushConverter().ConvertFromString("#2F3A4F")!,
                BorderThickness = new Thickness(1),
                Cursor = Cursors.Hand,
                Background = new SolidColorBrush(HueToColor(hue)),
                Tag = hue
            };
            border.MouseLeftButtonUp += (s, e) => HueSlider.Value = hue;
            SwatchPanel.Children.Add(border);
        }
    }

    private static Color HueToColor(double hueDeg)
    {
        // Representative preview swatch; the overlay applies this hue as a CSS hue-rotate()
        // filter over its whole UI, so this is an approximation, not an exact match.
        return HsvToRgb(hueDeg, 0.65, 0.85);
    }

    private static Color HsvToRgb(double h, double s, double v)
    {
        double c = v * s;
        double x = c * (1 - Math.Abs((h / 60.0) % 2 - 1));
        double m = v - c;
        double r, g, b;

        if (h < 60) (r, g, b) = (c, x, 0.0);
        else if (h < 120) (r, g, b) = (x, c, 0.0);
        else if (h < 180) (r, g, b) = (0.0, c, x);
        else if (h < 240) (r, g, b) = (0.0, x, c);
        else if (h < 300) (r, g, b) = (x, 0.0, c);
        else (r, g, b) = (c, 0.0, x);

        return Color.FromRgb((byte)((r + m) * 255), (byte)((g + m) * 255), (byte)((b + m) * 255));
    }

    private void UpdatePreview(double hue)
    {
        HueLabel.Text = $"{(int)hue}°";
        PreviewSwatch.Background = new SolidColorBrush(HueToColor(hue));
    }

    private void HueSlider_ValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        var hue = (int)e.NewValue;
        UpdatePreview(hue);

        _env?.Set("OVERLAY_HUE_DEG", hue.ToString());
        _voteService?.Broadcast("theme", new { type = "theme", hue_deg = hue });
    }

    private void Close_Click(object sender, RoutedEventArgs e) => Close();
}

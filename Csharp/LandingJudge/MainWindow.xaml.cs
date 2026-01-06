using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using LandingJudge.Services;
using Microsoft.Extensions.DependencyInjection;

namespace LandingJudge;

public partial class MainWindow : Window
{
    private EnvService? _env;
    private VoteService? _voteService;
    private QuoteService? _quoteService;
    private TtsService? _ttsService;
    private int _port = 5010;
    private int _currentHue = 0;
    private DispatcherTimer _saveTimer;
    private bool _isLoaded = false;

    public MainWindow()
    {
        InitializeComponent();
        
        _saveTimer = new DispatcherTimer();
        _saveTimer.Interval = TimeSpan.FromMilliseconds(500);
        _saveTimer.Tick += SaveTimer_Tick;

        Loaded += MainWindow_Loaded;
        Closing += MainWindow_Closing;
    }

    private void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        var services = App.AppHost?.Services;
        _env = services?.GetService<EnvService>();
        _voteService = services?.GetService<VoteService>();
        _quoteService = services?.GetService<QuoteService>();
        _ttsService = services?.GetService<TtsService>();

        if (_voteService != null)
        {
            AppendLog("Application started.");
            _port = _env?.GetInt("PORT", 5010) ?? 5010;
            AppendLog($"Server running on port {_port}");
        }

        LoadSettings();
        _isLoaded = true;
    }

    private void MainWindow_Closing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        SaveSettings(); // Force save on close
    }

    private void AppendLog(string message)
    {
        try 
        {
             File.AppendAllText("debug.log", $"[{DateTime.Now:HH:mm:ss}] {message}\n");
        }
        catch {}

        Dispatcher.Invoke(() =>
        {
            EventsLog.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}\n");
            EventsLog.ScrollToEnd();
        });
    }

    private void LoadSettings()
    {
        _env?.Load();

        _port = _env?.GetInt("PORT", 5010) ?? 5010;

        DingCheck.IsChecked = _env?.GetBool("ENABLE_DINGDONG", false) ?? false;
        LogCheck.IsChecked = _env?.GetBool("SHOW_EVENTS_LOG", true) ?? true;

        _currentHue = _env?.GetInt("OVERLAY_HUE_DEG", 0) ?? 0;

        // Effects
        var preset = _env?.Get("EFFECT_PRESET", "none") ?? "none";
        foreach (var child in EffectsPanel.Children)
        {
            if (child is RadioButton rb && rb.Tag?.ToString() == preset)
            {
                rb.IsChecked = true;
                break;
            }
        }
        
        StaticOnlyCheck.IsChecked = _env?.GetBool("ADD_STATIC_NOISE", false) ?? false;

        // Noise Level (Single Slider)
        var level = _env?.GetDouble("STATIC_NOISE_LEVEL", 0.0) ?? 0.0;
        SetNoiseSlider(level);
    }

    private void TriggerSave()
    {
        if (!_isLoaded) return;
        _saveTimer.Stop();
        _saveTimer.Start();
    }

    private void SaveTimer_Tick(object? sender, EventArgs e)
    {
        _saveTimer.Stop();
        SaveSettings();
    }

    private void SaveSettings()
    {
        if (_env == null) return;

        // Note: Port, Region, Voice, Format, TTS Enable, Keys are now managed by SettingsWindow
        // We only save local controls here (Effects, Noise, Ding, Log)
        
        var noiseLevel = SliderToLevel(NoiseSlider.Value);
        
        string preset = "none";
        foreach (var child in EffectsPanel.Children)
        {
            if (child is RadioButton rb && rb.IsChecked == true)
            {
                preset = rb.Tag?.ToString() ?? "none";
                break;
            }
        }

        bool addStaticNoise = StaticOnlyCheck.IsChecked == true;
        
        // Read values from env that are not on this UI but needed for broadcast/consistency
        bool enableTts = _env.GetBool("ENABLE_TTS", true);

        _env.Set("ENABLE_DINGDONG", DingCheck.IsChecked == true ? "true" : "false");
        _env.Set("SHOW_EVENTS_LOG", LogCheck.IsChecked == true ? "true" : "false");
        _env.Set("OVERLAY_HUE_DEG", _currentHue.ToString());
        
        _env.Set("EFFECT_PRESET", preset);
        _env.Set("ADD_STATIC_NOISE", addStaticNoise ? "true" : "false");
        
        _env.Set("STATIC_NOISE_LEVEL", noiseLevel.ToString("0.000"));
        _env.Set("RADIO_NOISE_LEVEL", noiseLevel.ToString("0.000"));
        _env.Set("WIND_NOISE_LEVEL", noiseLevel.ToString("0.000"));
        
        // Settings Window handles: PORT, REGION, VOICE, FORMAT, KEYS, ENABLE_TTS

        var settingsPayload = new
        {
            type = "settings",
            enable_tts = enableTts,
            enable_dingdong = DingCheck.IsChecked == true,
            effects = new
            {
                static_noise = addStaticNoise,
                preset = preset,
                static_noise_level = noiseLevel,
                radio_noise_level = noiseLevel,
                wind_noise_level = noiseLevel
            }
        };
        _voteService?.Broadcast("settings", settingsPayload);
        _voteService?.Broadcast("theme", new { type = "theme", hue_deg = _currentHue });
        
        StatusText.Text = "Settings saved.";
    }

    private void Setting_Changed(object sender, RoutedEventArgs e) => TriggerSave();
    
    private void LogCheck_CheckedChanged(object sender, RoutedEventArgs e) => TriggerSave();

    private void StaticOnly_Checked(object sender, RoutedEventArgs e) => TriggerSave();

    private void StaticOnly_Unchecked(object sender, RoutedEventArgs e) => TriggerSave();

    private void Effect_Checked(object sender, RoutedEventArgs e) => TriggerSave();

    private void NoiseSlider_ValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (NoiseSlider == null || NoiseValue == null) return;
        var level = SliderToLevel(NoiseSlider.Value);
        NoiseValue.Text = level.ToString("0.000");
        TriggerSave();
    }

    private void SetNoiseSlider(double level)
    {
        var clamped = Math.Clamp(level, 0.0, 0.1);
        var sliderValue = LevelToSlider(clamped);
        if (Math.Abs(NoiseSlider.Value - sliderValue) > 0.5)
        {
            NoiseSlider.Value = sliderValue;
        }
        NoiseValue.Text = clamped.ToString("0.000");
    }

    private static double SliderToLevel(double sliderValue) => Math.Round(sliderValue / 1000.0, 3);
    private static int LevelToSlider(double level) => (int)Math.Round(level * 1000);

    private async void Vote_Click(object sender, RoutedEventArgs e)
    {
        if (_voteService == null || _quoteService == null) return;

        if (sender is Button btn && int.TryParse(btn.Tag?.ToString(), out int score))
        {
            score = Math.Clamp(score, 1, 10);
            var (quote, message) = _quoteService.GetQuote(score);
            var tier = _quoteService.GetTier(score);

            // Reload settings to ensure we have latest (especially from Settings Window)
            _env?.Load();
            var enableTts = _env?.GetBool("ENABLE_TTS", true) ?? true;
            var enableBell = _env?.GetBool("ENABLE_DINGDONG", false) ?? false;
            var durationMs = _env?.GetInt("BANNER_DURATION_MS", 8000) ?? 8000;

            var audioUrl = "";
            if (enableTts && _ttsService != null)
            {
                try 
                {
                    audioUrl = await _ttsService.GenerateAudioUrlAsync(quote);
                }
                catch (Exception ex)
                {
                    AppendLog($"Error generating TTS: {ex.Message}");
                }
            }

            var effects = new
            {
                static_noise = _env?.GetBool("ADD_STATIC_NOISE", false) ?? false,
                preset = _env?.Get("EFFECT_PRESET", "none") ?? "none",
                static_noise_level = _env?.GetDouble("STATIC_NOISE_LEVEL", 0.0) ?? 0.0,
                radio_noise_level = _env?.GetDouble("RADIO_NOISE_LEVEL", 0.0) ?? 0.0,
                wind_noise_level = _env?.GetDouble("WIND_NOISE_LEVEL", 0.0) ?? 0.0
            };

            var payload = new
            {
                type = "vote",
                score = score,
                level = tier,
                quote = quote,
                message = message,
                audio_url = audioUrl,
                duration_ms = durationMs,
                enable_tts = enableTts,
                enable_dingdong = enableBell,
                effects
            };
            _voteService.Broadcast("vote", payload);
            AppendLog($"Vote broadcast: Score {score} ({tier})");
        }
    }

    private void OpenSettings_Click(object sender, RoutedEventArgs e)
    {
        var settings = new SettingsWindow(_env);
        settings.Owner = this;
        if (settings.ShowDialog() == true)
        {
            // Reload env and broadcast changes
            _env?.Load();
            TriggerSave(); 
            AppendLog("Configuration updated.");
        }
    }

    private void OpenHue_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new Window
        {
            Title = "Overlay Colour",
            Width = 400,
            Height = 200,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Owner = this,
            Background = new SolidColorBrush(Color.FromRgb(16, 19, 24)),
            Foreground = Brushes.White,
            ResizeMode = ResizeMode.NoResize
        };

        var stack = new StackPanel { Margin = new Thickness(20) };
        
        var valText = new TextBlock { Text = $"Hue: {_currentHue}°", HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0,0,0,10), Foreground = Brushes.White, FontSize = 16 };
        var slider = new Slider { Minimum = 0, Maximum = 360, Value = _currentHue, Margin = new Thickness(0,0,0,20) };
        slider.ValueChanged += (s, args) => 
        {
            _currentHue = (int)slider.Value;
            valText.Text = $"Hue: {_currentHue}°";
            _voteService?.Broadcast("theme", new { type = "theme", hue_deg = _currentHue });
        };

        var closeBtn = new Button { Content = "Close", Width = 100, Height = 30, Background = new SolidColorBrush(Color.FromRgb(40, 45, 55)), Foreground = Brushes.White, BorderThickness = new Thickness(0) };
        closeBtn.Click += (s, args) => dialog.Close();

        stack.Children.Add(valText);
        stack.Children.Add(slider);
        stack.Children.Add(closeBtn);
        dialog.Content = stack;
        
        dialog.ShowDialog();
        TriggerSave();
    }

    private void EditQuotes_Click(object sender, RoutedEventArgs e)
    {
        var path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "quotes.json");
        if (!File.Exists(path))
        {
            var defaultPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "quotes.default.json");
            if (File.Exists(defaultPath)) File.Copy(defaultPath, path);
            else File.WriteAllText(path, "{ \"quotes\": {}, \"messages\": {} }");
        }
        
        try
        {
            Process.Start(new ProcessStartInfo { FileName = path, UseShellExecute = true });
            StatusText.Text = "Opened quotes.json.";
            AppendLog("Opened quotes.json for editing.");
        }
        catch (Exception ex)
        {
            StatusText.Text = $"Error: {ex.Message}";
        }
    }

    private void ClearCache_Click(object sender, RoutedEventArgs e)
    {
        var res = MessageBox.Show("Delete all generated audio files? This cannot be undone.", "Clear Sound Cache", MessageBoxButton.YesNo, MessageBoxImage.Warning);
        if (res == MessageBoxResult.Yes)
        {
            try
            {
                var audioDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "wwwroot", "static", "audio");
                if (Directory.Exists(audioDir))
                {
                    var files = Directory.GetFiles(audioDir, "*.*")
                        .Where(f => f.EndsWith(".mp3") || f.EndsWith(".wav") || f.EndsWith("audio_index.json"));
                    int count = 0;
                    foreach (var f in files)
                    {
                        try { File.Delete(f); count++; } catch { }
                    }
                    StatusText.Text = $"Cleared {count} files.";
                    AppendLog($"Cleared {count} audio cache files.");
                }
            }
            catch (Exception ex)
            {
                StatusText.Text = $"Error: {ex.Message}";
            }
        }
    }

    private void ResetDefaults_Click(object sender, RoutedEventArgs e)
    {
        if (MessageBox.Show("Reset all settings to defaults?", "Confirm Reset", MessageBoxButton.YesNo) == MessageBoxResult.Yes)
        {
            _isLoaded = false; 

            // Only reset UI controls present on Main Window
            foreach (var child in EffectsPanel.Children)
            {
                if (child is RadioButton rb) rb.IsChecked = (rb.Tag?.ToString() == "none");
            }
            
            StaticOnlyCheck.IsChecked = false;
            NoiseSlider.Value = 0;
            
            LogCheck.IsChecked = true;
            DingCheck.IsChecked = false;
            
            _currentHue = 0;

            // Also reset Env defaults for non-UI settings?
            // "Reset Defaults" usually implies resetting everything.
            _env?.Set("PORT", "5010");
            _env?.Set("AWS_REGION", "us-east-1");
            _env?.Set("POLLY_VOICE_ID", "Joanna");
            _env?.Set("POLLY_OUTPUT_FORMAT", "mp3");
            _env?.Set("ENABLE_TTS", "true");

            _isLoaded = true;
            TriggerSave(); 
            StatusText.Text = "Defaults restored.";
            AppendLog("Settings reset to defaults.");
        }
    }
    
    private void OpenOverlay_Click(object sender, RoutedEventArgs e) => OpenUrl($"http://localhost:{_port}/overlay");
    private void OpenTikTok_Click(object sender, RoutedEventArgs e) => OpenUrl("https://tiktok.com/@craigybabyj_new");
    private void OpenDiscord_Click(object sender, RoutedEventArgs e) => OpenUrl("https://discord.gg/F7HYUB2uGu");
    private void OpenWeb_Click(object sender, RoutedEventArgs e) => OpenUrl("https://www.craigybabyj.com");

    private void OpenUrl(string url)
    {
        try { Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true }); } catch { }
    }
}

using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
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
    private int _port = 5000;
    private DispatcherTimer _saveTimer;
    
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
            _port = _env?.GetInt("PORT", 5000) ?? 5000;
            AppendLog($"Server running on port {_port}");
        }

        LoadSettings();
    }

    private void MainWindow_Closing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        SaveSettings();
    }

    private void AppendLog(string message)
    {
        // Debug log file disabled by user request
        /*
        try 
        {
             File.AppendAllText("debug.log", $"[{DateTime.Now:HH:mm:ss}] {message}\n");
        }
        catch {}
        */

        Dispatcher.Invoke(() =>
        {
            if (EventsLog != null)
            {
                EventsLog.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}\n");
                EventsLog.ScrollToEnd();
            }
        });
    }

    private void LoadSettings()
    {
        _env?.Load();

        _port = _env?.GetInt("PORT", 5000) ?? 5000;

        if (DingCheck != null) 
            DingCheck.IsChecked = _env?.GetBool("ENABLE_DINGDONG", false) ?? false;
        
        if (LogCheck != null)
        {
            var showLogs = _env?.GetBool("SHOW_EVENTS_LOG", true) ?? true;
            LogCheck.IsChecked = showLogs;
            if (EventsGroup != null) EventsGroup.Visibility = showLogs ? Visibility.Visible : Visibility.Collapsed;
        }

        var preset = _env?.Get("EFFECT_PRESET", "none") ?? "none";
        if (EffectsPanel != null)
        {
            foreach (var child in EffectsPanel.Children)
            {
                if (child is RadioButton rb && rb.Tag?.ToString() == preset)
                {
                    rb.IsChecked = true;
                    break;
                }
            }
        }
        
        if (StaticOnlyCheck != null)
            StaticOnlyCheck.IsChecked = _env?.GetBool("ADD_STATIC_NOISE", false) ?? false;
        
        var noiseLevel = _env?.GetDouble("STATIC_NOISE_LEVEL", 0.0) ?? 0.0;
        if (NoiseSlider != null)
            NoiseSlider.Value = noiseLevel * 100.0; // 0.0-1.0 -> 0-100
    }

    private void SaveSettings()
    {
        if (_env == null) return;
        
        _env.Set("ENABLE_DINGDONG", DingCheck?.IsChecked == true ? "true" : "false");
        _env.Set("SHOW_EVENTS_LOG", LogCheck?.IsChecked == true ? "true" : "false");
        
        string preset = "none";
        if (EffectsPanel != null)
        {
            foreach (var child in EffectsPanel.Children)
            {
                if (child is RadioButton rb && rb.IsChecked == true)
                {
                    preset = rb.Tag?.ToString() ?? "none";
                    break;
                }
            }
        }
        _env.Set("EFFECT_PRESET", preset);
        _env.Set("ADD_STATIC_NOISE", StaticOnlyCheck?.IsChecked == true ? "true" : "false");
        
        double noiseVal = (NoiseSlider?.Value ?? 0) / 100.0;
        _env.Set("STATIC_NOISE_LEVEL", noiseVal.ToString());
        _env.Set("RADIO_NOISE_LEVEL", noiseVal.ToString());
        _env.Set("WIND_NOISE_LEVEL", noiseVal.ToString());
    }

    private void BroadcastSettings()
    {
        _env?.Load();
        var enableTts = _env?.GetBool("ENABLE_TTS", true) ?? true;
        var addStaticNoise = _env?.GetBool("ADD_STATIC_NOISE", false) ?? false;
        var preset = _env?.Get("EFFECT_PRESET", "none") ?? "none";
        var noiseLevel = _env?.GetDouble("STATIC_NOISE_LEVEL", 0.0) ?? 0.0;

        var settingsPayload = new
        {
            type = "settings",
            enable_tts = enableTts,
            enable_dingdong = DingCheck?.IsChecked == true,
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
        
        if (StatusText != null) StatusText.Text = "Settings saved.";
    }

    private void SaveTimer_Tick(object? sender, EventArgs e)
    {
        _saveTimer.Stop();
        SaveSettings();
        BroadcastSettings();
    }

    private void TriggerSave()
    {
        _saveTimer.Stop();
        _saveTimer.Start();
    }

    // Event Handlers referenced in XAML

    private void OpenSettings_Click(object sender, RoutedEventArgs e)
    {
        var settingsWin = new SettingsWindow(_env);
        settingsWin.Owner = this;
        if (settingsWin.ShowDialog() == true)
        {
            LoadSettings();
            BroadcastSettings();
        }
    }

    private void OpenTikTok_Click(object sender, RoutedEventArgs e) => OpenUrl("https://tiktok.com");
    private void OpenDiscord_Click(object sender, RoutedEventArgs e) => OpenUrl("https://discord.com");
    private void OpenWeb_Click(object sender, RoutedEventArgs e) => OpenUrl("https://google.com"); // Placeholder

    private void OpenUrl(string url)
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); } catch { }
    }

    private void StaticOnly_Checked(object sender, RoutedEventArgs e) => TriggerSave();
    private void StaticOnly_Unchecked(object sender, RoutedEventArgs e) => TriggerSave();

    private void Effect_Checked(object sender, RoutedEventArgs e) => TriggerSave();

    private void NoiseSlider_ValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (NoiseValue != null) NoiseValue.Text = Math.Round(e.NewValue).ToString();
        TriggerSave();
    }

    private void Setting_Changed(object sender, RoutedEventArgs e) => TriggerSave();

    private void LogCheck_CheckedChanged(object sender, RoutedEventArgs e)
    {
        if (EventsGroup != null) 
            EventsGroup.Visibility = (LogCheck?.IsChecked == true) ? Visibility.Visible : Visibility.Collapsed;
        TriggerSave();
    }

    private void ResetDefaults_Click(object sender, RoutedEventArgs e)
    {
        if (MessageBox.Show("Reset all settings to default?", "Confirm", MessageBoxButton.YesNo) == MessageBoxResult.Yes)
        {
            // Simple reset: delete env vars or just set known defaults
            _env?.Set("PORT", "5000");
            _env?.Set("ENABLE_TTS", "true");
            _env?.Set("EFFECT_PRESET", "none");
            _env?.Set("STATIC_NOISE_LEVEL", "0");
            LoadSettings();
            BroadcastSettings();
        }
    }

    private void OpenOverlay_Click(object sender, RoutedEventArgs e)
    {
        OpenUrl($"http://localhost:{_port}/overlay");
    }

    private void OpenHue_Click(object sender, RoutedEventArgs e)
    {
        // Simple hue cycle for now
        var current = _env?.GetInt("OVERLAY_HUE_DEG", 0) ?? 0;
        var newHue = (current + 45) % 360;
        _env?.Set("OVERLAY_HUE_DEG", newHue.ToString());
        _voteService?.Broadcast("theme", new { type = "theme", hue_deg = newHue });
        AppendLog($"Hue changed to {newHue}°");
    }

    private void EditQuotes_Click(object sender, RoutedEventArgs e)
    {
        try { Process.Start(new ProcessStartInfo("notepad.exe", "quotes.json") { UseShellExecute = true }); } catch { }
    }

    private void ClearCache_Click(object sender, RoutedEventArgs e)
    {
        if (MessageBox.Show("Clear audio cache?", "Confirm", MessageBoxButton.YesNo) == MessageBoxResult.Yes)
        {
             // Delete mp3/wav files in audio_cache
             try
             {
                 var path = Path.Combine(AppContext.BaseDirectory, "audio_cache");
                 if (Directory.Exists(path))
                 {
                     int count = 0;
                     foreach (var file in Directory.GetFiles(path, "quote_*.*"))
                     {
                         try 
                         {
                             File.Delete(file);
                             count++;
                         }
                         catch { /* ignore locked files */ }
                     }
                     AppendLog($"Audio cache cleared. Removed {count} files.");
                 }
                 else
                 {
                     AppendLog("Cache directory not found.");
                 }
             }
             catch (Exception ex)
             {
                  AppendLog($"Error clearing cache: {ex.Message}");
             }
        }
    }

    private async void Vote_Click(object sender, RoutedEventArgs e)
    {
        if (_voteService == null || _quoteService == null) return;

        if (sender is Button btn && int.TryParse(btn.Tag?.ToString(), out int score))
        {
            score = Math.Clamp(score, 1, 10);
            var (quote, message) = _quoteService.GetQuote(score);
            var tier = _quoteService.GetTier(score);

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
}

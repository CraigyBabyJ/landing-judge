using System;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using System.Windows.Media;
using LandingJudge.Services;
using Amazon.Polly;
using Amazon.Polly.Model;
using Amazon;
using System.Speech.Synthesis;
using EdgeTTS;
using System.Threading.Tasks;

namespace LandingJudge;

public partial class SettingsWindow : Window
{
    private readonly EnvService? _env;

    public SettingsWindow(EnvService? env)
    {
        InitializeComponent();
        _env = env;
        LoadSettings();
    }

    private async void ProviderCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateVisibility();
        await LoadVoicesForProviderAsync();
    }

    private void UpdateVisibility()
    {
        if (AwsSettingsPanel == null) return;
        var provider = (ProviderCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "AWS";
        AwsSettingsPanel.Visibility = (provider == "System" || provider == "Edge") ? Visibility.Collapsed : Visibility.Visible;
    }

    private void LoadSettings()
    {
        _env?.Load();

        PortBox.Text = _env?.Get("PORT", "5000") ?? "5000";

        var provider = _env?.Get("TTS_PROVIDER", "Edge") ?? "Edge";
        ProviderCombo.SelectedItem = ProviderCombo.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(i => i.Tag?.ToString() == provider) 
            ?? ProviderCombo.Items.OfType<ComboBoxItem>().First();

        UpdateVisibility();
        _ = LoadVoicesForProviderAsync();

        var region = _env?.Get("AWS_REGION", "us-east-1") ?? "us-east-1";
        RegionCombo.SelectedItem = RegionCombo.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(i => string.Equals(i.Content?.ToString(), region, StringComparison.OrdinalIgnoreCase))
            ?? RegionCombo.Items.OfType<ComboBoxItem>().First();

        var savedVoice = _env?.Get("POLLY_VOICE_ID", "en-GB-MaisieNeural") ?? "en-GB-MaisieNeural";
        
        // After loading voices (async), we might need to select it. 
        // Since LoadVoicesForProviderAsync is async, we might race here.
        // For simplicity, we trust LoadVoicesForProviderAsync will be called or we set it if items exist.
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        if (_env == null)
        {
            Close();
            return;
        }

        if (int.TryParse(PortBox.Text, out var parsedPort) && parsedPort > 0 && parsedPort < 65536)
        {
            _env.Set("PORT", parsedPort.ToString());
        }

        var provider = (ProviderCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "AWS";
        var region = (RegionCombo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "us-east-1";
        var format = (FormatCombo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "mp3";
        
        string voiceId = "Joanna";
        if (VoiceCombo.SelectedItem is VoiceViewModel vvm)
        {
            voiceId = vvm.Id;
        }
        else if (VoiceCombo.SelectedItem is ComboBoxItem cbi)
        {
             voiceId = cbi.Tag?.ToString() ?? cbi.Content?.ToString() ?? "Joanna";
        }
        else if (!string.IsNullOrEmpty(VoiceCombo.Text))
        {
            voiceId = VoiceCombo.Text;
        }

        _env.Set("TTS_PROVIDER", provider);
        _env.Set("ENABLE_TTS", TtsCheck.IsChecked == true ? "true" : "false");
        _env.Set("AWS_REGION", region);
        _env.Set("POLLY_VOICE_ID", voiceId);
        _env.Set("POLLY_OUTPUT_FORMAT", format);
        _env.Set("AWS_ACCESS_KEY_ID", KeyBox.Text?.Trim() ?? "");
        _env.Set("AWS_SECRET_ACCESS_KEY", SecretBox.Password?.Trim() ?? "");

        DialogResult = true;
        Close();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        Close();
    }

    private void LoadVoices_Click(object sender, RoutedEventArgs e)
    {
        _ = LoadVoicesForProviderAsync();
    }

    private async Task LoadVoicesForProviderAsync()
    {
        var provider = (ProviderCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "AWS";
        VoiceCombo.Items.Clear();

        if (provider == "System")
        {
            using var synth = new SpeechSynthesizer();
            foreach (var v in synth.GetInstalledVoices())
            {
                var name = v.VoiceInfo.Name;
                VoiceCombo.Items.Add(new VoiceViewModel { Name = name, Id = name, FlagPath = GetFlagPath(v.VoiceInfo.Culture.Name) });
            }
        }
        else if (provider == "Edge")
        {
            try
            {
                var commonEdgeVoices = new[] 
                {
                    "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural", "en-US-EricNeural",
                    "en-GB-SoniaNeural", "en-GB-RyanNeural", "en-GB-LibbyNeural",
                    "en-AU-NatashaNeural", "en-AU-WilliamNeural",
                    "fr-FR-DeniseNeural", "fr-FR-HenriNeural",
                    "de-DE-KatjaNeural", "de-DE-ConradNeural",
                    "es-ES-ElviraNeural", "es-ES-AlvaroNeural",
                    "it-IT-ElsaNeural", "it-IT-IsabellaNeural",
                    "ja-JP-NanamiNeural", "ja-JP-KeitaNeural",
                    "ko-KR-SunHiNeural", "ko-KR-InJoonNeural",
                    "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"
                };

                foreach (var v in commonEdgeVoices)
                {
                    // Extract locale from name (e.g. en-US from en-US-AriaNeural)
                    var parts = v.Split('-');
                    string locale = parts.Length >= 2 ? $"{parts[0]}-{parts[1]}" : "en-US";
                    
                    VoiceCombo.Items.Add(new VoiceViewModel { Name = v, Id = v, FlagPath = GetFlagPath(locale) });
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Failed to load Edge voices: {ex.Message}");
            }
        }
        else // AWS
        {
            var commonVoices = new[] { "Joanna", "Matthew", "Ivy", "Justin", "Kendra", "Joey", "Salli", "Kimberly" };
            foreach (var v in commonVoices)
            {
                VoiceCombo.Items.Add(new VoiceViewModel { Name = v, Id = v, FlagPath = GetFlagPath("en-US") });
            }
        }
        
        // Restore selection
        if (_env != null)
        {
             var savedVoice = _env.Get("POLLY_VOICE_ID", "en-GB-MaisieNeural");
             var match = VoiceCombo.Items.OfType<VoiceViewModel>().FirstOrDefault(i => i.Id == savedVoice);
             if (match != null)
             {
                 VoiceCombo.SelectedItem = match;
             }
             else if (VoiceCombo.Items.Count > 0)
             {
                 VoiceCombo.SelectedIndex = 0;
             }
        }
        else if (VoiceCombo.Items.Count > 0) 
        {
            VoiceCombo.SelectedIndex = 0;
        }
    }

    private string GetFlagPath(string locale)
    {
        // Simple mapping from locale to flag code
        // locale example: en-US, fr-FR
        if (string.IsNullOrEmpty(locale)) return "pack://application:,,,/wwwroot/static/icons/earth.png";

        var countryCode = locale.Split('-').Last().ToLower();
        
        // Handle special cases or default
        if (countryCode == "en") countryCode = "us"; // Default English to US flag if generic
        
        // Mappings for specific overrides if needed
        if (locale.StartsWith("en-GB")) countryCode = "gb";
        if (locale.StartsWith("en-AU")) countryCode = "au";
        
        return $"pack://application:,,,/wwwroot/static/flags/{countryCode}.png";
    }

    public class VoiceViewModel
    {
        public string Name { get; set; } = "";
        public string Id { get; set; } = "";
        public string FlagPath { get; set; } = "";
        
        public override string ToString() => Name;
    }
}

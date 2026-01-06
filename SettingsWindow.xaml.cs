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
        var provider = (ProviderCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "Edge";
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

        TtsCheck.IsChecked = _env?.GetBool("ENABLE_TTS", true) ?? true;
        KeyBox.Text = _env?.Get("AWS_ACCESS_KEY_ID", "") ?? "";
        SecretBox.Password = _env?.Get("AWS_SECRET_ACCESS_KEY", "") ?? "";

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

        var provider = (ProviderCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "Edge";
        var region = (RegionCombo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "us-east-1";
        
        string voiceId = "Joanna";
        if (VoiceCombo.SelectedItem is VoiceViewModel vvm)
        {
            voiceId = vvm.Id;
        }
        else
        {
             // Fallback or default if selection is invalid
             var saved = _env.Get("POLLY_VOICE_ID", "Joanna");
             // If the box is empty, keep the saved one, or default to Joanna
             voiceId = !string.IsNullOrEmpty(saved) ? saved : "Joanna";
        }

        _env.Set("TTS_PROVIDER", provider);
        _env.Set("ENABLE_TTS", TtsCheck.IsChecked == true ? "true" : "false");
        _env.Set("AWS_REGION", region);
        _env.Set("POLLY_VOICE_ID", voiceId);
        _env.Set("POLLY_OUTPUT_FORMAT", "mp3");
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

    private int GetLocalePriority(string locale)
    {
        if (string.IsNullOrEmpty(locale)) return 100;
        if (locale.StartsWith("en-GB", StringComparison.OrdinalIgnoreCase)) return 1;
        if (locale.StartsWith("en-US", StringComparison.OrdinalIgnoreCase)) return 2;
        if (locale.StartsWith("en-", StringComparison.OrdinalIgnoreCase)) return 3;
        return 10;
    }

    private async Task LoadVoicesForProviderAsync()
    {
        var provider = (ProviderCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "AWS";
        VoiceCombo.Items.Clear();
        var voiceList = new List<VoiceViewModel>();

        if (provider == "System")
        {
            using var synth = new SpeechSynthesizer();
            foreach (var v in synth.GetInstalledVoices())
            {
                var name = v.VoiceInfo.Name;
                var locale = v.VoiceInfo.Culture.Name;
                voiceList.Add(new VoiceViewModel { Name = name, Id = name, FlagPath = GetFlagPath(locale), Locale = locale });
            }
        }
        else if (provider == "Edge")
        {
            try
            {
                // Try dynamic listing
                var voices = await EdgeTTS.VoicesManager.ListVoices();
                if (voices != null && voices.Count > 0)
                {
                    foreach (var v in voices)
                    {
                        voiceList.Add(new VoiceViewModel 
                        { 
                            Name = $"{v.ShortName} ({v.Gender})", 
                            Id = v.ShortName, 
                            FlagPath = GetFlagPath(v.Locale),
                            Locale = v.Locale
                        });
                    }
                }
            }
            catch { /* Ignore and fall back to hardcoded */ }

            if (voiceList.Count == 0)
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
                    
                    voiceList.Add(new VoiceViewModel { Name = v, Id = v, FlagPath = GetFlagPath(locale), Locale = locale });
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Failed to load Edge voices: {ex.Message}");
            }
            }
        }
        else // AWS
        {
            bool loaded = false;
            try
            {
                var regionStr = (RegionCombo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "us-east-1";
                var regionEndpoint = RegionEndpoint.GetBySystemName(regionStr);
                
                AmazonPollyClient client;
                var ak = KeyBox.Text.Trim();
                var sk = SecretBox.Password.Trim();
                
                if (!string.IsNullOrEmpty(ak) && !string.IsNullOrEmpty(sk))
                    client = new AmazonPollyClient(ak, sk, regionEndpoint);
                else
                    client = new AmazonPollyClient(regionEndpoint);

                var req = new DescribeVoicesRequest();
                var resp = await client.DescribeVoicesAsync(req);
                
                if (resp.Voices.Count > 0)
                {
                    foreach (var v in resp.Voices)
                    {
                        voiceList.Add(new VoiceViewModel { Name = $"{v.Name} ({v.Gender})", Id = v.Id, FlagPath = GetFlagPath(v.LanguageCode), Locale = v.LanguageCode });
                    }
                    loaded = true;
                }
            }
            catch { /* Fallback */ }

            if (!loaded)
            {
                var commonVoices = new[] { "Joanna", "Matthew", "Ivy", "Justin", "Kendra", "Joey", "Salli", "Kimberly" };
                foreach (var v in commonVoices)
                {
                    voiceList.Add(new VoiceViewModel { Name = v, Id = v, FlagPath = GetFlagPath("en-US"), Locale = "en-US" });
                }
            }
        }
        
        // Sort and populate
        var sorted = voiceList
            .OrderBy(v => GetLocalePriority(v.Locale))
            .ThenBy(v => v.Locale)
            .ThenBy(v => v.Name)
            .ToList();

        foreach (var v in sorted)
        {
            VoiceCombo.Items.Add(v);
        }
        
        // Restore selection
        if (VoiceCombo.Items.Count > 0)
        {
            VoiceViewModel? match = null;
            
            // 1. Try saved voice
            var savedVoice = _env?.Get("POLLY_VOICE_ID");
            if (!string.IsNullOrEmpty(savedVoice))
            {
                match = VoiceCombo.Items.OfType<VoiceViewModel>().FirstOrDefault(i => i.Id == savedVoice);
            }

            // 2. If Edge and no match (or no saved voice), try "Maisie"
            if (match == null && provider == "Edge")
            {
                 match = VoiceCombo.Items.OfType<VoiceViewModel>()
                         .FirstOrDefault(i => i.Id.Contains("Maisie", StringComparison.OrdinalIgnoreCase) 
                                           || i.Name.Contains("Maisie", StringComparison.OrdinalIgnoreCase));
            }

            // 3. Fallback to first item
            if (match == null)
            {
                match = VoiceCombo.Items.OfType<VoiceViewModel>().FirstOrDefault();
            }

            if (match != null)
            {
                VoiceCombo.SelectedItem = match;
            }
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
        public string Locale { get; set; } = "";
        
        public override string ToString() => Name;
    }
}

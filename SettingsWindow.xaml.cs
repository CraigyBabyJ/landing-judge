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
        // If items are empty, add the saved one
        if (VoiceCombo.Items.Count == 0)
        {
             VoiceCombo.Items.Add(new ComboBoxItem { Content = savedVoice, Tag = savedVoice, IsSelected = true });
        }
        else
        {
            // Try to match by Tag (ID) or Content (Name)
            var match = VoiceCombo.Items.OfType<ComboBoxItem>().FirstOrDefault(i => (i.Tag?.ToString() ?? i.Content.ToString()) == savedVoice);
            if (match != null) VoiceCombo.SelectedItem = match;
            else VoiceCombo.Text = savedVoice; 
        }

        var format = _env?.Get("POLLY_OUTPUT_FORMAT", "mp3") ?? "mp3";
        FormatCombo.SelectedItem = FormatCombo.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(i => string.Equals(i.Content?.ToString(), format, StringComparison.OrdinalIgnoreCase))
            ?? FormatCombo.Items.OfType<ComboBoxItem>().First();

        TtsCheck.IsChecked = _env?.GetBool("ENABLE_TTS", true) ?? true;

        KeyBox.Text = _env?.Get("AWS_ACCESS_KEY_ID", "") ?? "";
        SecretBox.Password = _env?.Get("AWS_SECRET_ACCESS_KEY", "") ?? "";
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
        if (VoiceCombo.SelectedItem is ComboBoxItem cbi)
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
                VoiceCombo.Items.Add(new ComboBoxItem { Content = name, Tag = name });
            }
        }
        else if (provider == "Edge")
        {
            try
            {
                // Using a hardcoded list of common multilingual voices as EdgeTTS.GetVoices() is not available
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
                    VoiceCombo.Items.Add(new ComboBoxItem { Content = v, Tag = v });
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Failed to load Edge voices: {ex.Message}");
            }
        }
        else // AWS
        {
            // Just add some common ones or leave empty to type in manually
            var commonVoices = new[] { "Joanna", "Matthew", "Ivy", "Justin", "Kendra", "Joey", "Salli", "Kimberly" };
            foreach (var v in commonVoices)
            {
                VoiceCombo.Items.Add(new ComboBoxItem { Content = v, Tag = v });
            }
        }
        
        if (VoiceCombo.Items.Count > 0) 
            VoiceCombo.SelectedIndex = 0;
    }
}

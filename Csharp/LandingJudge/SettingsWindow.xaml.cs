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

        PortBox.Text = _env?.Get("PORT", "5010") ?? "5010";

        var provider = _env?.Get("TTS_PROVIDER", "AWS") ?? "AWS";
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

        var savedVoice = _env?.Get("POLLY_VOICE_ID", "Joanna") ?? "Joanna";
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

    private async void LoadVoices_Click(object sender, RoutedEventArgs e)
    {
        await LoadVoicesForProviderAsync();
    }

    private async Task LoadVoicesForProviderAsync()
    {
        var provider = (ProviderCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "AWS";
        VoiceCombo.Items.Clear();

        if (provider == "System")
        {
            try
            {
                var voices = await Task.Run(() =>
                {
                    using var synth = new SpeechSynthesizer();
                    return synth.GetInstalledVoices()
                        .Where(v => v.Enabled)
                        .OrderByDescending(v => v.VoiceInfo.Culture.Name.StartsWith("en", StringComparison.OrdinalIgnoreCase))
                        .ThenBy(v => v.VoiceInfo.Name)
                        .ToList();
                });

                foreach (var v in voices)
                {
                    var name = v.VoiceInfo.Name.Replace("Microsoft ", "");
                    var display = $"{name} ({v.VoiceInfo.Culture.DisplayName})";
                    var item = BuildVoiceItem(display, v.VoiceInfo.Culture.Name, v.VoiceInfo.Name, display);
                    VoiceCombo.Items.Add(item);
                }

                if (VoiceCombo.Items.Count > 0)
                {
                    VoiceCombo.SelectedIndex = 0;
                    VoiceCombo.IsDropDownOpen = true;
                }
                else
                {
                    VoiceCombo.Items.Add(new ComboBoxItem { Content = "Default", Tag = "Default", IsSelected = true });
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Error loading system voices: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            return;
        }

        if (provider == "Edge")
        {
            try
            {
                var voicesList = await VoicesManager.ListVoices();
                var voices = voicesList
                    .OrderByDescending(v => (v.Locale ?? "").StartsWith("en", StringComparison.OrdinalIgnoreCase))
                    .ThenBy(v => v.FriendlyName ?? v.Name)
                    .ToList();

                foreach (var v in voices)
                {
                    var friendly = (v.FriendlyName ?? v.Name).Replace("Microsoft ", "");
                    var loc = string.IsNullOrWhiteSpace(v.Locale) ? ExtractLocaleFromShortName(v.ShortName) : v.Locale;
                    var display = $"{friendly} ({loc})";
                    var item = BuildVoiceItem(display, loc ?? "", v.ShortName, $"{v.Name} [{loc}]");
                    VoiceCombo.Items.Add(item);
                }

                if (VoiceCombo.Items.Count > 0)
                {
                    VoiceCombo.SelectedIndex = 0;
                    VoiceCombo.IsDropDownOpen = true;
                }
                else
                {
                    VoiceCombo.Items.Add(new ComboBoxItem { Content = "en-US-AriaNeural", Tag = "en-US-AriaNeural", IsSelected = true });
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Error loading Edge voices: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            return;
        }

        try
        {
            string key = KeyBox.Text.Trim();
            string secret = SecretBox.Password.Trim();
            string region = (RegionCombo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "us-east-1";

            if (string.IsNullOrEmpty(key) || string.IsNullOrEmpty(secret))
            {
                VoiceCombo.Items.Add(new ComboBoxItem { Content = "Joanna", Tag = "Joanna", IsSelected = true });
                return;
            }

            var client = new AmazonPollyClient(key, secret, RegionEndpoint.GetBySystemName(region));
            var request = new DescribeVoicesRequest();
            var response = await client.DescribeVoicesAsync(request);

            var voices = response.Voices
                .OrderByDescending(v => (v.LanguageCode?.ToString() ?? "").StartsWith("en", StringComparison.OrdinalIgnoreCase))
                .ThenBy(v => v.LanguageCode?.ToString() ?? string.Empty)
                .ThenBy(v => v.Name ?? string.Empty)
                .ToList();

            foreach (var v in voices)
            {
                var name = (v.Name ?? "").Replace("Microsoft ", "");
                var label = $"{name} ({v.LanguageName})";
                var item = BuildVoiceItem(label, v.LanguageCode, v.Id, $"{v.Name} [{v.LanguageCode}]");
                VoiceCombo.Items.Add(item);
            }

            if (VoiceCombo.Items.Count > 0)
            {
                VoiceCombo.SelectedIndex = 0;
                VoiceCombo.IsDropDownOpen = true;
            }
            else
            {
                VoiceCombo.Items.Add(new ComboBoxItem { Content = "Joanna", Tag = "Joanna", IsSelected = true });
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Error loading voices: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private string NormalizeFlagCode(string locale)
    {
        if (string.IsNullOrWhiteSpace(locale)) return "";
        var lc = locale.Replace("_", "-").ToLowerInvariant();
        var parts = lc.Split('-');

        // Full-locale overrides
        var fullMap = new System.Collections.Generic.Dictionary<string, string>
        {
            // Common AWS/Edge locales
            { "en-us", "us" }, { "en-gb", "gb" }, { "en-au", "au" }, { "en-ca", "ca" }, { "en-nz", "nz" }, { "en-ie", "ie" }, { "en-in", "in" }, { "en-za", "za" },
            { "en-sg", "sg" }, { "en-ph", "ph" }, { "en-ke", "ke" }, { "en-tz", "tz" }, { "en-gh", "gh" }, { "en-ng", "ng" },
            { "es-es", "es" }, { "es-mx", "mx" }, { "es-us", "us" }, { "es-ar", "ar" }, { "es-co", "co" }, { "es-cl", "cl" }, { "es-pe", "pe" }, { "es-uy", "uy" }, { "es-ve", "ve" }, { "es-ec", "ec" }, { "es-pa", "pa" }, { "es-cr", "cr" }, { "es-gt", "gt" }, { "es-hn", "hn" }, { "es-ni", "ni" }, { "es-sv", "sv" }, { "es-do", "do" }, { "es-pr", "pr" }, { "es-bo", "bo" }, { "es-419", "mx" },
            { "fr-fr", "fr" }, { "fr-ca", "ca" }, { "de-de", "de" }, { "it-it", "it" }, { "nl-nl", "nl" }, { "nl-be", "be" },
            { "sv-se", "se" }, { "no-no", "no" }, { "da-dk", "dk" }, { "fi-fi", "fi" }, { "pl-pl", "pl" }, { "tr-tr", "tr" }, { "he-il", "il" },
            { "cs-cz", "cz" }, { "sk-sk", "sk" }, { "ro-ro", "ro" }, { "hu-hu", "hu" }, { "el-gr", "gr" }, { "bg-bg", "bg" }, { "hr-hr", "hr" }, { "sr-rs", "rs" }, { "uk-ua", "ua" }, { "sl-si", "si" }, { "mk-mk", "mk" }, { "sq-al", "al" }, { "bs-ba", "ba" },
            { "ru-ru", "ru" }, { "pt-br", "br" }, { "pt-pt", "pt" }, { "ja-jp", "jp" }, { "ko-kr", "kr" }, { "zh-cn", "cn" }, { "zh-hk", "hk" }, { "zh-tw", "tw" },
            { "yue-hk", "hk" }, { "zh-hans-cn", "cn" }, { "zh-hant-tw", "tw" },
            { "ar-sa", "sa" }, { "ar-ae", "ae" }, { "ar-eg", "eg" }, { "ar-ma", "ma" }, { "ar-qa", "qa" }, { "ar-jo", "jo" }, { "ar-lb", "lb" }, { "ar-kw", "kw" },
            { "hi-in", "in" }, { "bn-in", "in" }, { "bn-bd", "bd" }, { "ta-in", "in" }, { "ta-sg", "sg" }, { "ta-lk", "lk" }, { "ta-my", "my" }, { "te-in", "in" }, { "ml-in", "in" }, { "mr-in", "in" },
            { "ur-pk", "pk" }, { "ur-in", "in" }, { "fa-ir", "ir" }, { "sw-ke", "ke" }, { "sw-tz", "tz" }, { "zu-za", "za" }, { "af-za", "za" },
            { "vi-vn", "vn" }, { "th-th", "th" }, { "id-id", "id" }, { "ms-my", "my" }, { "ms-bn", "bn" },
            { "is-is", "is" }, { "lv-lv", "lv" }, { "lt-lt", "lt" }, { "et-ee", "ee" }, { "ga-ie", "ie" }, { "cy-gb", "gb" }, { "gd-gb", "gb" }, { "mt-mt", "mt" }, { "kk-kz", "kz" }, { "uz-uz", "uz" }, { "az-az", "az" }, { "ka-ge", "ge" }, { "hy-am", "am" }, { "eu-es", "es" }, { "gl-es", "es" }, { "ca-es", "es" }
        };
        if (fullMap.TryGetValue(lc, out var code)) return code;

        // Region-first approach
        if (parts.Length > 1)
        {
            var region = parts.Last();
            if (region.Length == 2) return region;
            if (region == "419") return "mx"; // Latin America
        }

        // Language fallbacks
        var lang = parts[0];
        var langMap = new System.Collections.Generic.Dictionary<string, string>
        {
            { "en", "us" }, { "es", "es" }, { "pt", "pt" }, { "fr", "fr" }, { "de", "de" }, { "it", "it" }, { "nl", "nl" }, { "sv", "se" }, { "no", "no" }, { "da", "dk" }, { "fi", "fi" }, { "pl", "pl" }, { "tr", "tr" }, { "he", "il" },
            { "cs", "cz" }, { "sk", "sk" }, { "ro", "ro" }, { "hu", "hu" }, { "el", "gr" }, { "bg", "bg" }, { "hr", "hr" }, { "sr", "rs" }, { "uk", "ua" },
            { "ru", "ru" }, { "ja", "jp" }, { "ko", "kr" }, { "zh", "cn" }, { "ar", "sa" }, { "arb", "sa" }, { "hi", "in" }, { "bn", "bd" }, { "ta", "in" }, { "te", "in" }, { "ml", "in" }, { "mr", "in" }, { "ur", "pk" },
            { "fa", "ir" }, { "sw", "tz" }, { "zu", "za" }, { "af", "za" }, { "vi", "vn" }, { "th", "th" }, { "id", "id" }, { "ms", "my" }
        };
        if (langMap.TryGetValue(lang, out var langCode)) return langCode;

        return "";
    }

    private ComboBoxItem BuildVoiceItem(string display, string locale, string tag, string tooltip)
    {
        var item = new ComboBoxItem();
        var panel = new StackPanel { Orientation = Orientation.Horizontal };
        var code = NormalizeFlagCode(locale);
        var flagPath = string.IsNullOrEmpty(code) ? "" : Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "wwwroot", "static", "flags", $"{code}.png");

        if (!string.IsNullOrEmpty(flagPath) && !File.Exists(flagPath))
        {
            var synonyms = new System.Collections.Generic.Dictionary<string, string>
            {
                { "gb", "uk" }, { "kr", "ko" }, { "jp", "ja" }, { "cn", "zh" }, { "sa", "ar" }, { "ua", "uk" }
            };
            if (synonyms.TryGetValue(code, out var alt))
            {
                var altPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "wwwroot", "static", "flags", $"{alt}.png");
                if (File.Exists(altPath)) flagPath = altPath;
            }
        }

        if (!string.IsNullOrEmpty(flagPath) && File.Exists(flagPath))
        {
            var img = new Image
            {
                Source = new BitmapImage(new Uri(flagPath)),
                Width = 20,
                Margin = new Thickness(0, 0, 5, 0)
            };
            panel.Children.Add(img);
        }
        else if (!string.IsNullOrEmpty(code))
        {
            var badge = new Border
            {
                Background = (Brush)new BrushConverter().ConvertFromString("#2F3A4F"),
                CornerRadius = new CornerRadius(3),
                Margin = new Thickness(0, 0, 5, 0),
                Padding = new Thickness(3, 1, 3, 1)
            };
            var tb = new TextBlock
            {
                Text = code.ToUpperInvariant(),
                Foreground = Brushes.White,
                FontSize = 11,
                VerticalAlignment = VerticalAlignment.Center
            };
            badge.Child = tb;
            panel.Children.Add(badge);
        }
        panel.Children.Add(new TextBlock { Text = display, VerticalAlignment = VerticalAlignment.Center });
        item.Content = panel;
        item.Tag = tag;
        item.ToolTip = tooltip;
        return item;
    }

    private string ExtractLocaleFromShortName(string shortName)
    {
        if (string.IsNullOrWhiteSpace(shortName)) return "";
        var parts = shortName.Split('-');
        if (parts.Length >= 2)
        {
            var lang = parts[0];
            var region = parts[1];
            return $"{lang}-{region}";
        }
        return "";
    }
}

using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace LandingJudge.Services;

public class QuoteService
{
    private Dictionary<string, List<string>> _quotes = new();
    private Dictionary<string, string> _messages = new();
    private readonly Random _rng = new();

    public QuoteService()
    {
        LoadQuotes();
    }

    public void LoadQuotes()
    {
        var basePath = AppContext.BaseDirectory;
        var path = Path.Combine(basePath, "quotes.json");
        
        // If quotes.json doesn't exist, try to extract default from embedded resources
        if (!File.Exists(path))
        {
            try
            {
                var assembly = System.Reflection.Assembly.GetEntryAssembly();
                using var stream = assembly?.GetManifestResourceStream("LandingJudge.quotes.default.json");
                if (stream != null)
                {
                    using var reader = new StreamReader(stream);
                    var defaultJson = reader.ReadToEnd();
                    File.WriteAllText(path, defaultJson);
                }
            }
            catch { /* Ignore extraction error */ }
        }

        if (File.Exists(path))
        {
            try 
            {
                var json = File.ReadAllText(path);
                var root = JsonSerializer.Deserialize<QuoteRoot>(json);
                if (root != null)
                {
                    _quotes = root.Quotes ?? new();
                    _messages = root.Messages ?? new();
                }
            }
            catch { /* Log error */ }
        }
    }

    public string GetTier(int score)
    {
        if (score <= 3) return "bad";
        if (score <= 6) return "ok";
        if (score <= 8) return "good";
        return "great";
    }

    public (string Quote, string Message) GetQuote(int score)
    {
        var s = score.ToString();
        string quote = "";
        if (_quotes.TryGetValue(s, out var list) && list.Count > 0)
        {
            quote = list[_rng.Next(list.Count)];
        }
        
        string message = "";
        if (_messages.TryGetValue(s, out var msg))
        {
            message = msg;
        }

        return (quote, message);
    }

    private class QuoteRoot
    {
        [JsonPropertyName("quotes")]
        public Dictionary<string, List<string>>? Quotes { get; set; }
        
        [JsonPropertyName("messages")]
        public Dictionary<string, string>? Messages { get; set; }
    }
}

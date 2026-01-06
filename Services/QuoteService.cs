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
        if (!File.Exists(path)) path = Path.Combine(basePath, "quotes.default.json");
        
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
        
        // If empty, load default as fallback if primary was missing/corrupt
        var defaultPath = Path.Combine(basePath, "quotes.default.json");
        if ((_quotes.Count == 0 || _messages.Count == 0) && File.Exists(defaultPath) && path != defaultPath)
        {
             try 
            {
                var json = File.ReadAllText(defaultPath);
                var root = JsonSerializer.Deserialize<QuoteRoot>(json);
                if (root != null)
                {
                    if (_quotes.Count == 0) _quotes = root.Quotes ?? new();
                    if (_messages.Count == 0) _messages = root.Messages ?? new();
                }
            }
            catch { }
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

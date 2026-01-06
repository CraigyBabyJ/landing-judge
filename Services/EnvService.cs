using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace LandingJudge.Services;

public class EnvService
{
    private readonly Dictionary<string, string> _values = new();
    private readonly string? _envPath;

    public EnvService()
    {
        _envPath = FindEnvPath();
        Load();
    }

    private string? FindEnvPath()
    {
        var current = AppContext.BaseDirectory;
        for (int i = 0; i < 10; i++)
        {
            var path = Path.Combine(current, ".env");
            if (File.Exists(path))
            {
                return path;
            }
            var parent = Directory.GetParent(current);
            if (parent == null) break;
            current = parent.FullName;
        }
        return null;
    }

    public void Load()
    {
        _values.Clear();

        if (_envPath != null && File.Exists(_envPath))
        {
            foreach (var line in File.ReadAllLines(_envPath))
            {
                ParseLine(line);
            }
        }
    }

    private void ParseLine(string line)
    {
        var trimmed = line.Trim();
        if (string.IsNullOrEmpty(trimmed) || trimmed.StartsWith("#")) return;

        var parts = trimmed.Split('=', 2);
        if (parts.Length == 2)
        {
            var key = parts[0].Trim();
            var val = parts[1].Trim();
            if (val.StartsWith("\"") && val.EndsWith("\""))
            {
                val = val.Substring(1, val.Length - 2);
            }
            else if (val.StartsWith("'") && val.EndsWith("'"))
            {
                val = val.Substring(1, val.Length - 2);
            }
            _values[key] = val;
        }
    }

    public string Get(string key, string defaultValue = "")
    {
        return _values.TryGetValue(key, out var val) ? val : defaultValue;
    }

    public int GetInt(string key, int defaultValue = 0)
    {
        var v = Get(key, defaultValue.ToString());
        return int.TryParse(v, out var parsed) ? parsed : defaultValue;
    }

    public double GetDouble(string key, double defaultValue = 0)
    {
        var v = Get(key, defaultValue.ToString());
        return double.TryParse(v, out var parsed) ? parsed : defaultValue;
    }

    public bool GetBool(string key, bool defaultValue = false)
    {
        var val = Get(key);
        if (string.IsNullOrEmpty(val)) return defaultValue;
        val = val.ToLowerInvariant();
        return val == "1" || val == "true" || val == "yes" || val == "on";
    }

    public void Set(string key, string value)
    {
        _values[key] = value;
        Persist();
    }

    private void Persist()
    {
        if (string.IsNullOrWhiteSpace(_envPath)) return;

        try
        {
            if (!File.Exists(_envPath))
            {
                File.WriteAllLines(_envPath, _values.Select(kvp => $"{kvp.Key}={kvp.Value}"));
                return;
            }

            var lines = File.ReadAllLines(_envPath).ToList();
            var keys = new HashSet<string>(_values.Keys, StringComparer.OrdinalIgnoreCase);

            for (int i = 0; i < lines.Count; i++)
            {
                var trimmed = lines[i].Trim();
                if (string.IsNullOrEmpty(trimmed) || trimmed.StartsWith("#")) continue;
                var parts = trimmed.Split('=', 2);
                if (parts.Length != 2) continue;
                var key = parts[0].Trim();
                if (keys.Contains(key))
                {
                    lines[i] = $"{key}={_values[key]}";
                    keys.Remove(key);
                }
            }

            foreach (var missing in keys)
            {
                lines.Add($"{missing}={_values[missing]}");
            }

            File.WriteAllLines(_envPath, lines);
        }
        catch
        {
            // Swallow errors; best-effort persistence.
        }
    }
}

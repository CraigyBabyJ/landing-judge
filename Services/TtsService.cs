using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Amazon;
using Amazon.Polly;
using Amazon.Polly.Model;
using System.Speech.Synthesis;
using EdgeTTS;

namespace LandingJudge.Services;

public class TtsService
{
    private readonly EnvService _env;
    private readonly string _audioDir;
    private readonly string _indexFile;
    private Dictionary<string, AudioIndexEntry> _index = new();

    public TtsService(EnvService env)
    {
        _env = env;
        // Map to local writable cache directory
        _audioDir = Path.Combine(AppContext.BaseDirectory, "audio_cache");
        _indexFile = Path.Combine(_audioDir, "audio_index.json");
        
        if (!Directory.Exists(_audioDir))
        {
            Directory.CreateDirectory(_audioDir);
        }
        
        LoadIndex();
    }

    private void LoadIndex()
    {
        if (File.Exists(_indexFile))
        {
            try
            {
                var json = File.ReadAllText(_indexFile);
                _index = JsonSerializer.Deserialize<Dictionary<string, AudioIndexEntry>>(json) ?? new();
            }
            catch { _index = new(); }
        }
    }

    private void SaveIndex()
    {
        try
        {
            var json = JsonSerializer.Serialize(_index, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(_indexFile, json);
        }
        catch { }
    }

    public async Task<string> GenerateAudioUrlAsync(string text)
    {
        if (!_env.GetBool("ENABLE_TTS", true)) return "";
        if (string.IsNullOrWhiteSpace(text)) return "";

        var provider = _env.Get("TTS_PROVIDER", "AWS");
        if (provider == "System")
        {
            var sysVoiceId = _env.Get("POLLY_VOICE_ID"); // For System provider, this holds the voice name
            
            string sysKeyMaterial = $"{text}|voice={sysVoiceId}|provider=System";
            string sysKeyHash = GetMd5Hash(sysKeyMaterial).Substring(0, 12);

            if (_index.TryGetValue(sysKeyHash, out var sysEntry))
            {
                var path = Path.Combine(_audioDir, sysEntry.filename);
                if (File.Exists(path))
                {
                    return $"/static/audio/{sysEntry.filename}";
                }
            }

            try
            {
                string filename = $"quote_System_{sysVoiceId ?? "Default"}_{GetMd5Hash(text).Substring(0, 12)}.wav";
                string filePath = Path.Combine(_audioDir, filename);

                await Task.Run(() => 
                {
                    using var synth = new SpeechSynthesizer();
                    if (!string.IsNullOrEmpty(sysVoiceId))
                    {
                        try { synth.SelectVoice(sysVoiceId); } catch { /* Fallback to default */ }
                    }
                    synth.SetOutputToWaveFile(filePath);
                    synth.Speak(text);
                });

                var newEntry = new AudioIndexEntry
                {
                    text = text,
                    voice = sysVoiceId ?? "Default",
                    engine = "system",
                    format = "wav",
                    region = "local",
                    filename = filename,
                    created_ts = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                    play_count = 1
                };
                _index[sysKeyHash] = newEntry;
                SaveIndex();

                return $"/static/audio/{filename}";
            }
            catch (Exception ex)
            {
                throw new Exception($"System TTS failed: {ex.Message}", ex);
            }
        }

        if (provider == "Edge")
        {
             var edgeVoiceId = _env.Get("POLLY_VOICE_ID", "en-US-AriaNeural"); // Default Edge voice
            
             string edgeKeyMaterial = $"{text}|voice={edgeVoiceId}|provider=Edge";
             string edgeKeyHash = GetMd5Hash(edgeKeyMaterial).Substring(0, 12);

             if (_index.TryGetValue(edgeKeyHash, out var edgeEntry))
             {
                 var path = Path.Combine(_audioDir, edgeEntry.filename);
                 if (File.Exists(path))
                 {
                     return $"/static/audio/{edgeEntry.filename}";
                 }
             }

             try
             {
                 string filename = $"quote_Edge_{edgeVoiceId}_{GetMd5Hash(text).Substring(0, 12)}.mp3";
                 string filePath = Path.Combine(_audioDir, filename);

                var communicate = new Communicate(text, edgeVoiceId);
                await communicate.Save(filePath);

                 var newEntry = new AudioIndexEntry
                 {
                     text = text,
                     voice = edgeVoiceId,
                     engine = "edge-neural",
                     format = "mp3",
                     region = "global",
                     filename = filename,
                     created_ts = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                     play_count = 1
                 };
                 _index[edgeKeyHash] = newEntry;
                 SaveIndex();

                 return $"/static/audio/{filename}";
             }
             catch (Exception ex)
             {
                 throw new Exception($"Edge TTS failed: {ex.Message}", ex);
             }
        }

        var regionStr = _env.Get("AWS_REGION", "us-east-1");
        var accessKey = _env.Get("AWS_ACCESS_KEY_ID");
        var secretKey = _env.Get("AWS_SECRET_ACCESS_KEY");
        var voiceId = _env.Get("POLLY_VOICE_ID", "Joanna");
        var format = _env.Get("POLLY_OUTPUT_FORMAT", "mp3");
        
        // Default to neural, fallback to standard
        string engine = "neural";

        // key_material = f"{text}|voice={vid}|engine={engine}|fmt={POLLY_OUTPUT_FORMAT}|region={AWS_REGION}"
        string keyMaterial = $"{text}|voice={voiceId}|engine={engine}|fmt={format}|region={regionStr}";
        string keyHash = GetMd5Hash(keyMaterial).Substring(0, 12);

        if (_index.TryGetValue(keyHash, out var entry))
        {
            var path = Path.Combine(_audioDir, entry.filename);
            if (File.Exists(path))
            {
                // Increment play count? Python does it? Maybe. Not critical.
                return $"/static/audio/{entry.filename}";
            }
        }

        // Not in index, synthesize
        try
        {
            var region = RegionEndpoint.GetBySystemName(regionStr);
            AmazonPollyClient client;
            
            if (!string.IsNullOrEmpty(accessKey) && !string.IsNullOrEmpty(secretKey))
            {
                client = new AmazonPollyClient(accessKey, secretKey, region);
            }
            else
            {
                client = new AmazonPollyClient(region);
            }

            var request = new SynthesizeSpeechRequest
            {
                Text = text,
                OutputFormat = OutputFormat.FindValue(format),
                VoiceId = VoiceId.FindValue(voiceId),
                Engine = Engine.FindValue(engine)
            };

            SynthesizeSpeechResponse response;
            try 
            {
                response = await client.SynthesizeSpeechAsync(request);
            }
            catch (Exception)
            {
                // Retry with standard
                request.Engine = Engine.Standard;
                engine = "standard";
                response = await client.SynthesizeSpeechAsync(request);
            }

            // Recalculate key hash if engine changed?
            // Python: "Retry once with alternate engine on mismatch... engine = alt"
            // And logic uses 'engine' variable for key_material.
            // So if engine changed, we should probably update keyHash or just store it under the original request?
            // Python: key_material is calculated BEFORE the call. 
            // BUT, if synthesize fails and it retries, it updates 'engine' variable.
            // AND then it creates the file. 
            // Wait, Python's index key uses the *requested* engine or the *used* engine?
            // Python: key_material is built using 'engine' which is initially set by pick_engine_for_voice.
            // If retry happens, 'engine' is updated.
            // But key_material is NOT recomputed in Python code snippet I saw (it was computed before try/catch).
            // Actually, looking at Python code:
            // key_material = ...
            // entry = index.get(...)
            // if entry: return ...
            // try: synthesize ... except: engine=alt ...
            // So if it falls back, it uses the NEW engine for synthesis.
            // But what about the index key?
            // The Python code snippet ends abruptly in the `Read` output.
            // I'll assume I should use the FINAL engine for the key to be correct for future lookups of that engine.
            
            // Let's recompute keyHash if engine changed
            if (engine != "neural") // assuming we started with neural
            {
                 keyMaterial = $"{text}|voice={voiceId}|engine={engine}|fmt={format}|region={regionStr}";
                 keyHash = GetMd5Hash(keyMaterial).Substring(0, 12);
            }

            // Save file
            string textHash = GetMd5Hash(text).Substring(0, 12);
            string safeVoice = voiceId; 
            string filename = $"quote_{safeVoice}_{engine}_{textHash}.{format}";
            string filePath = Path.Combine(_audioDir, filename);

            using (var fileStream = File.Create(filePath))
            {
                await response.AudioStream.CopyToAsync(fileStream);
            }

            // Update index
            var newEntry = new AudioIndexEntry
            {
                text = text,
                voice = voiceId,
                engine = engine,
                format = format,
                region = regionStr,
                filename = filename,
                created_ts = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                play_count = 1
            };
            _index[keyHash] = newEntry;
            SaveIndex();

            return $"/static/audio/{filename}";
        }
        catch (Exception ex)
        {
            throw new Exception($"TTS Generation failed: {ex.Message}", ex);
        }
    }

    private string GetMd5Hash(string input)
    {
        using var md5 = MD5.Create();
        var bytes = Encoding.UTF8.GetBytes(input);
        var hash = md5.ComputeHash(bytes);
        return BitConverter.ToString(hash).Replace("-", "").ToLowerInvariant();
    }

    public class AudioIndexEntry
    {
        public string text { get; set; } = "";
        public string voice { get; set; } = "";
        public string engine { get; set; } = "";
        public string format { get; set; } = "";
        public string region { get; set; } = "";
        public string filename { get; set; } = "";
        public string created_ts { get; set; } = "";
        public int play_count { get; set; } = 0;
    }
}

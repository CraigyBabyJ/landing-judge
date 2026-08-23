using System;
using System.IO;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace LandingJudge.Services;

/// <summary>
/// Minimal Edge "Read Aloud" TTS client. Bypasses the EdgeTTS NuGet package (1.0.3, latest available),
/// which does not send the Sec-MS-GEC anti-bot token Microsoft now requires on the synthesis websocket
/// (the voices-list REST endpoint works without it, which is why that call misleadingly succeeds while
/// every actual synthesis request gets a 403).
/// </summary>
public static class EdgeTtsClient
{
    private const string TrustedClientToken = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
    private const string ChromiumFullVersion = "143.0.3650.75";
    private const string ChromiumMajorVersion = "143";
    private const string SecMsGecVersion = "1-" + ChromiumFullVersion;
    private const string UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/" + ChromiumMajorVersion + ".0.0.0 Safari/537.36 Edg/" + ChromiumMajorVersion + ".0.0.0";
    private const string WssUrl = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=" + TrustedClientToken;

    private static string GenerateSecMsGec()
    {
        // Windows FILETIME epoch (100ns ticks since 1601-01-01), rounded down to the nearest 5 minutes,
        // then hashed with the trusted client token. Required by Microsoft's anti-bot check since 2024.
        const long winEpochSeconds = 11644473600L;
        double unixSeconds = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
        double ticks = unixSeconds + winEpochSeconds;
        ticks -= ticks % 300;
        ticks *= 1e9 / 100.0; // seconds -> 100ns ticks

        string strToHash = $"{ticks:F0}{TrustedClientToken}";
        using var sha256 = SHA256.Create();
        var hash = sha256.ComputeHash(Encoding.ASCII.GetBytes(strToHash));
        var sb = new StringBuilder(hash.Length * 2);
        foreach (var b in hash) sb.Append(b.ToString("X2"));
        return sb.ToString();
    }

    private static string DateToString()
    {
        // e.g. "Mon Jan 01 2024 12:00:00 GMT+0000 (Coordinated Universal Time)"
        var now = DateTime.UtcNow;
        return now.ToString("ddd MMM dd yyyy HH:mm:ss 'GMT+0000 (Coordinated Universal Time)'", System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string EscapeXml(string text) => text
        .Replace("&", "&amp;")
        .Replace("<", "&lt;")
        .Replace(">", "&gt;");

    public static async Task SynthesizeToFileAsync(string text, string voice, string outputPath, CancellationToken token = default)
    {
        var connectionId = Guid.NewGuid().ToString("N");
        var secMsGec = GenerateSecMsGec();
        var url = $"{WssUrl}&ConnectionId={connectionId}&Sec-MS-GEC={secMsGec}&Sec-MS-GEC-Version={SecMsGecVersion}";

        using var ws = new ClientWebSocket();
        ws.Options.SetRequestHeader("Pragma", "no-cache");
        ws.Options.SetRequestHeader("Cache-Control", "no-cache");
        ws.Options.SetRequestHeader("Origin", "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold");
        ws.Options.SetRequestHeader("User-Agent", UserAgent);
        ws.Options.SetRequestHeader("Accept-Encoding", "gzip, deflate, br, zstd");
        ws.Options.SetRequestHeader("Accept-Language", "en-US,en;q=0.9");

        var muid = RandomNumberGenerator.GetHexString(32, false).ToUpperInvariant();
        ws.Options.Cookies = new System.Net.CookieContainer();
        ws.Options.Cookies.Add(new System.Net.Cookie("muid", muid, "/", "speech.platform.bing.com"));

        await ws.ConnectAsync(new Uri(url), token);

        var requestId = Guid.NewGuid().ToString("N");
        var timestamp = DateToString();

        var configMessage =
            $"X-Timestamp:{timestamp}\r\n" +
            "Content-Type:application/json; charset=utf-8\r\n" +
            "Path:speech.config\r\n\r\n" +
            "{\"context\":{\"synthesis\":{\"audio\":{\"metadataoptions\":{" +
            "\"sentenceBoundaryEnabled\":\"false\",\"wordBoundaryEnabled\":\"false\"}," +
            "\"outputFormat\":\"audio-24khz-48kbitrate-mono-mp3\"}}}}";

        var ssml =
            "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
            $"<voice name='{voice}'><prosody pitch='+0Hz' rate='+0%' volume='+0%'>{EscapeXml(text)}</prosody></voice></speak>";

        var ssmlMessage =
            $"X-RequestId:{requestId}\r\n" +
            "Content-Type:application/ssml+xml\r\n" +
            $"X-Timestamp:{timestamp}Z\r\n" +
            "Path:ssml\r\n\r\n" +
            ssml;

        await SendTextAsync(ws, configMessage, token);
        await SendTextAsync(ws, ssmlMessage, token);

        using var audioStream = new MemoryStream();
        var buffer = new byte[16384];

        while (ws.State == WebSocketState.Open)
        {
            using var messageStream = new MemoryStream();
            WebSocketReceiveResult result;
            do
            {
                result = await ws.ReceiveAsync(buffer, token);
                if (result.MessageType == WebSocketMessageType.Close) break;
                messageStream.Write(buffer, 0, result.Count);
            } while (!result.EndOfMessage);

            if (result.MessageType == WebSocketMessageType.Close) break;

            var payload = messageStream.ToArray();

            if (result.MessageType == WebSocketMessageType.Text)
            {
                var text2 = Encoding.UTF8.GetString(payload);
                if (text2.Contains("Path:turn.end"))
                {
                    break;
                }
                if (text2.Contains("Path:response") && text2.Contains("\"status\":\"error\""))
                {
                    throw new Exception($"Edge TTS returned an error response: {text2}");
                }
            }
            else if (result.MessageType == WebSocketMessageType.Binary)
            {
                // Frame layout: 2-byte big-endian header length, then the header text, then raw audio bytes.
                if (payload.Length < 2) continue;
                int headerLen = (payload[0] << 8) | payload[1];
                if (payload.Length < 2 + headerLen) continue;
                var header = Encoding.UTF8.GetString(payload, 2, headerLen);
                if (header.Contains("Path:audio"))
                {
                    audioStream.Write(payload, 2 + headerLen, payload.Length - 2 - headerLen);
                }
            }
        }

        try
        {
            if (ws.State == WebSocketState.Open)
            {
                await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "done", token);
            }
        }
        catch
        {
            // The service often hard-closes the socket right after the final audio frame,
            // before our graceful close handshake completes. We already have the audio
            // at this point, so this is not a real failure.
        }

        if (audioStream.Length == 0)
        {
            throw new Exception("Edge TTS returned no audio data.");
        }

        await File.WriteAllBytesAsync(outputPath, audioStream.ToArray(), token);
    }

    private static Task SendTextAsync(ClientWebSocket ws, string message, CancellationToken token)
    {
        var bytes = Encoding.UTF8.GetBytes(message);
        return ws.SendAsync(bytes, WebSocketMessageType.Text, true, token);
    }
}

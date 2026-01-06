using System.Threading.Channels;

namespace LandingJudge.Services;

public class VoteService
{
    // Event to notify active streams: (eventType, jsonData)
    public event Action<string, string>? OnEvent;

    public void Broadcast(string eventType, object data)
    {
        var json = System.Text.Json.JsonSerializer.Serialize(data);
        OnEvent?.Invoke(eventType, json);
    }
}

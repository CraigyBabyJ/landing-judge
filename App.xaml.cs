using System.IO;
using System.Text.Json;
using System.Threading.Channels;
using System.Windows;
using Microsoft.Extensions.FileProviders;
using System.Reflection;
using LandingJudge.Services;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

namespace LandingJudge;

public partial class App : Application
{
    public static IHost? AppHost { get; private set; }

    private MainWindow? _mainWindow;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        try
        {
            // Prepare audio cache directory
            var audioCachePath = Path.Combine(AppContext.BaseDirectory, "audio_cache");
            Directory.CreateDirectory(audioCachePath);
            // Ensure static/audio structure exists inside cache for consistency if needed, 
            // but we will map /static/audio to audioCachePath directly.

            // ... existing host setup ...
            var builder = Host.CreateDefaultBuilder()
                .ConfigureWebHostDefaults(webBuilder =>
                {
                    // Late-bind Kestrel to port from .env (default 5000)
                    webBuilder.UseKestrel((context, options) =>
                    {
                        var envService = new EnvService();
                        envService.Load();
                        var port = envService.GetInt("PORT", 5000);
                        options.ListenAnyIP(port);
                    });
                    webBuilder.ConfigureServices(services =>
                    {
                        services.AddSingleton<EnvService>();
                        services.AddSingleton<VoteService>();
                        services.AddSingleton<QuoteService>();
                        services.AddSingleton<TtsService>();
                        services.AddCors();
                    });
                    webBuilder.Configure(app =>
                    {
                        app.UseCors(policy => policy.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod());

                        // 1. Embedded Provider (for wwwroot contents embedded in assembly)
                        // This expects wwwroot/file.ext to be mapped to root.
                        var embeddedProvider = new ManifestEmbeddedFileProvider(Assembly.GetEntryAssembly()!, "wwwroot");

                        // 2. Physical Provider (for generated audio files)
                        // We map this specifically to allow TtsService to write files to disk and serve them.
                        var physicalProvider = new PhysicalFileProvider(audioCachePath);

                        // Serve embedded files (e.g. /overlay.html, /static/flags/...)
                        app.UseStaticFiles(new StaticFileOptions
                        {
                            FileProvider = embeddedProvider,
                            RequestPath = ""
                        });

                        // Serve generated audio files at /static/audio
                        app.UseStaticFiles(new StaticFileOptions
                        {
                            FileProvider = physicalProvider,
                            RequestPath = "/static/audio"
                        });
                        
                        app.UseRouting();

                        app.UseEndpoints(endpoints =>
                        {
                            endpoints.MapGet("/overlay", async context =>
                            {
                                context.Response.ContentType = "text/html";
                                var fileInfo = embeddedProvider.GetFileInfo("overlay.html");
                                if (fileInfo.Exists)
                                {
                                    await context.Response.SendFileAsync(fileInfo);
                                }
                                else
                                {
                                    context.Response.StatusCode = 404;
                                }
                            });

                            endpoints.MapGet("/stream", async (HttpContext context, VoteService voteService, CancellationToken ct) =>
                            {
                                context.Response.Headers.Append("Content-Type", "text/event-stream");
                                context.Response.Headers.Append("Cache-Control", "no-cache");
                                context.Response.Headers.Append("Connection", "keep-alive");

                                var channel = Channel.CreateUnbounded<string>();

                                void Handler(string type, string data)
                                {
                                    channel.Writer.TryWrite($"data: {data}\n\n");
                                }

                                voteService.OnEvent += Handler;

                                // Send initial theme/settings snapshot so overlay updates immediately.
                                try
                                {
                                    var env = app.ApplicationServices.GetRequiredService<EnvService>();
                                    env.Load();

                                    var settingsPayload = BuildSettingsPayload(env);
                                    channel.Writer.TryWrite($"data: {JsonSerializer.Serialize(settingsPayload)}\n\n");

                                    var themePayload = BuildThemePayload(env);
                                    channel.Writer.TryWrite($"data: {JsonSerializer.Serialize(themePayload)}\n\n");
                                }
                                catch { /* ignore */ }

                                await context.Response.Body.FlushAsync(ct);

                                try
                                {
                                    while (!ct.IsCancellationRequested)
                                    {
                                        var msg = await channel.Reader.ReadAsync(ct);
                                        await context.Response.WriteAsync(msg, ct);
                                        await context.Response.Body.FlushAsync(ct);
                                    }
                                }
                                catch (OperationCanceledException) { }
                                finally
                                {
                                    voteService.OnEvent -= Handler;
                                }
                            });

                            endpoints.MapPost("/theme", async (HttpContext context, EnvService env) =>
                            {
                                try
                                {
                                    var body = await JsonSerializer.DeserializeAsync<ThemeRequest>(context.Request.Body) ?? new ThemeRequest();
                                    var deg = Math.Clamp(body.hue_deg, 0, 360);
                                    env.Set("OVERLAY_HUE_DEG", deg.ToString());

                                    var payload = BuildThemePayload(env);
                                    var vs = context.RequestServices.GetRequiredService<VoteService>();
                                    vs.Broadcast(payload.type, payload);
                                    return Results.Ok(new { ok = true, hue_deg = deg });
                                }
                                catch (Exception ex)
                                {
                                    return Results.BadRequest(new { ok = false, error = ex.Message });
                                }
                            });

                            endpoints.MapPost("/preview", async (HttpContext context, VoteService voteService) =>
                            {
                                try
                                {
                                    var body = await JsonSerializer.DeserializeAsync<PreviewRequest>(context.Request.Body) ?? new PreviewRequest();
                                    var score = Math.Clamp(body.score, 1, 10);
                                    var payload = new { type = "preview", active = body.active, score = score };
                                    voteService.Broadcast("preview", payload);
                                    return Results.Ok(new { ok = true, active = body.active, score });
                                }
                                catch (Exception ex)
                                {
                                    return Results.BadRequest(new { ok = false, error = ex.Message });
                                }
                            });

                            endpoints.MapGet("/vote/{score:int}", async (int score, VoteService voteService, QuoteService quoteService, TtsService ttsService, EnvService env) =>
                            {
                                env.Load(); // Reload latest changes saved via UI or file edits.

                                if (score < 1) score = 1;
                                if (score > 10) score = 10;

                                var (quote, message) = quoteService.GetQuote(score);
                                var tier = quoteService.GetTier(score);
                                
                                var enableTts = env.GetBool("ENABLE_TTS", true);
                                var enableBell = env.GetBool("ENABLE_DINGDONG", false);
                                var audioUrl = enableTts ? await ttsService.GenerateAudioUrlAsync(quote) : "";

                                int durationMs = env.GetInt("BANNER_DURATION_MS", 8000);

                                // Audio effects / noise levels
                                var effects = new
                                {
                                    static_noise = env.GetBool("ADD_STATIC_NOISE", false),
                                    preset = env.Get("EFFECT_PRESET", "none"),
                                    static_noise_level = env.GetDouble("STATIC_NOISE_LEVEL", 0.0),
                                    radio_noise_level = env.GetDouble("RADIO_NOISE_LEVEL", 0.0),
                                    wind_noise_level = env.GetDouble("WIND_NOISE_LEVEL", 0.0)
                                };

                                var payload = new
                                {
                                    type = "vote",
                                    score = score,
                                    level = tier,
                                    quote = quote,
                                    message = message,
                                    audio_url = audioUrl,
                                    duration_ms = durationMs,
                                    enable_tts = enableTts,
                                    enable_dingdong = enableBell,
                                    effects,
                                    ts = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
                                };

                                voteService.Broadcast("vote", payload);
                                return Results.Ok(payload);
                            });
                            
                            // Default route
                            endpoints.MapGet("/", () => Results.Redirect("/overlay"));
                        });
                    });
                });

            AppHost = builder.Build();
            File.AppendAllText("debug.log", $"[{DateTime.Now}] Host built. Starting...\n");
            await AppHost.StartAsync();
            File.AppendAllText("debug.log", $"[{DateTime.Now}] Host started. Opening MainWindow...\n");

            _mainWindow = new MainWindow();
            _mainWindow.Show();
            File.AppendAllText("debug.log", $"[{DateTime.Now}] MainWindow shown.\n");
        }
        catch (Exception ex)
        {
            File.WriteAllText("error.log", $"Startup Error: {ex.Message}\n{ex.StackTrace}");
            File.AppendAllText("debug.log", $"[{DateTime.Now}] Startup Error: {ex.Message}\n");
            Shutdown();
        }
    }

    protected override async void OnExit(ExitEventArgs e)
    {
        File.AppendAllText("debug.log", $"[{DateTime.Now}] OnExit called. ExitCode: {e.ApplicationExitCode}\n");
        if (AppHost != null)
        {
            await AppHost.StopAsync();
            AppHost.Dispose();
        }
        base.OnExit(e);
    }

    private static object BuildSettingsPayload(EnvService env)
    {
        return new
        {
            type = "settings",
            enable_tts = env.GetBool("ENABLE_TTS", true),
            enable_dingdong = env.GetBool("ENABLE_DINGDONG", false),
            effects = new
            {
                static_noise = env.GetBool("ADD_STATIC_NOISE", false),
                preset = env.Get("EFFECT_PRESET", "none"),
                static_noise_level = env.GetDouble("STATIC_NOISE_LEVEL", 0.0),
                radio_noise_level = env.GetDouble("RADIO_NOISE_LEVEL", 0.0),
                wind_noise_level = env.GetDouble("WIND_NOISE_LEVEL", 0.0)
            }
        };
    }

    private static ThemePayload BuildThemePayload(EnvService env)
    {
        var hue = env.GetInt("OVERLAY_HUE_DEG", 0);
        hue = Math.Clamp(hue, 0, 360);
        return new ThemePayload { type = "theme", hue_deg = hue };
    }

    private record ThemeRequest
    {
        public int hue_deg { get; set; } = 0;
    }

    private record ThemePayload
    {
        public string type { get; set; } = "theme";
        public int hue_deg { get; set; }
    }

    private record PreviewRequest
    {
        public bool active { get; set; } = false;
        public int score { get; set; } = 1;
    }
}

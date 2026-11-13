// GENERATED from auto_edit/openapi.yaml by scripts/gen_dart_client.py.
// Do not edit: change the spec and run the script again.
// ignore_for_file: type=lint

import 'dart:typed_data';

import '../transport.dart';
import 'models.dart';

/// Every operation of the engine API (contract 1.3.0).
class AutoEditApi {
  AutoEditApi(this.transport);

  final Transport transport;

  /// The `info.version` this client was generated from.
  static const contractVersion = '1.3.0';

  /// The engine is up, and which contract it speaks
  ///
  /// `GET /api/health`
  Future<Health> health() async => Health.fromJson(
    (await transport.json('GET', '/api/health') as Map).cast<String, Object?>(),
  );

  /// This contract, as JSON
  ///
  /// `GET /api/openapi.json`
  Future<Map<String, Object?>> openapi() async =>
      (await transport.json('GET', '/api/openapi.json') as Map)
          .cast<String, Object?>();

  /// Every edit (workspace), newest first, with its live status
  ///
  /// `GET /api/library`
  Future<ListLibraryResponse> listLibrary() async =>
      ListLibraryResponse.fromJson(
        (await transport.json('GET', '/api/library') as Map)
            .cast<String, Object?>(),
      );

  /// Sub-folders and videos of a directory (default the inbox)
  ///
  /// `GET /api/browse`
  Future<Browse> browse({String? dir}) async => Browse.fromJson(
    (await transport.json(
              'GET',
              '/api/browse',
              query: {if (dir != null) 'dir': dir},
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Biblioteca — the videos in the inbox (sub-folders up to 3 levels), each with its edits
  ///
  /// `GET /api/recordings`
  Future<Recordings> listRecordings() async => Recordings.fromJson(
    (await transport.json('GET', '/api/recordings') as Map)
        .cast<String, Object?>(),
  );

  /// JPEG thumbnail of a video inside the inbox (only there)
  ///
  /// `GET /api/recordings/thumb`
  Future<Uint8List> recordingThumb({required String path}) =>
      transport.bytes('GET', '/api/recordings/thumb', query: {'path': path});

  /// The URL of `recordingThumb` (to hand a player or an image widget together with [Transport.headers]).
  Uri recordingThumbUri({required String path}) =>
      transport.uri('/api/recordings/thumb', query: {'path': path});

  /// The inbox and output folders, as the pipeline uses them now
  ///
  /// `GET /api/folders`
  Future<Folders> getFolders() async => Folders.fromJson(
    (await transport.json('GET', '/api/folders') as Map)
        .cast<String, Object?>(),
  );

  /// Open the inbox or the output folder in the file manager (this machine)
  ///
  /// `POST /api/folders/{which}/open`
  Future<Opened> openFolder(String which) async => Opened.fromJson(
    (await transport.json(
              'POST',
              '/api/folders/${Uri.encodeComponent(which)}/open',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Name and size of a video picked or dropped in "Novo edit"
  ///
  /// `GET /api/video-file`
  Future<VideoFile> videoFileInfo({required String path}) async =>
      VideoFile.fromJson(
        (await transport.json('GET', '/api/video-file', query: {'path': path})
                as Map)
            .cast<String, Object?>(),
      );

  /// Start editing a video (job)
  ///
  /// `POST /api/edit`
  Future<JobStarted> startEdit(EditRequest body) async => JobStarted.fromJson(
    (await transport.json('POST', '/api/edit', body: body.toJson()) as Map)
        .cast<String, Object?>(),
  );

  /// Full status of one edit, with plan and metadata summaries
  ///
  /// `GET /api/videos/{video_id}`
  Future<VideoDetail> getVideo(String videoId) async => VideoDetail.fromJson(
    (await transport.json('GET', '/api/videos/${Uri.encodeComponent(videoId)}')
            as Map)
        .cast<String, Object?>(),
  );

  /// Stop it, then delete the workspace and its output files (never the source video)
  ///
  /// `DELETE /api/videos/{video_id}`
  Future<DeleteVideoResponse> deleteVideo(String videoId) async =>
      DeleteVideoResponse.fromJson(
        (await transport.json(
                  'DELETE',
                  '/api/videos/${Uri.encodeComponent(videoId)}',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Stop whatever runs on this video (job, a stray ralph, the queue)
  ///
  /// `POST /api/videos/{video_id}/stop`
  Future<StopVideoResponse> stopVideo(String videoId) async =>
      StopVideoResponse.fromJson(
        (await transport.json(
                  'POST',
                  '/api/videos/${Uri.encodeComponent(videoId)}/stop',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Run the pipeline again from a stage (job)
  ///
  /// `POST /api/videos/{video_id}/resume`
  Future<JobStarted> resumeVideo(
    String videoId,
    ResumeVideoRequest body,
  ) async => JobStarted.fromJson(
    (await transport.json(
              'POST',
              '/api/videos/${Uri.encodeComponent(videoId)}/resume',
              body: body.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Live events of this video's current job (SSE)
  ///
  /// `GET /api/videos/{video_id}/events`
  Stream<JobEvent> videoEvents(String videoId) => transport
      .events('/api/videos/${Uri.encodeComponent(videoId)}/events')
      .map((e) => JobEvent.fromJson((e as Map).cast<String, Object?>()));

  /// Live events of a job (SSE); history first, then live
  ///
  /// `GET /api/jobs/{job_id}/events`
  Stream<JobEvent> jobEvents(String jobId) => transport
      .events('/api/jobs/${Uri.encodeComponent(jobId)}/events')
      .map((e) => JobEvent.fromJson((e as Map).cast<String, Object?>()));

  /// The cut plan, with what is said in each kept segment
  ///
  /// `GET /api/videos/{video_id}/plan`
  Future<Plan> getPlan(String videoId) async => Plan.fromJson(
    (await transport.json(
              'GET',
              '/api/videos/${Uri.encodeComponent(videoId)}/plan',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Replace the kept segments (rewrites reviewed_plan.json; the agent's version is kept)
  ///
  /// `PUT /api/videos/{video_id}/plan`
  Future<Plan> savePlan(String videoId, SavePlanRequest body) async =>
      Plan.fromJson(
        (await transport.json(
                  'PUT',
                  '/api/videos/${Uri.encodeComponent(videoId)}/plan',
                  body: body.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Take a window out of the plan (takes effect on the next execute)
  ///
  /// `POST /api/videos/{video_id}/plan/cut`
  Future<CutRangeResponse> cutRange(
    String videoId,
    CutRangeRequest body,
  ) async => CutRangeResponse.fromJson(
    (await transport.json(
              'POST',
              '/api/videos/${Uri.encodeComponent(videoId)}/plan/cut',
              body: body.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Zoom / B-roll asked for, with where each plays in the edited video
  ///
  /// `GET /api/videos/{video_id}/effects`
  Future<Effects> listEffects(String videoId) async => Effects.fromJson(
    (await transport.json(
              'GET',
              '/api/videos/${Uri.encodeComponent(videoId)}/effects',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Add a zoom or a B-roll (burned at execute; resume from there)
  ///
  /// `POST /api/videos/{video_id}/effects`
  Future<Effects> addEffect(String videoId, EffectInput body) async =>
      Effects.fromJson(
        (await transport.json(
                  'POST',
                  '/api/videos/${Uri.encodeComponent(videoId)}/effects',
                  body: body.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Remove every effect
  ///
  /// `DELETE /api/videos/{video_id}/effects`
  Future<Effects> removeAllEffects(String videoId) async => Effects.fromJson(
    (await transport.json(
              'DELETE',
              '/api/videos/${Uri.encodeComponent(videoId)}/effects',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Remove one effect (its index in the list)
  ///
  /// `DELETE /api/videos/{video_id}/effects/{index}`
  Future<Effects> removeEffect(
    String videoId,
    int index,
  ) async => Effects.fromJson(
    (await transport.json(
              'DELETE',
              '/api/videos/${Uri.encodeComponent(videoId)}/effects/${Uri.encodeComponent('$index')}',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// The short's caption look (final style + its own adjust)
  ///
  /// `GET /api/videos/{video_id}/captions`
  Future<Captions> getCaptions(String videoId) async => Captions.fromJson(
    (await transport.json(
              'GET',
              '/api/videos/${Uri.encodeComponent(videoId)}/captions',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Save the per-video adjust; an absent key keeps its previous value
  ///
  /// `PUT /api/videos/{video_id}/captions`
  Future<Captions> saveCaptions(String videoId, CaptionAdjust body) async =>
      Captions.fromJson(
        (await transport.json(
                  'PUT',
                  '/api/videos/${Uri.encodeComponent(videoId)}/captions',
                  body: body.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// PNG of the caption over a frame of this short, with the adjust applied
  ///
  /// `POST /api/videos/{video_id}/captions/preview`
  Future<Uint8List> previewCaptions(String videoId, {CaptionAdjust? body}) =>
      transport.bytes(
        'POST',
        '/api/videos/${Uri.encodeComponent(videoId)}/captions/preview',
        body: body?.toJson(),
      );

  /// What the Resultado screen shows — metadata and the finished files
  ///
  /// `GET /api/videos/{video_id}/result`
  Future<Result> getResult(String videoId) async => Result.fromJson(
    (await transport.json(
              'GET',
              '/api/videos/${Uri.encodeComponent(videoId)}/result',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Which thumbnail (A/B/C) goes with the upload
  ///
  /// `PUT /api/videos/{video_id}/thumbnail`
  Future<ChooseThumbnailResponse> chooseThumbnail(
    String videoId,
    ChooseThumbnailRequest body,
  ) async => ChooseThumbnailResponse.fromJson(
    (await transport.json(
              'PUT',
              '/api/videos/${Uri.encodeComponent(videoId)}/thumbnail',
              body: body.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// One finished file (supports Range, for seeking in the player)
  ///
  /// `GET /api/videos/{video_id}/file/{kind}`
  Future<Uint8List> getFile(
    String videoId,
    ArtifactKind kind,
  ) => transport.bytes(
    'GET',
    '/api/videos/${Uri.encodeComponent(videoId)}/file/${Uri.encodeComponent(kind.value)}',
  );

  /// The URL of `getFile` (to hand a player or an image widget together with [Transport.headers]).
  Uri getFileUri(String videoId, ArtifactKind kind) => transport.uri(
    '/api/videos/${Uri.encodeComponent(videoId)}/file/${Uri.encodeComponent(kind.value)}',
  );

  /// Open a file on the engine's machine (default app, or `reveal` in the folder)
  ///
  /// `POST /api/videos/{video_id}/open/{kind}`
  Future<Opened> openFile(
    String videoId,
    String kind, {
    OpenFileRequest? body,
  }) async => Opened.fromJson(
    (await transport.json(
              'POST',
              '/api/videos/${Uri.encodeComponent(videoId)}/open/${Uri.encodeComponent(kind)}',
              body: body?.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Shorts candidates of a finished long
  ///
  /// `GET /api/videos/{video_id}/shorts`
  Future<ShortsState> getShorts(String videoId, {double? maxDur}) async =>
      ShortsState.fromJson(
        (await transport.json(
                  'GET',
                  '/api/videos/${Uri.encodeComponent(videoId)}/shorts',
                  query: {if (maxDur != null) 'max_dur': '$maxDur'},
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Run the clipper (job)
  ///
  /// `POST /api/videos/{video_id}/shorts`
  Future<JobStarted> findShorts(
    String videoId, {
    FindShortsRequest? body,
  }) async => JobStarted.fromJson(
    (await transport.json(
              'POST',
              '/api/videos/${Uri.encodeComponent(videoId)}/shorts',
              body: body?.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Cut the picked candidates; each becomes a <name>_shortN edit, run in a queue
  ///
  /// `POST /api/videos/{video_id}/shorts/cut`
  Future<CutShortsResponse> cutShorts(
    String videoId,
    CutShortsRequest body,
  ) async => CutShortsResponse.fromJson(
    (await transport.json(
              'POST',
              '/api/videos/${Uri.encodeComponent(videoId)}/shorts/cut',
              body: body.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Is a YouTube channel connected?
  ///
  /// `GET /api/publish/youtube`
  Future<YouTubeAccount> youtubeAccount() async => YouTubeAccount.fromJson(
    (await transport.json('GET', '/api/publish/youtube') as Map)
        .cast<String, Object?>(),
  );

  /// Open the OAuth consent in the browser (poll GET /api/publish/youtube; gives up after 5 min)
  ///
  /// `POST /api/publish/youtube/connect`
  Future<YouTubeAccount> youtubeConnect() async => YouTubeAccount.fromJson(
    (await transport.json('POST', '/api/publish/youtube/connect') as Map)
        .cast<String, Object?>(),
  );

  /// Stop waiting for the browser's authorization
  ///
  /// `POST /api/publish/youtube/connect/cancel`
  Future<YouTubeAccount> youtubeConnectCancel() async =>
      YouTubeAccount.fromJson(
        (await transport.json('POST', '/api/publish/youtube/connect/cancel')
                as Map)
            .cast<String, Object?>(),
      );

  /// Forget the saved YouTube token
  ///
  /// `POST /api/publish/youtube/disconnect`
  Future<YouTubeAccount> youtubeDisconnect() async => YouTubeAccount.fromJson(
    (await transport.json('POST', '/api/publish/youtube/disconnect') as Map)
        .cast<String, Object?>(),
  );

  /// The OAuth client JSON (Desktop app) from Google Cloud — a path or its content
  ///
  /// `PUT /api/publish/youtube/client`
  Future<YouTubeAccount> youtubeClient(YoutubeClientRequest body) async =>
      YouTubeAccount.fromJson(
        (await transport.json(
                  'PUT',
                  '/api/publish/youtube/client',
                  body: body.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Mark the sent videos that were deleted on YouTube (at most once a minute)
  ///
  /// `POST /api/publish/youtube/refresh`
  Future<YoutubeRefreshResponse> youtubeRefresh() async =>
      YoutubeRefreshResponse.fromJson(
        (await transport.json('POST', '/api/publish/youtube/refresh') as Map)
            .cast<String, Object?>(),
      );

  /// The Publicar card — defaults from the metadata and past publishes
  ///
  /// `GET /api/videos/{video_id}/publish`
  Future<PublishState> getPublish(String videoId) async =>
      PublishState.fromJson(
        (await transport.json(
                  'GET',
                  '/api/videos/${Uri.encodeComponent(videoId)}/publish',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// How the sent videos are on YouTube now (scheduled became public? deleted?)
  ///
  /// `GET /api/videos/{video_id}/publish/live`
  Future<GetPublishLiveResponse> getPublishLive(String videoId) async =>
      GetPublishLiveResponse.fromJson(
        (await transport.json(
                  'GET',
                  '/api/videos/${Uri.encodeComponent(videoId)}/publish/live',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Upload to YouTube with the chosen thumbnail (job)
  ///
  /// `POST /api/videos/{video_id}/publish/youtube`
  Future<JobStarted> publishYoutube(
    String videoId,
    PublishRequest body,
  ) async => JobStarted.fromJson(
    (await transport.json(
              'POST',
              '/api/videos/${Uri.encodeComponent(videoId)}/publish/youtube',
              body: body.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// The saved retention analysis (no call to YouTube)
  ///
  /// `GET /api/videos/{video_id}/retention`
  Future<Retention> getRetention(String videoId) async => Retention.fromJson(
    (await transport.json(
              'GET',
              '/api/videos/${Uri.encodeComponent(videoId)}/retention',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Fetch the retention curve from YouTube now and save the analysis
  ///
  /// `POST /api/videos/{video_id}/retention`
  Future<Retention> refreshRetention(String videoId) async =>
      Retention.fromJson(
        (await transport.json(
                  'POST',
                  '/api/videos/${Uri.encodeComponent(videoId)}/retention',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// The channel's retention over time, with vs without the planner's lessons
  ///
  /// `GET /api/insights/trend`
  Future<Trend> retentionTrend({String? type}) async => Trend.fromJson(
    (await transport.json(
              'GET',
              '/api/insights/trend',
              query: {if (type != null) 'type': type},
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Styles (presets + the person's), the active one, fonts, brand
  ///
  /// `GET /api/styles`
  Future<Styles> listStyles() async => Styles.fromJson(
    (await transport.json('GET', '/api/styles') as Map).cast<String, Object?>(),
  );

  /// Save a style of the person's
  ///
  /// `POST /api/styles`
  Future<Style> saveStyle(SaveStyleRequest body) async => Style.fromJson(
    (await transport.json('POST', '/api/styles', body: body.toJson()) as Map)
        .cast<String, Object?>(),
  );

  ///
  /// `PUT /api/styles/active`
  Future<ActiveStyle> setActiveStyle(SetActiveStyleRequest body) async =>
      ActiveStyle.fromJson(
        (await transport.json('PUT', '/api/styles/active', body: body.toJson())
                as Map)
            .cast<String, Object?>(),
      );

  ///
  /// `DELETE /api/styles/{style_id}`
  Future<ActiveStyle> deleteStyle(String styleId) async => ActiveStyle.fromJson(
    (await transport.json(
              'DELETE',
              '/api/styles/${Uri.encodeComponent(styleId)}',
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Write the .autoedit-style.json to Downloads and show it in the file manager
  ///
  /// `POST /api/styles/{style_id}/export`
  Future<ExportStyleResponse> exportStyle(String styleId) async =>
      ExportStyleResponse.fromJson(
        (await transport.json(
                  'POST',
                  '/api/styles/${Uri.encodeComponent(styleId)}/export',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Import a .autoedit-style.json (never overwrites)
  ///
  /// `POST /api/styles/import`
  Future<Style> importStyle(ImportStyleRequest body) async => Style.fromJson(
    (await transport.json('POST', '/api/styles/import', body: body.toJson())
            as Map)
        .cast<String, Object?>(),
  );

  /// PNG of a style on a frame of the most recent video
  ///
  /// `POST /api/styles/preview/{kind}`
  Future<Uint8List> previewStyle(String kind, PreviewStyleRequest body) =>
      transport.bytes(
        'POST',
        '/api/styles/preview/${Uri.encodeComponent(kind)}',
        body: body.toJson(),
      );

  /// Create a style with AI from a description and a reference image (job; done carries the draft in `result`)
  ///
  /// `POST /api/styles/generate`
  Future<TaskStarted> generateStyle(GenerateStyleRequest body) async =>
      TaskStarted.fromJson(
        (await transport.json(
                  'POST',
                  '/api/styles/generate',
                  body: body.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Adjust a style with AI (job; done carries the draft in `result`)
  ///
  /// `POST /api/styles/adjust`
  Future<TaskStarted> adjustStyle(AdjustStyleRequest body) async =>
      TaskStarted.fromJson(
        (await transport.json('POST', '/api/styles/adjust', body: body.toJson())
                as Map)
            .cast<String, Object?>(),
      );

  /// Colors of an image (default the saved logo) and a suggested set
  ///
  /// `POST /api/styles/palette`
  Future<StylePaletteResponse> stylePalette({
    StylePaletteRequest? body,
  }) async => StylePaletteResponse.fromJson(
    (await transport.json('POST', '/api/styles/palette', body: body?.toJson())
            as Map)
        .cast<String, Object?>(),
  );

  ///
  /// `GET /api/brand/logo`
  Future<Uint8List> getLogo() => transport.bytes('GET', '/api/brand/logo');

  /// The URL of `getLogo` (to hand a player or an image widget together with [Transport.headers]).
  Uri getLogoUri() => transport.uri('/api/brand/logo');

  ///
  /// `PUT /api/brand/logo`
  Future<Brand> uploadLogo(UploadLogoRequest body) async => Brand.fromJson(
    (await transport.json('PUT', '/api/brand/logo', body: body.toJson()) as Map)
        .cast<String, Object?>(),
  );

  ///
  /// `DELETE /api/brand/logo`
  Future<Brand> deleteLogo() async => Brand.fromJson(
    (await transport.json('DELETE', '/api/brand/logo') as Map)
        .cast<String, Object?>(),
  );

  /// ~/.auto-edit/settings.json, with the defaults filled in
  ///
  /// `GET /api/settings`
  Future<Settings> getSettings() async => Settings.fromJson(
    (await transport.json('GET', '/api/settings') as Map)
        .cast<String, Object?>(),
  );

  /// Merge the given keys into the settings
  ///
  /// `PUT /api/settings`
  Future<Settings> saveSettings(Settings body) async => Settings.fromJson(
    (await transport.json('PUT', '/api/settings', body: body.toJson()) as Map)
        .cast<String, Object?>(),
  );

  /// First run — is an agent ready, is Whisper downloaded?
  ///
  /// `GET /api/setup`
  Future<Setup> getSetup() async => Setup.fromJson(
    (await transport.json('GET', '/api/setup') as Map).cast<String, Object?>(),
  );

  /// Download a Whisper model (progress in GET /api/setup)
  ///
  /// `POST /api/setup/whisper`
  Future<WhisperState> downloadWhisper({DownloadWhisperRequest? body}) async =>
      WhisperState.fromJson(
        (await transport.json(
                  'POST',
                  '/api/setup/whisper',
                  body: body?.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Each AI agent — installed? version? (Ollama: models)
  ///
  /// `GET /api/agents`
  Future<ListAgentsResponse> listAgents() async => ListAgentsResponse.fromJson(
    (await transport.json('GET', '/api/agents') as Map).cast<String, Object?>(),
  );

  /// Send a real minimal prompt; the first that works becomes the primary
  ///
  /// `POST /api/agents/{name}/test`
  Future<TestAgentResponse> testAgent(
    String name, {
    TestAgentRequest? body,
  }) async => TestAgentResponse.fromJson(
    (await transport.json(
              'POST',
              '/api/agents/${Uri.encodeComponent(name)}/test',
              body: body?.toJson(),
            )
            as Map)
        .cast<String, Object?>(),
  );

  /// Open a terminal on the engine's machine with the CLI's login
  ///
  /// `POST /api/agents/{name}/login`
  Future<LoginAgentResponse> loginAgent(String name) async =>
      LoginAgentResponse.fromJson(
        (await transport.json(
                  'POST',
                  '/api/agents/${Uri.encodeComponent(name)}/login',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Run the official installer in a terminal (or open the download page)
  ///
  /// `POST /api/agents/{name}/install`
  Future<InstallAgentResponse> installAgent(String name) async =>
      InstallAgentResponse.fromJson(
        (await transport.json(
                  'POST',
                  '/api/agents/${Uri.encodeComponent(name)}/install',
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Download an Ollama model (progress in GET /api/agents)
  ///
  /// `POST /api/agents/ollama/pull`
  Future<PullOllamaResponse> pullOllama(PullOllamaRequest body) async =>
      PullOllamaResponse.fromJson(
        (await transport.json(
                  'POST',
                  '/api/agents/ollama/pull',
                  body: body.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  /// Save the OpenRouter API key (never sent back whole)
  ///
  /// `PUT /api/agents/openrouter/key`
  Future<AgentStatus> saveOpenrouterKey(SaveOpenrouterKeyRequest body) async =>
      AgentStatus.fromJson(
        (await transport.json(
                  'PUT',
                  '/api/agents/openrouter/key',
                  body: body.toJson(),
                )
                as Map)
            .cast<String, Object?>(),
      );

  ///
  /// `DELETE /api/agents/openrouter/key`
  Future<AgentStatus> deleteOpenrouterKey() async => AgentStatus.fromJson(
    (await transport.json('DELETE', '/api/agents/openrouter/key') as Map)
        .cast<String, Object?>(),
  );

  /// Open a link in the default browser — only YouTube, Google Cloud and the agent CLIs' pages
  ///
  /// `POST /api/open-url`
  Future<Opened> openUrl(OpenUrlRequest body) async => Opened.fromJson(
    (await transport.json('POST', '/api/open-url', body: body.toJson()) as Map)
        .cast<String, Object?>(),
  );
}

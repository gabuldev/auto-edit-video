// GENERATED from auto_edit/openapi.yaml by scripts/gen_dart_client.py.
// Do not edit: change the spec and run the script again.
// ignore_for_file: type=lint

/// Values the engine sends today; an unknown one still parses (a newer engine).
extension type const VideoStatus(String value) {
  static const running = VideoStatus('running');
  static const done = VideoStatus('done');
  static const failed = VideoStatus('failed');
  static const queued = VideoStatus('queued');
  static const idle = VideoStatus('idle');
  static const interrupted = VideoStatus('interrupted');
  static const values = [running, done, failed, queued, idle, interrupted];
}

/// Values the engine sends today; an unknown one still parses (a newer engine).
extension type const VideoType(String value) {
  static const short = VideoType('short');
  static const long = VideoType('long');
  static const values = [short, long];
}

/// Values the engine sends today; an unknown one still parses (a newer engine).
extension type const ArtifactKind(String value) {
  static const video = ArtifactKind('video');
  static const thumbnail = ArtifactKind('thumbnail');
  static const thumbnailB = ArtifactKind('thumbnail_b');
  static const thumbnailC = ArtifactKind('thumbnail_c');
  static const captions = ArtifactKind('captions');
  static const notes = ArtifactKind('notes');
  static const values = [
    video,
    thumbnail,
    thumbnailB,
    thumbnailC,
    captions,
    notes,
  ];
}

/// edited: the time of the video the person watched; original: the raw recording
/// Values the engine sends today; an unknown one still parses (a newer engine).
extension type const Timeline(String value) {
  static const edited = Timeline('edited');
  static const original = Timeline('original');
  static const values = [edited, original];
}

class ApiError {
  const ApiError({required this.error});

  final String error;

  factory ApiError.fromJson(Map<String, Object?> json) =>
      ApiError(error: json['error'] as String);

  Map<String, Object?> toJson() => {'error': error};
}

class Health {
  const Health({
    required this.ok,
    required this.apiVersion,
    required this.version,
    this.repoRoot,
  });

  final bool ok;

  /// info.version of this contract
  final String apiVersion;

  /// auto-edit version
  final String version;
  final String? repoRoot;

  factory Health.fromJson(Map<String, Object?> json) => Health(
    ok: json['ok'] as bool,
    apiVersion: json['api_version'] as String,
    version: json['version'] as String,
    repoRoot: json['repo_root'] == null ? null : json['repo_root'] as String,
  );

  Map<String, Object?> toJson() => {
    'ok': ok,
    'api_version': apiVersion,
    'version': version,
    if (repoRoot != null) 'repo_root': repoRoot!,
  };
}

class Window {
  const Window({required this.start, required this.end});

  final double start;
  final double end;

  factory Window.fromJson(Map<String, Object?> json) => Window(
    start: (json['start'] as num).toDouble(),
    end: (json['end'] as num).toDouble(),
  );

  Map<String, Object?> toJson() => {'start': start, 'end': end};
}

class VideoFile {
  const VideoFile({
    required this.name,
    required this.path,
    required this.size,
    required this.modified,
  });

  final String name;
  final String path;
  final int size;
  final String modified;

  factory VideoFile.fromJson(Map<String, Object?> json) => VideoFile(
    name: json['name'] as String,
    path: json['path'] as String,
    size: (json['size'] as num).toInt(),
    modified: json['modified'] as String,
  );

  Map<String, Object?> toJson() => {
    'name': name,
    'path': path,
    'size': size,
    'modified': modified,
  };
}

class Browse {
  const Browse({
    required this.dir,
    this.parent,
    required this.exists,
    required this.dirs,
    required this.videos,
  });

  final String dir;
  final String? parent;
  final bool exists;
  final List<BrowseDirsItem> dirs;
  final List<VideoFile> videos;

  factory Browse.fromJson(Map<String, Object?> json) => Browse(
    dir: json['dir'] as String,
    parent: json['parent'] == null ? null : json['parent'] as String,
    exists: json['exists'] as bool,
    dirs: (json['dirs'] as List)
        .map((e) => BrowseDirsItem.fromJson((e as Map).cast<String, Object?>()))
        .toList(),
    videos: (json['videos'] as List)
        .map((e) => VideoFile.fromJson((e as Map).cast<String, Object?>()))
        .toList(),
  );

  Map<String, Object?> toJson() => {
    'dir': dir,
    'parent': parent,
    'exists': exists,
    'dirs': dirs.map((e) => e.toJson()).toList(),
    'videos': videos.map((e) => e.toJson()).toList(),
  };
}

class Recordings {
  const Recordings({
    required this.folder,
    required this.exists,
    required this.truncated,
    required this.recordings,
  });

  final String folder;
  final bool exists;
  final bool truncated;
  final List<RecordingsRecordingsItem> recordings;

  factory Recordings.fromJson(Map<String, Object?> json) => Recordings(
    folder: json['folder'] as String,
    exists: json['exists'] as bool,
    truncated: json['truncated'] as bool,
    recordings: (json['recordings'] as List)
        .map(
          (e) => RecordingsRecordingsItem.fromJson(
            (e as Map).cast<String, Object?>(),
          ),
        )
        .toList(),
  );

  Map<String, Object?> toJson() => {
    'folder': folder,
    'exists': exists,
    'truncated': truncated,
    'recordings': recordings.map((e) => e.toJson()).toList(),
  };
}

class Folder {
  const Folder({
    required this.path,
    required this.custom,
    required this.exists,
  });

  final String path;
  final bool custom;
  final bool exists;

  factory Folder.fromJson(Map<String, Object?> json) => Folder(
    path: json['path'] as String,
    custom: json['custom'] as bool,
    exists: json['exists'] as bool,
  );

  Map<String, Object?> toJson() => {
    'path': path,
    'custom': custom,
    'exists': exists,
  };
}

class Folders {
  const Folders({required this.inbox, required this.output});

  final Folder inbox;
  final Folder output;

  factory Folders.fromJson(Map<String, Object?> json) => Folders(
    inbox: Folder.fromJson((json['inbox'] as Map).cast<String, Object?>()),
    output: Folder.fromJson((json['output'] as Map).cast<String, Object?>()),
  );

  Map<String, Object?> toJson() => {
    'inbox': inbox.toJson(),
    'output': output.toJson(),
  };
}

/// What is left out comes from the settings
class EditRequest {
  const EditRequest({
    required this.videoPath,
    required this.type,
    this.context,
    this.language,
    this.whisperModel,
    this.maxIterations,
    this.dryRun,
    this.coldOpen,
    this.reorder,
    this.overlaysDir,
    this.name,
  });

  /// Path on the engine's machine
  final String videoPath;
  final VideoType type;
  final String? context;
  final String? language;
  final String? whisperModel;
  final int? maxIterations;
  final bool? dryRun;
  final bool? coldOpen;
  final bool? reorder;
  final String? overlaysDir;

  /// The edit's display name (empty: the file name)
  final String? name;

  factory EditRequest.fromJson(Map<String, Object?> json) => EditRequest(
    videoPath: json['video_path'] as String,
    type: VideoType(json['type'] as String),
    context: json['context'] == null ? null : json['context'] as String,
    language: json['language'] == null ? null : json['language'] as String,
    whisperModel: json['whisper_model'] == null
        ? null
        : json['whisper_model'] as String,
    maxIterations: json['max_iterations'] == null
        ? null
        : (json['max_iterations'] as num).toInt(),
    dryRun: json['dry_run'] == null ? null : json['dry_run'] as bool,
    coldOpen: json['cold_open'] == null ? null : json['cold_open'] as bool,
    reorder: json['reorder'] == null ? null : json['reorder'] as bool,
    overlaysDir: json['overlays_dir'] == null
        ? null
        : json['overlays_dir'] as String,
    name: json['name'] == null ? null : json['name'] as String,
  );

  Map<String, Object?> toJson() => {
    'video_path': videoPath,
    'type': type.value,
    if (context != null) 'context': context!,
    if (language != null) 'language': language!,
    if (whisperModel != null) 'whisper_model': whisperModel!,
    if (maxIterations != null) 'max_iterations': maxIterations!,
    if (dryRun != null) 'dry_run': dryRun!,
    if (coldOpen != null) 'cold_open': coldOpen!,
    if (reorder != null) 'reorder': reorder!,
    if (overlaysDir != null) 'overlays_dir': overlaysDir!,
    if (name != null) 'name': name!,
  };
}

class VideoSummary {
  const VideoSummary({
    required this.id,
    this.name,
    required this.videoName,
    this.videoPath,
    required this.type,
    this.language,
    this.currentStage,
    required this.status,
    this.derivedFrom,
    this.title,
    this.context,
    required this.hasThumbnail,
    this.iteration,
    this.maxIterations,
    this.planId,
    this.createdAt,
    required this.stages,
    this.estimatedTokens,
    this.output,
    this.published,
  });

  final String id;
  final String? name;
  final String videoName;
  final String? videoPath;
  final VideoType type;
  final String? language;
  final String? currentStage;
  final VideoStatus status;

  /// a short cut from a long: the long's workspace
  final String? derivedFrom;
  final String? title;
  final String? context;
  final bool hasThumbnail;
  final int? iteration;
  final int? maxIterations;
  final String? planId;
  final String? createdAt;

  /// stage name → pending | running | done | failed | skip
  final Map<String, String?> stages;
  final int? estimatedTokens;

  /// absolute path of the delivered video
  final String? output;
  final VideoSummaryPublished? published;

  factory VideoSummary.fromJson(Map<String, Object?> json) => VideoSummary(
    id: json['id'] as String,
    name: json['name'] == null ? null : json['name'] as String,
    videoName: json['video_name'] as String,
    videoPath: json['video_path'] == null ? null : json['video_path'] as String,
    type: VideoType(json['type'] as String),
    language: json['language'] == null ? null : json['language'] as String,
    currentStage: json['current_stage'] == null
        ? null
        : json['current_stage'] as String,
    status: VideoStatus(json['status'] as String),
    derivedFrom: json['derived_from'] == null
        ? null
        : json['derived_from'] as String,
    title: json['title'] == null ? null : json['title'] as String,
    context: json['context'] == null ? null : json['context'] as String,
    hasThumbnail: json['has_thumbnail'] as bool,
    iteration: json['iteration'] == null
        ? null
        : (json['iteration'] as num).toInt(),
    maxIterations: json['max_iterations'] == null
        ? null
        : (json['max_iterations'] as num).toInt(),
    planId: json['plan_id'] == null ? null : json['plan_id'] as String,
    createdAt: json['created_at'] == null ? null : json['created_at'] as String,
    stages: (json['stages'] as Map).map(
      (k, e) => MapEntry(k as String, e == null ? null : e as String),
    ),
    estimatedTokens: json['estimated_tokens'] == null
        ? null
        : (json['estimated_tokens'] as num).toInt(),
    output: json['output'] == null ? null : json['output'] as String,
    published: json['published'] == null
        ? null
        : VideoSummaryPublished.fromJson(
            (json['published'] as Map).cast<String, Object?>(),
          ),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    if (name != null) 'name': name!,
    'video_name': videoName,
    if (videoPath != null) 'video_path': videoPath!,
    'type': type.value,
    if (language != null) 'language': language!,
    'current_stage': currentStage,
    'status': status.value,
    if (derivedFrom != null) 'derived_from': derivedFrom!,
    if (title != null) 'title': title!,
    if (context != null) 'context': context!,
    'has_thumbnail': hasThumbnail,
    if (iteration != null) 'iteration': iteration!,
    if (maxIterations != null) 'max_iterations': maxIterations!,
    if (planId != null) 'plan_id': planId!,
    if (createdAt != null) 'created_at': createdAt!,
    'stages': stages,
    if (estimatedTokens != null) 'estimated_tokens': estimatedTokens!,
    if (output != null) 'output': output!,
    if (published != null) 'published': published!.toJson(),
  };
}

class VideoDetail {
  const VideoDetail({
    required this.id,
    this.name,
    required this.videoName,
    this.videoPath,
    required this.type,
    this.language,
    this.currentStage,
    required this.status,
    this.derivedFrom,
    this.title,
    this.context,
    required this.hasThumbnail,
    this.iteration,
    this.maxIterations,
    this.planId,
    this.createdAt,
    required this.stages,
    this.estimatedTokens,
    this.output,
    this.published,
    required this.stageDetail,
    this.tokenStats,
    this.plan,
    this.metadata,
    this.jobId,
  });

  final String id;
  final String? name;
  final String videoName;
  final String? videoPath;
  final VideoType type;
  final String? language;
  final String? currentStage;
  final VideoStatus status;

  /// a short cut from a long: the long's workspace
  final String? derivedFrom;
  final String? title;
  final String? context;
  final bool hasThumbnail;
  final int? iteration;
  final int? maxIterations;
  final String? planId;
  final String? createdAt;

  /// stage name → pending | running | done | failed | skip
  final Map<String, String?> stages;
  final int? estimatedTokens;

  /// absolute path of the delivered video
  final String? output;
  final VideoSummaryPublished? published;
  final Map<String, Map<String, Object?>> stageDetail;
  final Map<String, Object?>? tokenStats;
  final VideoDetailPlan? plan;
  final Map<String, Object?>? metadata;

  /// the job running on it now
  final String? jobId;

  factory VideoDetail.fromJson(Map<String, Object?> json) => VideoDetail(
    id: json['id'] as String,
    name: json['name'] == null ? null : json['name'] as String,
    videoName: json['video_name'] as String,
    videoPath: json['video_path'] == null ? null : json['video_path'] as String,
    type: VideoType(json['type'] as String),
    language: json['language'] == null ? null : json['language'] as String,
    currentStage: json['current_stage'] == null
        ? null
        : json['current_stage'] as String,
    status: VideoStatus(json['status'] as String),
    derivedFrom: json['derived_from'] == null
        ? null
        : json['derived_from'] as String,
    title: json['title'] == null ? null : json['title'] as String,
    context: json['context'] == null ? null : json['context'] as String,
    hasThumbnail: json['has_thumbnail'] as bool,
    iteration: json['iteration'] == null
        ? null
        : (json['iteration'] as num).toInt(),
    maxIterations: json['max_iterations'] == null
        ? null
        : (json['max_iterations'] as num).toInt(),
    planId: json['plan_id'] == null ? null : json['plan_id'] as String,
    createdAt: json['created_at'] == null ? null : json['created_at'] as String,
    stages: (json['stages'] as Map).map(
      (k, e) => MapEntry(k as String, e == null ? null : e as String),
    ),
    estimatedTokens: json['estimated_tokens'] == null
        ? null
        : (json['estimated_tokens'] as num).toInt(),
    output: json['output'] == null ? null : json['output'] as String,
    published: json['published'] == null
        ? null
        : VideoSummaryPublished.fromJson(
            (json['published'] as Map).cast<String, Object?>(),
          ),
    stageDetail: (json['stage_detail'] as Map).map(
      (k, e) => MapEntry(k as String, (e as Map).cast<String, Object?>()),
    ),
    tokenStats: json['token_stats'] == null
        ? null
        : (json['token_stats'] as Map).cast<String, Object?>(),
    plan: json['plan'] == null
        ? null
        : VideoDetailPlan.fromJson(
            (json['plan'] as Map).cast<String, Object?>(),
          ),
    metadata: json['metadata'] == null
        ? null
        : (json['metadata'] as Map).cast<String, Object?>(),
    jobId: json['job_id'] == null ? null : json['job_id'] as String,
  );

  Map<String, Object?> toJson() => {
    'id': id,
    if (name != null) 'name': name!,
    'video_name': videoName,
    if (videoPath != null) 'video_path': videoPath!,
    'type': type.value,
    if (language != null) 'language': language!,
    'current_stage': currentStage,
    'status': status.value,
    if (derivedFrom != null) 'derived_from': derivedFrom!,
    if (title != null) 'title': title!,
    if (context != null) 'context': context!,
    'has_thumbnail': hasThumbnail,
    if (iteration != null) 'iteration': iteration!,
    if (maxIterations != null) 'max_iterations': maxIterations!,
    if (planId != null) 'plan_id': planId!,
    if (createdAt != null) 'created_at': createdAt!,
    'stages': stages,
    if (estimatedTokens != null) 'estimated_tokens': estimatedTokens!,
    if (output != null) 'output': output!,
    if (published != null) 'published': published!.toJson(),
    'stage_detail': stageDetail,
    if (tokenStats != null) 'token_stats': tokenStats!,
    if (plan != null) 'plan': plan!.toJson(),
    if (metadata != null) 'metadata': metadata!,
    if (jobId != null) 'job_id': jobId!,
  };
}

class SegmentInput {
  const SegmentInput({required this.start, required this.end, this.summary});

  final double start;
  final double end;
  final String? summary;

  factory SegmentInput.fromJson(Map<String, Object?> json) => SegmentInput(
    start: (json['start'] as num).toDouble(),
    end: (json['end'] as num).toDouble(),
    summary: json['summary'] == null ? null : json['summary'] as String,
  );

  Map<String, Object?> toJson() => {
    'start': start,
    'end': end,
    if (summary != null) 'summary': summary!,
  };
}

class Plan {
  const Plan({
    required this.id,
    this.name,
    required this.source,
    required this.editable,
    this.duration,
    required this.keptTotal,
    required this.keptSegments,
    required this.cuts,
    this.droppedBlocks,
  });

  final String id;
  final String? name;
  final String source;
  final bool editable;
  final double? duration;
  final double keptTotal;
  final List<PlanKeptSegmentsItem> keptSegments;
  final List<PlanCutsItem> cuts;
  final Object? droppedBlocks;

  factory Plan.fromJson(Map<String, Object?> json) => Plan(
    id: json['id'] as String,
    name: json['name'] == null ? null : json['name'] as String,
    source: json['source'] as String,
    editable: json['editable'] as bool,
    duration: json['duration'] == null
        ? null
        : (json['duration'] as num).toDouble(),
    keptTotal: (json['kept_total'] as num).toDouble(),
    keptSegments: (json['kept_segments'] as List)
        .map(
          (e) =>
              PlanKeptSegmentsItem.fromJson((e as Map).cast<String, Object?>()),
        )
        .toList(),
    cuts: (json['cuts'] as List)
        .map((e) => PlanCutsItem.fromJson((e as Map).cast<String, Object?>()))
        .toList(),
    droppedBlocks: json['dropped_blocks'],
  );

  Map<String, Object?> toJson() => {
    'id': id,
    if (name != null) 'name': name!,
    'source': source,
    'editable': editable,
    if (duration != null) 'duration': duration!,
    'kept_total': keptTotal,
    'kept_segments': keptSegments.map((e) => e.toJson()).toList(),
    'cuts': cuts.map((e) => e.toJson()).toList(),
    if (droppedBlocks != null) 'dropped_blocks': droppedBlocks,
  };
}

class EffectInput {
  const EffectInput({
    required this.type,
    required this.start,
    required this.end,
    this.scale,
    this.file,
    this.timeline,
  });

  final String type;
  final double start;
  final double end;

  /// zoom (default 1.2)
  final double? scale;

  /// broll: image or video on the engine's machine
  final String? file;
  final Timeline? timeline;

  factory EffectInput.fromJson(Map<String, Object?> json) => EffectInput(
    type: json['type'] as String,
    start: (json['start'] as num).toDouble(),
    end: (json['end'] as num).toDouble(),
    scale: json['scale'] == null ? null : (json['scale'] as num).toDouble(),
    file: json['file'] == null ? null : json['file'] as String,
    timeline: json['timeline'] == null
        ? null
        : Timeline(json['timeline'] as String),
  );

  Map<String, Object?> toJson() => {
    'type': type,
    'start': start,
    'end': end,
    if (scale != null) 'scale': scale!,
    if (file != null) 'file': file!,
    if (timeline != null) 'timeline': timeline!.value,
  };
}

class Effects {
  const Effects({
    required this.id,
    required this.effects,
    required this.stored,
    required this.notes,
    this.editedDuration,
    required this.rerenderFrom,
  });

  final String id;
  final List<EffectsEffectsItem> effects;
  final int stored;
  final List<String> notes;
  final double? editedDuration;
  final String rerenderFrom;

  factory Effects.fromJson(Map<String, Object?> json) => Effects(
    id: json['id'] as String,
    effects: (json['effects'] as List)
        .map(
          (e) =>
              EffectsEffectsItem.fromJson((e as Map).cast<String, Object?>()),
        )
        .toList(),
    stored: (json['stored'] as num).toInt(),
    notes: (json['notes'] as List).map((e) => e as String).toList(),
    editedDuration: json['edited_duration'] == null
        ? null
        : (json['edited_duration'] as num).toDouble(),
    rerenderFrom: json['rerender_from'] as String,
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'effects': effects.map((e) => e.toJson()).toList(),
    'stored': stored,
    'notes': notes,
    if (editedDuration != null) 'edited_duration': editedDuration!,
    'rerender_from': rerenderFrom,
  };
}

class CaptionAdjust {
  const CaptionAdjust({this.position, this.offset, this.size, this.hidden});

  final String? position;
  final double? offset;
  final double? size;
  final bool? hidden;

  factory CaptionAdjust.fromJson(Map<String, Object?> json) => CaptionAdjust(
    position: json['position'] == null ? null : json['position'] as String,
    offset: json['offset'] == null ? null : (json['offset'] as num).toDouble(),
    size: json['size'] == null ? null : (json['size'] as num).toDouble(),
    hidden: json['hidden'] == null ? null : json['hidden'] as bool,
  );

  Map<String, Object?> toJson() => {
    if (position != null) 'position': position!,
    if (offset != null) 'offset': offset!,
    if (size != null) 'size': size!,
    if (hidden != null) 'hidden': hidden!,
  };
}

class Captions {
  const Captions({
    required this.captions,
    required this.adjust,
    required this.fast,
    required this.sourceOk,
    required this.videoPath,
  });

  /// the resolved caption tokens of the style
  final Map<String, Object?> captions;
  final CaptionAdjust adjust;

  /// the cut is kept: rewriting the captions skips execute
  final bool fast;
  final bool sourceOk;
  final String videoPath;

  factory Captions.fromJson(Map<String, Object?> json) => Captions(
    captions: (json['captions'] as Map).cast<String, Object?>(),
    adjust: CaptionAdjust.fromJson(
      (json['adjust'] as Map).cast<String, Object?>(),
    ),
    fast: json['fast'] as bool,
    sourceOk: json['source_ok'] as bool,
    videoPath: json['video_path'] as String,
  );

  Map<String, Object?> toJson() => {
    'captions': captions,
    'adjust': adjust.toJson(),
    'fast': fast,
    'source_ok': sourceOk,
    'video_path': videoPath,
  };
}

class ThumbnailOption {
  const ThumbnailOption({
    required this.id,
    required this.kind,
    required this.layout,
    this.qa,
    required this.qaReasons,
    required this.chosen,
  });

  final String id;
  final ArtifactKind kind;
  final String layout;
  final String? qa;
  final List<String> qaReasons;
  final bool chosen;

  factory ThumbnailOption.fromJson(Map<String, Object?> json) =>
      ThumbnailOption(
        id: json['id'] as String,
        kind: ArtifactKind(json['kind'] as String),
        layout: json['layout'] as String,
        qa: json['qa'] == null ? null : json['qa'] as String,
        qaReasons: (json['qa_reasons'] as List)
            .map((e) => e as String)
            .toList(),
        chosen: json['chosen'] as bool,
      );

  Map<String, Object?> toJson() => {
    'id': id,
    'kind': kind.value,
    'layout': layout,
    if (qa != null) 'qa': qa!,
    'qa_reasons': qaReasons,
    'chosen': chosen,
  };
}

class Result {
  const Result({
    required this.id,
    this.name,
    required this.videoName,
    required this.type,
    required this.status,
    this.metadata,
    required this.files,
    required this.thumbnails,
    this.tokenStats,
  });

  final String id;
  final String? name;
  final String videoName;
  final VideoType type;
  final VideoStatus status;
  final Map<String, Object?>? metadata;

  /// artifact kind → the file (only the ones that exist)
  final Map<String, ResultFilesValue> files;
  final List<ThumbnailOption> thumbnails;
  final Map<String, Object?>? tokenStats;

  factory Result.fromJson(Map<String, Object?> json) => Result(
    id: json['id'] as String,
    name: json['name'] == null ? null : json['name'] as String,
    videoName: json['video_name'] as String,
    type: VideoType(json['type'] as String),
    status: VideoStatus(json['status'] as String),
    metadata: json['metadata'] == null
        ? null
        : (json['metadata'] as Map).cast<String, Object?>(),
    files: (json['files'] as Map).map(
      (k, e) => MapEntry(
        k as String,
        ResultFilesValue.fromJson((e as Map).cast<String, Object?>()),
      ),
    ),
    thumbnails: (json['thumbnails'] as List)
        .map(
          (e) => ThumbnailOption.fromJson((e as Map).cast<String, Object?>()),
        )
        .toList(),
    tokenStats: json['token_stats'] == null
        ? null
        : (json['token_stats'] as Map).cast<String, Object?>(),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    if (name != null) 'name': name!,
    'video_name': videoName,
    'type': type.value,
    'status': status.value,
    if (metadata != null) 'metadata': metadata!,
    'files': files.map((k, e) => MapEntry(k, e.toJson())),
    'thumbnails': thumbnails.map((e) => e.toJson()).toList(),
    if (tokenStats != null) 'token_stats': tokenStats!,
  };
}

class ShortsState {
  const ShortsState({
    required this.id,
    this.name,
    required this.eligible,
    this.reason,
    required this.hasPlan,
    required this.maxDuration,
    required this.clips,
    required this.rejected,
    required this.notes,
    this.job,
  });

  final String id;
  final String? name;
  final bool eligible;
  final String? reason;
  final bool hasPlan;
  final double maxDuration;
  final List<ShortsStateClipsItem> clips;
  final List<Object?> rejected;
  final String notes;
  final ShortsStateJob? job;

  factory ShortsState.fromJson(Map<String, Object?> json) => ShortsState(
    id: json['id'] as String,
    name: json['name'] == null ? null : json['name'] as String,
    eligible: json['eligible'] as bool,
    reason: json['reason'] == null ? null : json['reason'] as String,
    hasPlan: json['has_plan'] as bool,
    maxDuration: (json['max_duration'] as num).toDouble(),
    clips: (json['clips'] as List)
        .map(
          (e) =>
              ShortsStateClipsItem.fromJson((e as Map).cast<String, Object?>()),
        )
        .toList(),
    rejected: (json['rejected'] as List).map((e) => e).toList(),
    notes: json['notes'] as String,
    job: json['job'] == null
        ? null
        : ShortsStateJob.fromJson((json['job'] as Map).cast<String, Object?>()),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    if (name != null) 'name': name!,
    'eligible': eligible,
    'reason': reason,
    'has_plan': hasPlan,
    'max_duration': maxDuration,
    'clips': clips.map((e) => e.toJson()).toList(),
    'rejected': rejected,
    'notes': notes,
    if (job != null) 'job': job!.toJson(),
  };
}

class YouTubeAccount {
  const YouTubeAccount({
    required this.connected,
    this.needsReconnect,
    this.channel,
    required this.connecting,
    this.error,
    required this.hasClientSecret,
    this.clientId,
  });

  final bool connected;
  final bool? needsReconnect;
  final String? channel;
  final bool connecting;
  final String? error;
  final bool hasClientSecret;
  final String? clientId;

  factory YouTubeAccount.fromJson(Map<String, Object?> json) => YouTubeAccount(
    connected: json['connected'] as bool,
    needsReconnect: json['needs_reconnect'] == null
        ? null
        : json['needs_reconnect'] as bool,
    channel: json['channel'] == null ? null : json['channel'] as String,
    connecting: json['connecting'] as bool,
    error: json['error'] == null ? null : json['error'] as String,
    hasClientSecret: json['has_client_secret'] as bool,
    clientId: json['client_id'] == null ? null : json['client_id'] as String,
  );

  Map<String, Object?> toJson() => {
    'connected': connected,
    if (needsReconnect != null) 'needs_reconnect': needsReconnect!,
    if (channel != null) 'channel': channel!,
    'connecting': connecting,
    if (error != null) 'error': error!,
    'has_client_secret': hasClientSecret,
    if (clientId != null) 'client_id': clientId!,
  };
}

class PublishRequest {
  const PublishRequest({
    this.title,
    this.description,
    this.tags,
    this.privacy,
    this.publishAt,
    this.captions,
    this.comment,
    this.force,
  });

  final String? title;
  final String? description;
  final Object? tags;
  final String? privacy;

  /// schedule (needs privacy private)
  final String? publishAt;

  /// long: send the .srt along
  final bool? captions;

  /// comment to pin (not on a private video)
  final String? comment;

  /// send again even if already on YouTube
  final bool? force;

  factory PublishRequest.fromJson(Map<String, Object?> json) => PublishRequest(
    title: json['title'] == null ? null : json['title'] as String,
    description: json['description'] == null
        ? null
        : json['description'] as String,
    tags: json['tags'],
    privacy: json['privacy'] == null ? null : json['privacy'] as String,
    publishAt: json['publish_at'] == null ? null : json['publish_at'] as String,
    captions: json['captions'] == null ? null : json['captions'] as bool,
    comment: json['comment'] == null ? null : json['comment'] as String,
    force: json['force'] == null ? null : json['force'] as bool,
  );

  Map<String, Object?> toJson() => {
    if (title != null) 'title': title!,
    if (description != null) 'description': description!,
    if (tags != null) 'tags': tags,
    if (privacy != null) 'privacy': privacy!,
    if (publishAt != null) 'publish_at': publishAt!,
    if (captions != null) 'captions': captions!,
    if (comment != null) 'comment': comment!,
    if (force != null) 'force': force!,
  };
}

class PublishState {
  const PublishState({
    required this.id,
    required this.type,
    required this.eligible,
    this.reason,
    required this.defaults,
    required this.thumbnail,
    this.thumbnailVariant,
    required this.captions,
    this.pinnedComment,
    this.titleOptions,
    this.nextVideo,
    required this.limits,
    required this.published,
    required this.account,
    this.job,
  });

  final String id;
  final VideoType type;
  final bool eligible;
  final String? reason;
  final PublishStateDefaults defaults;
  final bool thumbnail;
  final String? thumbnailVariant;
  final bool captions;
  final String? pinnedComment;
  final List<String>? titleOptions;
  final Object? nextVideo;
  final PublishStateLimits limits;
  final List<PublishStatePublishedItem> published;
  final YouTubeAccount account;
  final PublishStateJob? job;

  factory PublishState.fromJson(Map<String, Object?> json) => PublishState(
    id: json['id'] as String,
    type: VideoType(json['type'] as String),
    eligible: json['eligible'] as bool,
    reason: json['reason'] == null ? null : json['reason'] as String,
    defaults: PublishStateDefaults.fromJson(
      (json['defaults'] as Map).cast<String, Object?>(),
    ),
    thumbnail: json['thumbnail'] as bool,
    thumbnailVariant: json['thumbnail_variant'] == null
        ? null
        : json['thumbnail_variant'] as String,
    captions: json['captions'] as bool,
    pinnedComment: json['pinned_comment'] == null
        ? null
        : json['pinned_comment'] as String,
    titleOptions: json['title_options'] == null
        ? null
        : (json['title_options'] as List).map((e) => e as String).toList(),
    nextVideo: json['next_video'],
    limits: PublishStateLimits.fromJson(
      (json['limits'] as Map).cast<String, Object?>(),
    ),
    published: (json['published'] as List)
        .map(
          (e) => PublishStatePublishedItem.fromJson(
            (e as Map).cast<String, Object?>(),
          ),
        )
        .toList(),
    account: YouTubeAccount.fromJson(
      (json['account'] as Map).cast<String, Object?>(),
    ),
    job: json['job'] == null
        ? null
        : PublishStateJob.fromJson(
            (json['job'] as Map).cast<String, Object?>(),
          ),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'type': type.value,
    'eligible': eligible,
    'reason': reason,
    'defaults': defaults.toJson(),
    'thumbnail': thumbnail,
    if (thumbnailVariant != null) 'thumbnail_variant': thumbnailVariant!,
    'captions': captions,
    if (pinnedComment != null) 'pinned_comment': pinnedComment!,
    if (titleOptions != null) 'title_options': titleOptions!,
    if (nextVideo != null) 'next_video': nextVideo,
    'limits': limits.toJson(),
    'published': published.map((e) => e.toJson()).toList(),
    'account': account.toJson(),
    if (job != null) 'job': job!.toJson(),
  };
}

class Retention {
  const Retention({
    required this.id,
    this.youtubeId,
    this.data,
    this.versusPrevious,
    required this.account,
  });

  final String id;
  final String? youtubeId;

  /// the saved analysis (retention.json)
  final Map<String, Object?>? data;
  final Map<String, Object?>? versusPrevious;
  final YouTubeAccount account;

  factory Retention.fromJson(Map<String, Object?> json) => Retention(
    id: json['id'] as String,
    youtubeId: json['youtube_id'] == null ? null : json['youtube_id'] as String,
    data: json['data'] == null
        ? null
        : (json['data'] as Map).cast<String, Object?>(),
    versusPrevious: json['versus_previous'] == null
        ? null
        : (json['versus_previous'] as Map).cast<String, Object?>(),
    account: YouTubeAccount.fromJson(
      (json['account'] as Map).cast<String, Object?>(),
    ),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'youtube_id': youtubeId,
    'data': data,
    'versus_previous': versusPrevious,
    'account': account.toJson(),
  };
}

class Trend {
  const Trend({this.type, required this.videos});

  final String? type;
  final List<TrendVideosItem> videos;

  factory Trend.fromJson(Map<String, Object?> json) => Trend(
    type: json['type'] == null ? null : json['type'] as String,
    videos: (json['videos'] as List)
        .map(
          (e) => TrendVideosItem.fromJson((e as Map).cast<String, Object?>()),
        )
        .toList(),
  );

  Map<String, Object?> toJson() => {
    if (type != null) 'type': type!,
    'videos': videos.map((e) => e.toJson()).toList(),
  };
}

class Style {
  const Style({
    required this.id,
    required this.name,
    this.description,
    required this.tokens,
  });

  final String id;
  final String name;
  final String? description;
  final Map<String, Object?> tokens;

  factory Style.fromJson(Map<String, Object?> json) => Style(
    id: json['id'] as String,
    name: json['name'] as String,
    description: json['description'] == null
        ? null
        : json['description'] as String,
    tokens: (json['tokens'] as Map).cast<String, Object?>(),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'name': name,
    if (description != null) 'description': description!,
    'tokens': tokens,
  };
}

class Brand {
  const Brand({this.name, this.handle, this.logo, this.logoBg});

  final String? name;
  final String? handle;

  /// path of the saved logo on the engine's machine
  final String? logo;
  final String? logoBg;

  factory Brand.fromJson(Map<String, Object?> json) => Brand(
    name: json['name'] == null ? null : json['name'] as String,
    handle: json['handle'] == null ? null : json['handle'] as String,
    logo: json['logo'] == null ? null : json['logo'] as String,
    logoBg: json['logo_bg'] == null ? null : json['logo_bg'] as String,
  );

  Map<String, Object?> toJson() => {
    if (name != null) 'name': name!,
    if (handle != null) 'handle': handle!,
    if (logo != null) 'logo': logo!,
    if (logoBg != null) 'logo_bg': logoBg!,
  };
}

class Styles {
  const Styles({
    required this.active,
    required this.styles,
    required this.fonts,
    required this.icons,
    required this.positions,
    required this.brand,
    required this.aiVision,
  });

  final String active;
  final List<Style> styles;
  final List<StylesFontsItem> fonts;
  final List<String> icons;
  final StylesPositions positions;
  final Brand brand;
  final bool aiVision;

  factory Styles.fromJson(Map<String, Object?> json) => Styles(
    active: json['active'] as String,
    styles: (json['styles'] as List)
        .map((e) => Style.fromJson((e as Map).cast<String, Object?>()))
        .toList(),
    fonts: (json['fonts'] as List)
        .map(
          (e) => StylesFontsItem.fromJson((e as Map).cast<String, Object?>()),
        )
        .toList(),
    icons: (json['icons'] as List).map((e) => e as String).toList(),
    positions: StylesPositions.fromJson(
      (json['positions'] as Map).cast<String, Object?>(),
    ),
    brand: Brand.fromJson((json['brand'] as Map).cast<String, Object?>()),
    aiVision: json['ai_vision'] as bool,
  );

  Map<String, Object?> toJson() => {
    'active': active,
    'styles': styles.map((e) => e.toJson()).toList(),
    'fonts': fonts.map((e) => e.toJson()).toList(),
    'icons': icons,
    'positions': positions.toJson(),
    'brand': brand.toJson(),
    'ai_vision': aiVision,
  };
}

/// ~/.auto-edit/settings.json (validated by auto_edit/settings.py)
class Settings {
  const Settings({
    this.language,
    this.whisperModel,
    this.coldOpen,
    this.reorder,
    this.overlaysDir,
    this.agent,
    this.verifiedAgent,
    this.brand,
    this.inbox,
    this.outputDir,
    this.style,
  });

  final String? language;
  final String? whisperModel;
  final bool? coldOpen;
  final bool? reorder;
  final String? overlaysDir;
  final SettingsAgent? agent;
  final String? verifiedAgent;
  final Map<String, Object?>? brand;
  final String? inbox;
  final String? outputDir;
  final String? style;

  factory Settings.fromJson(Map<String, Object?> json) => Settings(
    language: json['language'] == null ? null : json['language'] as String,
    whisperModel: json['whisper_model'] == null
        ? null
        : json['whisper_model'] as String,
    coldOpen: json['cold_open'] == null ? null : json['cold_open'] as bool,
    reorder: json['reorder'] == null ? null : json['reorder'] as bool,
    overlaysDir: json['overlays_dir'] == null
        ? null
        : json['overlays_dir'] as String,
    agent: json['agent'] == null
        ? null
        : SettingsAgent.fromJson(
            (json['agent'] as Map).cast<String, Object?>(),
          ),
    verifiedAgent: json['verified_agent'] == null
        ? null
        : json['verified_agent'] as String,
    brand: json['brand'] == null
        ? null
        : (json['brand'] as Map).cast<String, Object?>(),
    inbox: json['inbox'] == null ? null : json['inbox'] as String,
    outputDir: json['output_dir'] == null ? null : json['output_dir'] as String,
    style: json['style'] == null ? null : json['style'] as String,
  );

  Map<String, Object?> toJson() => {
    if (language != null) 'language': language!,
    if (whisperModel != null) 'whisper_model': whisperModel!,
    if (coldOpen != null) 'cold_open': coldOpen!,
    if (reorder != null) 'reorder': reorder!,
    if (overlaysDir != null) 'overlays_dir': overlaysDir!,
    if (agent != null) 'agent': agent!.toJson(),
    if (verifiedAgent != null) 'verified_agent': verifiedAgent!,
    if (brand != null) 'brand': brand!,
    if (inbox != null) 'inbox': inbox!,
    if (outputDir != null) 'output_dir': outputDir!,
    if (style != null) 'style': style!,
  };
}

class AgentStatus {
  const AgentStatus({
    required this.name,
    required this.label,
    required this.installed,
    this.path,
    this.version,
    this.loginCommand,
    this.docs,
    this.apiKey,
    this.keyHint,
    this.keySource,
    this.server,
    this.models,
    this.pulling,
  });

  final String name;
  final String label;
  final bool installed;
  final String? path;
  final String? version;
  final String? loginCommand;
  final String? docs;

  /// OpenRouter: no CLI, installed = there is a key
  final bool? apiKey;

  /// The key masked (sk-or-…abcd); the key never comes back
  final String? keyHint;

  /// env (OPENROUTER_API_KEY) | settings (saved by the app)
  final String? keySource;

  /// Ollama: the server answers
  final bool? server;

  /// Ollama: the models downloaded
  final List<String>? models;

  /// Ollama: model → downloading | done | the error
  final Map<String, String>? pulling;

  factory AgentStatus.fromJson(Map<String, Object?> json) => AgentStatus(
    name: json['name'] as String,
    label: json['label'] as String,
    installed: json['installed'] as bool,
    path: json['path'] == null ? null : json['path'] as String,
    version: json['version'] == null ? null : json['version'] as String,
    loginCommand: json['login_command'] == null
        ? null
        : json['login_command'] as String,
    docs: json['docs'] == null ? null : json['docs'] as String,
    apiKey: json['api_key'] == null ? null : json['api_key'] as bool,
    keyHint: json['key_hint'] == null ? null : json['key_hint'] as String,
    keySource: json['key_source'] == null ? null : json['key_source'] as String,
    server: json['server'] == null ? null : json['server'] as bool,
    models: json['models'] == null
        ? null
        : (json['models'] as List).map((e) => e as String).toList(),
    pulling: json['pulling'] == null
        ? null
        : (json['pulling'] as Map).map(
            (k, e) => MapEntry(k as String, e as String),
          ),
  );

  Map<String, Object?> toJson() => {
    'name': name,
    'label': label,
    'installed': installed,
    if (path != null) 'path': path!,
    if (version != null) 'version': version!,
    if (loginCommand != null) 'login_command': loginCommand!,
    if (docs != null) 'docs': docs!,
    if (apiKey != null) 'api_key': apiKey!,
    if (keyHint != null) 'key_hint': keyHint!,
    if (keySource != null) 'key_source': keySource!,
    if (server != null) 'server': server!,
    if (models != null) 'models': models!,
    if (pulling != null) 'pulling': pulling!,
  };
}

class SettingsAgent {
  const SettingsAgent({this.primary, this.fallback, this.models});

  final String? primary;
  final String? fallback;

  /// agent → model (null: the CLI's default)
  final Map<String, String?>? models;

  factory SettingsAgent.fromJson(Map<String, Object?> json) => SettingsAgent(
    primary: json['primary'] == null ? null : json['primary'] as String,
    fallback: json['fallback'] == null ? null : json['fallback'] as String,
    models: json['models'] == null
        ? null
        : (json['models'] as Map).map(
            (k, e) => MapEntry(k as String, e == null ? null : e as String),
          ),
  );

  Map<String, Object?> toJson() => {
    if (primary != null) 'primary': primary!,
    if (fallback != null) 'fallback': fallback!,
    if (models != null) 'models': models!,
  };
}

class WhisperState {
  const WhisperState({
    required this.model,
    required this.ready,
    required this.downloading,
    required this.progress,
    this.sizeMb,
    this.error,
  });

  final String model;
  final bool ready;
  final bool downloading;
  final double progress;
  final int? sizeMb;
  final String? error;

  factory WhisperState.fromJson(Map<String, Object?> json) => WhisperState(
    model: json['model'] as String,
    ready: json['ready'] as bool,
    downloading: json['downloading'] as bool,
    progress: (json['progress'] as num).toDouble(),
    sizeMb: json['size_mb'] == null ? null : (json['size_mb'] as num).toInt(),
    error: json['error'] == null ? null : json['error'] as String,
  );

  Map<String, Object?> toJson() => {
    'model': model,
    'ready': ready,
    'downloading': downloading,
    'progress': progress,
    if (sizeMb != null) 'size_mb': sizeMb!,
    if (error != null) 'error': error!,
  };
}

class Setup {
  const Setup({
    required this.agents,
    this.primary,
    this.installed,
    required this.agentReady,
    this.verifiedAgent,
    required this.whisper,
    required this.ready,
    this.installCommands,
    required this.platform,
  });

  final List<AgentStatus> agents;
  final String? primary;
  final List<String>? installed;
  final bool agentReady;
  final String? verifiedAgent;
  final WhisperState whisper;
  final bool ready;
  final Map<String, Object?>? installCommands;
  final String platform;

  factory Setup.fromJson(Map<String, Object?> json) => Setup(
    agents: (json['agents'] as List)
        .map((e) => AgentStatus.fromJson((e as Map).cast<String, Object?>()))
        .toList(),
    primary: json['primary'] == null ? null : json['primary'] as String,
    installed: json['installed'] == null
        ? null
        : (json['installed'] as List).map((e) => e as String).toList(),
    agentReady: json['agent_ready'] as bool,
    verifiedAgent: json['verified_agent'] == null
        ? null
        : json['verified_agent'] as String,
    whisper: WhisperState.fromJson(
      (json['whisper'] as Map).cast<String, Object?>(),
    ),
    ready: json['ready'] as bool,
    installCommands: json['install_commands'] == null
        ? null
        : (json['install_commands'] as Map).cast<String, Object?>(),
    platform: json['platform'] as String,
  );

  Map<String, Object?> toJson() => {
    'agents': agents.map((e) => e.toJson()).toList(),
    if (primary != null) 'primary': primary!,
    if (installed != null) 'installed': installed!,
    'agent_ready': agentReady,
    if (verifiedAgent != null) 'verified_agent': verifiedAgent!,
    'whisper': whisper.toJson(),
    'ready': ready,
    if (installCommands != null) 'install_commands': installCommands!,
    'platform': platform,
  };
}

/// log: a line of the pipeline's log. stage: the stage now running.
/// progress: `pct` (upload) or `message` (AI style). done: finished
/// (`output` for an edit, `url`/`video_id` for a publish, `result` for an
/// AI style). error: failed or `status: cancelled`.
class JobEvent {
  const JobEvent({
    required this.type,
    this.line,
    this.stage,
    this.pct,
    this.message,
    this.status,
    this.output,
    this.url,
    this.videoId,
    this.result,
  });

  final String type;
  final String? line;
  final String? stage;
  final int? pct;
  final String? message;
  final String? status;
  final String? output;
  final String? url;
  final String? videoId;
  final Map<String, Object?>? result;

  factory JobEvent.fromJson(Map<String, Object?> json) => JobEvent(
    type: json['type'] as String,
    line: json['line'] == null ? null : json['line'] as String,
    stage: json['stage'] == null ? null : json['stage'] as String,
    pct: json['pct'] == null ? null : (json['pct'] as num).toInt(),
    message: json['message'] == null ? null : json['message'] as String,
    status: json['status'] == null ? null : json['status'] as String,
    output: json['output'] == null ? null : json['output'] as String,
    url: json['url'] == null ? null : json['url'] as String,
    videoId: json['video_id'] == null ? null : json['video_id'] as String,
    result: json['result'] == null
        ? null
        : (json['result'] as Map).cast<String, Object?>(),
  );

  Map<String, Object?> toJson() => {
    'type': type,
    if (line != null) 'line': line!,
    if (stage != null) 'stage': stage!,
    if (pct != null) 'pct': pct!,
    if (message != null) 'message': message!,
    if (status != null) 'status': status!,
    if (output != null) 'output': output!,
    if (url != null) 'url': url!,
    if (videoId != null) 'video_id': videoId!,
    if (result != null) 'result': result!,
  };
}

class ListLibraryResponse {
  const ListLibraryResponse({required this.videos});

  final List<VideoSummary> videos;

  factory ListLibraryResponse.fromJson(Map<String, Object?> json) =>
      ListLibraryResponse(
        videos: (json['videos'] as List)
            .map(
              (e) => VideoSummary.fromJson((e as Map).cast<String, Object?>()),
            )
            .toList(),
      );

  Map<String, Object?> toJson() => {
    'videos': videos.map((e) => e.toJson()).toList(),
  };
}

class Opened {
  const Opened({required this.opened});

  final String opened;

  factory Opened.fromJson(Map<String, Object?> json) =>
      Opened(opened: json['opened'] as String);

  Map<String, Object?> toJson() => {'opened': opened};
}

class JobStarted {
  const JobStarted({required this.jobId, required this.videoId});

  final String jobId;
  final String videoId;

  factory JobStarted.fromJson(Map<String, Object?> json) => JobStarted(
    jobId: json['job_id'] as String,
    videoId: json['video_id'] as String,
  );

  Map<String, Object?> toJson() => {'job_id': jobId, 'video_id': videoId};
}

class DeleteVideoResponse {
  const DeleteVideoResponse({required this.id, required this.removed});

  final String id;
  final List<String> removed;

  factory DeleteVideoResponse.fromJson(Map<String, Object?> json) =>
      DeleteVideoResponse(
        id: json['id'] as String,
        removed: (json['removed'] as List).map((e) => e as String).toList(),
      );

  Map<String, Object?> toJson() => {'id': id, 'removed': removed};
}

class StopVideoResponse {
  const StopVideoResponse({
    required this.id,
    required this.stopped,
    required this.resetStages,
  });

  final String id;
  final List<String> stopped;
  final List<String> resetStages;

  factory StopVideoResponse.fromJson(Map<String, Object?> json) =>
      StopVideoResponse(
        id: json['id'] as String,
        stopped: (json['stopped'] as List).map((e) => e as String).toList(),
        resetStages: (json['reset_stages'] as List)
            .map((e) => e as String)
            .toList(),
      );

  Map<String, Object?> toJson() => {
    'id': id,
    'stopped': stopped,
    'reset_stages': resetStages,
  };
}

class ResumeVideoRequest {
  const ResumeVideoRequest({
    required this.fromStage,
    this.overlaysDir,
    this.captionOnly,
  });

  /// extract, plan, review, evaluate, execute, overlay, caption, metadata…
  final String fromStage;
  final String? overlaysDir;

  /// short: rewrite only the burned captions
  final bool? captionOnly;

  factory ResumeVideoRequest.fromJson(Map<String, Object?> json) =>
      ResumeVideoRequest(
        fromStage: json['from_stage'] as String,
        overlaysDir: json['overlays_dir'] == null
            ? null
            : json['overlays_dir'] as String,
        captionOnly: json['caption_only'] == null
            ? null
            : json['caption_only'] as bool,
      );

  Map<String, Object?> toJson() => {
    'from_stage': fromStage,
    if (overlaysDir != null) 'overlays_dir': overlaysDir!,
    if (captionOnly != null) 'caption_only': captionOnly!,
  };
}

class SavePlanRequest {
  const SavePlanRequest({required this.keptSegments});

  final List<SegmentInput> keptSegments;

  factory SavePlanRequest.fromJson(Map<String, Object?> json) =>
      SavePlanRequest(
        keptSegments: (json['kept_segments'] as List)
            .map(
              (e) => SegmentInput.fromJson((e as Map).cast<String, Object?>()),
            )
            .toList(),
      );

  Map<String, Object?> toJson() => {
    'kept_segments': keptSegments.map((e) => e.toJson()).toList(),
  };
}

class CutRangeRequest {
  const CutRangeRequest({
    required this.start,
    required this.end,
    this.timeline,
  });

  final double start;
  final double end;
  final Timeline? timeline;

  factory CutRangeRequest.fromJson(Map<String, Object?> json) =>
      CutRangeRequest(
        start: (json['start'] as num).toDouble(),
        end: (json['end'] as num).toDouble(),
        timeline: json['timeline'] == null
            ? null
            : Timeline(json['timeline'] as String),
      );

  Map<String, Object?> toJson() => {
    'start': start,
    'end': end,
    if (timeline != null) 'timeline': timeline!.value,
  };
}

class CutRangeResponse {
  const CutRangeResponse({
    required this.id,
    this.name,
    required this.source,
    required this.editable,
    this.duration,
    required this.keptTotal,
    required this.keptSegments,
    required this.cuts,
    this.droppedBlocks,
    required this.removedWindows,
  });

  final String id;
  final String? name;
  final String source;
  final bool editable;
  final double? duration;
  final double keptTotal;
  final List<PlanKeptSegmentsItem> keptSegments;
  final List<PlanCutsItem> cuts;
  final Object? droppedBlocks;
  final List<Window> removedWindows;

  factory CutRangeResponse.fromJson(
    Map<String, Object?> json,
  ) => CutRangeResponse(
    id: json['id'] as String,
    name: json['name'] == null ? null : json['name'] as String,
    source: json['source'] as String,
    editable: json['editable'] as bool,
    duration: json['duration'] == null
        ? null
        : (json['duration'] as num).toDouble(),
    keptTotal: (json['kept_total'] as num).toDouble(),
    keptSegments: (json['kept_segments'] as List)
        .map(
          (e) =>
              PlanKeptSegmentsItem.fromJson((e as Map).cast<String, Object?>()),
        )
        .toList(),
    cuts: (json['cuts'] as List)
        .map((e) => PlanCutsItem.fromJson((e as Map).cast<String, Object?>()))
        .toList(),
    droppedBlocks: json['dropped_blocks'],
    removedWindows: (json['removed_windows'] as List)
        .map((e) => Window.fromJson((e as Map).cast<String, Object?>()))
        .toList(),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    if (name != null) 'name': name!,
    'source': source,
    'editable': editable,
    if (duration != null) 'duration': duration!,
    'kept_total': keptTotal,
    'kept_segments': keptSegments.map((e) => e.toJson()).toList(),
    'cuts': cuts.map((e) => e.toJson()).toList(),
    if (droppedBlocks != null) 'dropped_blocks': droppedBlocks,
    'removed_windows': removedWindows.map((e) => e.toJson()).toList(),
  };
}

class ChooseThumbnailRequest {
  const ChooseThumbnailRequest({required this.variant});

  final String variant;

  factory ChooseThumbnailRequest.fromJson(Map<String, Object?> json) =>
      ChooseThumbnailRequest(variant: json['variant'] as String);

  Map<String, Object?> toJson() => {'variant': variant};
}

class ChooseThumbnailResponse {
  const ChooseThumbnailResponse({required this.thumbnails});

  final List<ThumbnailOption> thumbnails;

  factory ChooseThumbnailResponse.fromJson(Map<String, Object?> json) =>
      ChooseThumbnailResponse(
        thumbnails: (json['thumbnails'] as List)
            .map(
              (e) =>
                  ThumbnailOption.fromJson((e as Map).cast<String, Object?>()),
            )
            .toList(),
      );

  Map<String, Object?> toJson() => {
    'thumbnails': thumbnails.map((e) => e.toJson()).toList(),
  };
}

class OpenFileRequest {
  const OpenFileRequest({this.reveal});

  final bool? reveal;

  factory OpenFileRequest.fromJson(Map<String, Object?> json) =>
      OpenFileRequest(
        reveal: json['reveal'] == null ? null : json['reveal'] as bool,
      );

  Map<String, Object?> toJson() => {if (reveal != null) 'reveal': reveal!};
}

class FindShortsRequest {
  const FindShortsRequest({this.maxDur});

  final double? maxDur;

  factory FindShortsRequest.fromJson(Map<String, Object?> json) =>
      FindShortsRequest(
        maxDur: json['max_dur'] == null
            ? null
            : (json['max_dur'] as num).toDouble(),
      );

  Map<String, Object?> toJson() => {if (maxDur != null) 'max_dur': maxDur!};
}

class CutShortsRequest {
  const CutShortsRequest({required this.pick, this.maxDur});

  final List<int> pick;
  final double? maxDur;

  factory CutShortsRequest.fromJson(Map<String, Object?> json) =>
      CutShortsRequest(
        pick: (json['pick'] as List).map((e) => (e as num).toInt()).toList(),
        maxDur: json['max_dur'] == null
            ? null
            : (json['max_dur'] as num).toDouble(),
      );

  Map<String, Object?> toJson() => {
    'pick': pick,
    if (maxDur != null) 'max_dur': maxDur!,
  };
}

class CutShortsResponse {
  const CutShortsResponse({required this.shorts});

  final List<String> shorts;

  factory CutShortsResponse.fromJson(Map<String, Object?> json) =>
      CutShortsResponse(
        shorts: (json['shorts'] as List).map((e) => e as String).toList(),
      );

  Map<String, Object?> toJson() => {'shorts': shorts};
}

class YoutubeClientRequest {
  const YoutubeClientRequest({this.path, this.content});

  final String? path;
  final String? content;

  factory YoutubeClientRequest.fromJson(Map<String, Object?> json) =>
      YoutubeClientRequest(
        path: json['path'] == null ? null : json['path'] as String,
        content: json['content'] == null ? null : json['content'] as String,
      );

  Map<String, Object?> toJson() => {
    if (path != null) 'path': path!,
    if (content != null) 'content': content!,
  };
}

class YoutubeRefreshResponse {
  const YoutubeRefreshResponse({
    required this.checked,
    required this.changed,
    this.error,
  });

  final bool checked;
  final bool changed;
  final String? error;

  factory YoutubeRefreshResponse.fromJson(Map<String, Object?> json) =>
      YoutubeRefreshResponse(
        checked: json['checked'] as bool,
        changed: json['changed'] as bool,
        error: json['error'] == null ? null : json['error'] as String,
      );

  Map<String, Object?> toJson() => {
    'checked': checked,
    'changed': changed,
    if (error != null) 'error': error!,
  };
}

class GetPublishLiveResponse {
  const GetPublishLiveResponse({required this.checked, this.videos});

  final bool checked;
  final List<Map<String, Object?>>? videos;

  factory GetPublishLiveResponse.fromJson(Map<String, Object?> json) =>
      GetPublishLiveResponse(
        checked: json['checked'] as bool,
        videos: json['videos'] == null
            ? null
            : (json['videos'] as List)
                  .map((e) => (e as Map).cast<String, Object?>())
                  .toList(),
      );

  Map<String, Object?> toJson() => {
    'checked': checked,
    if (videos != null) 'videos': videos!,
  };
}

class SaveStyleRequest {
  const SaveStyleRequest({
    required this.name,
    required this.tokens,
    this.id,
    this.description,
    this.activate,
  });

  final String name;
  final Map<String, Object?> tokens;
  final String? id;
  final String? description;
  final bool? activate;

  factory SaveStyleRequest.fromJson(Map<String, Object?> json) =>
      SaveStyleRequest(
        name: json['name'] as String,
        tokens: (json['tokens'] as Map).cast<String, Object?>(),
        id: json['id'] == null ? null : json['id'] as String,
        description: json['description'] == null
            ? null
            : json['description'] as String,
        activate: json['activate'] == null ? null : json['activate'] as bool,
      );

  Map<String, Object?> toJson() => {
    'name': name,
    'tokens': tokens,
    if (id != null) 'id': id!,
    if (description != null) 'description': description!,
    if (activate != null) 'activate': activate!,
  };
}

class SetActiveStyleRequest {
  const SetActiveStyleRequest({required this.id});

  final String id;

  factory SetActiveStyleRequest.fromJson(Map<String, Object?> json) =>
      SetActiveStyleRequest(id: json['id'] as String);

  Map<String, Object?> toJson() => {'id': id};
}

class ActiveStyle {
  const ActiveStyle({required this.active});

  final String active;

  factory ActiveStyle.fromJson(Map<String, Object?> json) =>
      ActiveStyle(active: json['active'] as String);

  Map<String, Object?> toJson() => {'active': active};
}

class ExportStyleResponse {
  const ExportStyleResponse({required this.path});

  final String path;

  factory ExportStyleResponse.fromJson(Map<String, Object?> json) =>
      ExportStyleResponse(path: json['path'] as String);

  Map<String, Object?> toJson() => {'path': path};
}

class ImportStyleRequest {
  const ImportStyleRequest({required this.file});

  /// Path of the file on the engine's machine
  final String file;

  factory ImportStyleRequest.fromJson(Map<String, Object?> json) =>
      ImportStyleRequest(file: json['file'] as String);

  Map<String, Object?> toJson() => {'file': file};
}

class PreviewStyleRequest {
  const PreviewStyleRequest({this.tokens});

  final Map<String, Object?>? tokens;

  factory PreviewStyleRequest.fromJson(Map<String, Object?> json) =>
      PreviewStyleRequest(
        tokens: json['tokens'] == null
            ? null
            : (json['tokens'] as Map).cast<String, Object?>(),
      );

  Map<String, Object?> toJson() => {if (tokens != null) 'tokens': tokens!};
}

class GenerateStyleRequest {
  const GenerateStyleRequest({this.description, this.image});

  final String? description;
  final String? image;

  factory GenerateStyleRequest.fromJson(Map<String, Object?> json) =>
      GenerateStyleRequest(
        description: json['description'] == null
            ? null
            : json['description'] as String,
        image: json['image'] == null ? null : json['image'] as String,
      );

  Map<String, Object?> toJson() => {
    if (description != null) 'description': description!,
    if (image != null) 'image': image!,
  };
}

class TaskStarted {
  const TaskStarted({required this.jobId});

  final String jobId;

  factory TaskStarted.fromJson(Map<String, Object?> json) =>
      TaskStarted(jobId: json['job_id'] as String);

  Map<String, Object?> toJson() => {'job_id': jobId};
}

class AdjustStyleRequest {
  const AdjustStyleRequest({
    required this.tokens,
    required this.request,
    this.image,
  });

  final Map<String, Object?> tokens;
  final String request;
  final String? image;

  factory AdjustStyleRequest.fromJson(Map<String, Object?> json) =>
      AdjustStyleRequest(
        tokens: (json['tokens'] as Map).cast<String, Object?>(),
        request: json['request'] as String,
        image: json['image'] == null ? null : json['image'] as String,
      );

  Map<String, Object?> toJson() => {
    'tokens': tokens,
    'request': request,
    if (image != null) 'image': image!,
  };
}

class StylePaletteRequest {
  const StylePaletteRequest({this.image});

  final String? image;

  factory StylePaletteRequest.fromJson(Map<String, Object?> json) =>
      StylePaletteRequest(
        image: json['image'] == null ? null : json['image'] as String,
      );

  Map<String, Object?> toJson() => {if (image != null) 'image': image!};
}

class StylePaletteResponse {
  const StylePaletteResponse({required this.colors, required this.suggested});

  final List<String> colors;
  final Map<String, Object?> suggested;

  factory StylePaletteResponse.fromJson(Map<String, Object?> json) =>
      StylePaletteResponse(
        colors: (json['colors'] as List).map((e) => e as String).toList(),
        suggested: (json['suggested'] as Map).cast<String, Object?>(),
      );

  Map<String, Object?> toJson() => {'colors': colors, 'suggested': suggested};
}

class UploadLogoRequest {
  const UploadLogoRequest({required this.data});

  final String data;

  factory UploadLogoRequest.fromJson(Map<String, Object?> json) =>
      UploadLogoRequest(data: json['data'] as String);

  Map<String, Object?> toJson() => {'data': data};
}

class DownloadWhisperRequest {
  const DownloadWhisperRequest({this.model});

  final String? model;

  factory DownloadWhisperRequest.fromJson(Map<String, Object?> json) =>
      DownloadWhisperRequest(
        model: json['model'] == null ? null : json['model'] as String,
      );

  Map<String, Object?> toJson() => {if (model != null) 'model': model!};
}

class ListAgentsResponse {
  const ListAgentsResponse({required this.agents});

  final List<AgentStatus> agents;

  factory ListAgentsResponse.fromJson(Map<String, Object?> json) =>
      ListAgentsResponse(
        agents: (json['agents'] as List)
            .map(
              (e) => AgentStatus.fromJson((e as Map).cast<String, Object?>()),
            )
            .toList(),
      );

  Map<String, Object?> toJson() => {
    'agents': agents.map((e) => e.toJson()).toList(),
  };
}

class TestAgentRequest {
  const TestAgentRequest({this.model});

  final String? model;

  factory TestAgentRequest.fromJson(Map<String, Object?> json) =>
      TestAgentRequest(
        model: json['model'] == null ? null : json['model'] as String,
      );

  Map<String, Object?> toJson() => {if (model != null) 'model': model!};
}

class TestAgentResponse {
  const TestAgentResponse({
    this.name,
    required this.ok,
    this.seconds,
    this.answer,
    this.error,
  });

  final String? name;
  final bool ok;
  final double? seconds;

  /// The start of what it answered
  final String? answer;
  final String? error;

  factory TestAgentResponse.fromJson(Map<String, Object?> json) =>
      TestAgentResponse(
        name: json['name'] == null ? null : json['name'] as String,
        ok: json['ok'] as bool,
        seconds: json['seconds'] == null
            ? null
            : (json['seconds'] as num).toDouble(),
        answer: json['answer'] == null ? null : json['answer'] as String,
        error: json['error'] == null ? null : json['error'] as String,
      );

  Map<String, Object?> toJson() => {
    if (name != null) 'name': name!,
    'ok': ok,
    if (seconds != null) 'seconds': seconds!,
    if (answer != null) 'answer': answer!,
    if (error != null) 'error': error!,
  };
}

class LoginAgentResponse {
  const LoginAgentResponse({required this.command});

  final String command;

  factory LoginAgentResponse.fromJson(Map<String, Object?> json) =>
      LoginAgentResponse(command: json['command'] as String);

  Map<String, Object?> toJson() => {'command': command};
}

class InstallAgentResponse {
  const InstallAgentResponse({this.command, this.opened});

  /// The installer run in a terminal
  final String? command;

  /// The download page opened in the browser
  final String? opened;

  factory InstallAgentResponse.fromJson(Map<String, Object?> json) =>
      InstallAgentResponse(
        command: json['command'] == null ? null : json['command'] as String,
        opened: json['opened'] == null ? null : json['opened'] as String,
      );

  Map<String, Object?> toJson() => {
    if (command != null) 'command': command!,
    if (opened != null) 'opened': opened!,
  };
}

class PullOllamaRequest {
  const PullOllamaRequest({required this.model});

  final String model;

  factory PullOllamaRequest.fromJson(Map<String, Object?> json) =>
      PullOllamaRequest(model: json['model'] as String);

  Map<String, Object?> toJson() => {'model': model};
}

class PullOllamaResponse {
  const PullOllamaResponse({required this.model, required this.status});

  final String model;
  final String status;

  factory PullOllamaResponse.fromJson(Map<String, Object?> json) =>
      PullOllamaResponse(
        model: json['model'] as String,
        status: json['status'] as String,
      );

  Map<String, Object?> toJson() => {'model': model, 'status': status};
}

class SaveOpenrouterKeyRequest {
  const SaveOpenrouterKeyRequest({required this.key});

  final String key;

  factory SaveOpenrouterKeyRequest.fromJson(Map<String, Object?> json) =>
      SaveOpenrouterKeyRequest(key: json['key'] as String);

  Map<String, Object?> toJson() => {'key': key};
}

class OpenUrlRequest {
  const OpenUrlRequest({required this.url});

  final String url;

  factory OpenUrlRequest.fromJson(Map<String, Object?> json) =>
      OpenUrlRequest(url: json['url'] as String);

  Map<String, Object?> toJson() => {'url': url};
}

class BrowseDirsItem {
  const BrowseDirsItem({required this.name, required this.path});

  final String name;
  final String path;

  factory BrowseDirsItem.fromJson(Map<String, Object?> json) => BrowseDirsItem(
    name: json['name'] as String,
    path: json['path'] as String,
  );

  Map<String, Object?> toJson() => {'name': name, 'path': path};
}

class RecordingsRecordingsItem {
  const RecordingsRecordingsItem({
    required this.name,
    required this.path,
    required this.folder,
    required this.ext,
    required this.size,
    required this.modified,
    this.duration,
    this.width,
    this.height,
    required this.edits,
  });

  final String name;
  final String path;
  final String folder;
  final String ext;
  final int size;
  final String modified;
  final double? duration;
  final int? width;
  final int? height;
  final List<RecordingsRecordingsItemEditsItem> edits;

  factory RecordingsRecordingsItem.fromJson(Map<String, Object?> json) =>
      RecordingsRecordingsItem(
        name: json['name'] as String,
        path: json['path'] as String,
        folder: json['folder'] as String,
        ext: json['ext'] as String,
        size: (json['size'] as num).toInt(),
        modified: json['modified'] as String,
        duration: json['duration'] == null
            ? null
            : (json['duration'] as num).toDouble(),
        width: json['width'] == null ? null : (json['width'] as num).toInt(),
        height: json['height'] == null ? null : (json['height'] as num).toInt(),
        edits: (json['edits'] as List)
            .map(
              (e) => RecordingsRecordingsItemEditsItem.fromJson(
                (e as Map).cast<String, Object?>(),
              ),
            )
            .toList(),
      );

  Map<String, Object?> toJson() => {
    'name': name,
    'path': path,
    'folder': folder,
    'ext': ext,
    'size': size,
    'modified': modified,
    if (duration != null) 'duration': duration!,
    if (width != null) 'width': width!,
    if (height != null) 'height': height!,
    'edits': edits.map((e) => e.toJson()).toList(),
  };
}

class VideoSummaryPublished {
  const VideoSummaryPublished({
    this.privacy,
    this.publishAt,
    this.publishedAt,
    this.count,
  });

  final String? privacy;
  final String? publishAt;
  final String? publishedAt;
  final int? count;

  factory VideoSummaryPublished.fromJson(Map<String, Object?> json) =>
      VideoSummaryPublished(
        privacy: json['privacy'] == null ? null : json['privacy'] as String,
        publishAt: json['publish_at'] == null
            ? null
            : json['publish_at'] as String,
        publishedAt: json['published_at'] == null
            ? null
            : json['published_at'] as String,
        count: json['count'] == null ? null : (json['count'] as num).toInt(),
      );

  Map<String, Object?> toJson() => {
    if (privacy != null) 'privacy': privacy!,
    if (publishAt != null) 'publish_at': publishAt!,
    if (publishedAt != null) 'published_at': publishedAt!,
    if (count != null) 'count': count!,
  };
}

class VideoDetailPlan {
  const VideoDetailPlan({this.keptSegments, this.droppedBlocks});

  final int? keptSegments;
  final Object? droppedBlocks;

  factory VideoDetailPlan.fromJson(Map<String, Object?> json) =>
      VideoDetailPlan(
        keptSegments: json['kept_segments'] == null
            ? null
            : (json['kept_segments'] as num).toInt(),
        droppedBlocks: json['dropped_blocks'],
      );

  Map<String, Object?> toJson() => {
    if (keptSegments != null) 'kept_segments': keptSegments!,
    if (droppedBlocks != null) 'dropped_blocks': droppedBlocks,
  };
}

class PlanKeptSegmentsItem {
  const PlanKeptSegmentsItem({
    required this.index,
    required this.start,
    required this.end,
    required this.duration,
    this.summary,
    required this.text,
  });

  final int index;
  final double start;
  final double end;
  final double duration;
  final String? summary;

  /// what is said in it
  final String text;

  factory PlanKeptSegmentsItem.fromJson(Map<String, Object?> json) =>
      PlanKeptSegmentsItem(
        index: (json['index'] as num).toInt(),
        start: (json['start'] as num).toDouble(),
        end: (json['end'] as num).toDouble(),
        duration: (json['duration'] as num).toDouble(),
        summary: json['summary'] == null ? null : json['summary'] as String,
        text: json['text'] as String,
      );

  Map<String, Object?> toJson() => {
    'index': index,
    'start': start,
    'end': end,
    'duration': duration,
    if (summary != null) 'summary': summary!,
    'text': text,
  };
}

class PlanCutsItem {
  const PlanCutsItem({
    required this.start,
    required this.end,
    required this.duration,
    this.reason,
    this.type,
  });

  final double start;
  final double end;
  final double duration;
  final String? reason;
  final String? type;

  factory PlanCutsItem.fromJson(Map<String, Object?> json) => PlanCutsItem(
    start: (json['start'] as num).toDouble(),
    end: (json['end'] as num).toDouble(),
    duration: (json['duration'] as num).toDouble(),
    reason: json['reason'] == null ? null : json['reason'] as String,
    type: json['type'] == null ? null : json['type'] as String,
  );

  Map<String, Object?> toJson() => {
    'start': start,
    'end': end,
    'duration': duration,
    if (reason != null) 'reason': reason!,
    if (type != null) 'type': type!,
  };
}

class EffectsEffectsItem {
  const EffectsEffectsItem({
    required this.index,
    required this.type,
    required this.start,
    required this.end,
    this.scale,
    this.file,
  });

  final int index;
  final String type;

  /// original time
  final double start;
  final double end;
  final double? scale;
  final String? file;

  factory EffectsEffectsItem.fromJson(Map<String, Object?> json) =>
      EffectsEffectsItem(
        index: (json['index'] as num).toInt(),
        type: json['type'] as String,
        start: (json['start'] as num).toDouble(),
        end: (json['end'] as num).toDouble(),
        scale: json['scale'] == null ? null : (json['scale'] as num).toDouble(),
        file: json['file'] == null ? null : json['file'] as String,
      );

  Map<String, Object?> toJson() => {
    'index': index,
    'type': type,
    'start': start,
    'end': end,
    if (scale != null) 'scale': scale!,
    if (file != null) 'file': file!,
  };
}

class ResultFilesValue {
  const ResultFilesValue({required this.path, required this.size});

  final String path;
  final int size;

  factory ResultFilesValue.fromJson(Map<String, Object?> json) =>
      ResultFilesValue(
        path: json['path'] as String,
        size: (json['size'] as num).toInt(),
      );

  Map<String, Object?> toJson() => {'path': path, 'size': size};
}

class ShortsStateClipsItem {
  const ShortsStateClipsItem({
    required this.number,
    required this.start,
    required this.end,
    required this.duration,
    this.score,
    required this.hook,
    this.reason,
    required this.text,
    required this.overlaps,
    this.short,
  });

  /// what /shorts/cut takes; the N of _shortN
  final int number;
  final double start;
  final double end;
  final double duration;
  final double? score;
  final String hook;
  final String? reason;
  final String text;
  final bool overlaps;
  final ShortsStateClipsItemShort? short;

  factory ShortsStateClipsItem.fromJson(Map<String, Object?> json) =>
      ShortsStateClipsItem(
        number: (json['number'] as num).toInt(),
        start: (json['start'] as num).toDouble(),
        end: (json['end'] as num).toDouble(),
        duration: (json['duration'] as num).toDouble(),
        score: json['score'] == null ? null : (json['score'] as num).toDouble(),
        hook: json['hook'] as String,
        reason: json['reason'] == null ? null : json['reason'] as String,
        text: json['text'] as String,
        overlaps: json['overlaps'] as bool,
        short: json['short'] == null
            ? null
            : ShortsStateClipsItemShort.fromJson(
                (json['short'] as Map).cast<String, Object?>(),
              ),
      );

  Map<String, Object?> toJson() => {
    'number': number,
    'start': start,
    'end': end,
    'duration': duration,
    if (score != null) 'score': score!,
    'hook': hook,
    if (reason != null) 'reason': reason!,
    'text': text,
    'overlaps': overlaps,
    if (short != null) 'short': short!.toJson(),
  };
}

class ShortsStateJob {
  const ShortsStateJob({this.id, this.status});

  final String? id;
  final String? status;

  factory ShortsStateJob.fromJson(Map<String, Object?> json) => ShortsStateJob(
    id: json['id'] == null ? null : json['id'] as String,
    status: json['status'] == null ? null : json['status'] as String,
  );

  Map<String, Object?> toJson() => {
    if (id != null) 'id': id!,
    if (status != null) 'status': status!,
  };
}

class PublishStateDefaults {
  const PublishStateDefaults({
    this.title,
    this.description,
    this.tags,
    this.privacy,
  });

  final String? title;
  final String? description;
  final List<String>? tags;
  final String? privacy;

  factory PublishStateDefaults.fromJson(Map<String, Object?> json) =>
      PublishStateDefaults(
        title: json['title'] == null ? null : json['title'] as String,
        description: json['description'] == null
            ? null
            : json['description'] as String,
        tags: json['tags'] == null
            ? null
            : (json['tags'] as List).map((e) => e as String).toList(),
        privacy: json['privacy'] == null ? null : json['privacy'] as String,
      );

  Map<String, Object?> toJson() => {
    if (title != null) 'title': title!,
    if (description != null) 'description': description!,
    if (tags != null) 'tags': tags!,
    if (privacy != null) 'privacy': privacy!,
  };
}

class PublishStateLimits {
  const PublishStateLimits({required this.title, required this.description});

  final int title;
  final int description;

  factory PublishStateLimits.fromJson(Map<String, Object?> json) =>
      PublishStateLimits(
        title: (json['title'] as num).toInt(),
        description: (json['description'] as num).toInt(),
      );

  Map<String, Object?> toJson() => {'title': title, 'description': description};
}

class PublishStatePublishedItem {
  const PublishStatePublishedItem({
    this.videoId,
    this.url,
    this.title,
    this.privacy,
    this.publishAt,
  });

  final String? videoId;
  final String? url;
  final String? title;
  final String? privacy;
  final String? publishAt;

  factory PublishStatePublishedItem.fromJson(Map<String, Object?> json) =>
      PublishStatePublishedItem(
        videoId: json['video_id'] == null ? null : json['video_id'] as String,
        url: json['url'] == null ? null : json['url'] as String,
        title: json['title'] == null ? null : json['title'] as String,
        privacy: json['privacy'] == null ? null : json['privacy'] as String,
        publishAt: json['publish_at'] == null
            ? null
            : json['publish_at'] as String,
      );

  Map<String, Object?> toJson() => {
    if (videoId != null) 'video_id': videoId!,
    if (url != null) 'url': url!,
    if (title != null) 'title': title!,
    if (privacy != null) 'privacy': privacy!,
    if (publishAt != null) 'publish_at': publishAt!,
  };
}

class PublishStateJob {
  const PublishStateJob({this.id, this.status});

  final String? id;
  final String? status;

  factory PublishStateJob.fromJson(Map<String, Object?> json) =>
      PublishStateJob(
        id: json['id'] == null ? null : json['id'] as String,
        status: json['status'] == null ? null : json['status'] as String,
      );

  Map<String, Object?> toJson() => {
    if (id != null) 'id': id!,
    if (status != null) 'status': status!,
  };
}

class TrendVideosItem {
  const TrendVideosItem({
    this.id,
    this.title,
    this.publishedAt,
    this.youtubeId,
    this.lessons,
  });

  final String? id;
  final String? title;
  final String? publishedAt;
  final String? youtubeId;
  final int? lessons;

  factory TrendVideosItem.fromJson(
    Map<String, Object?> json,
  ) => TrendVideosItem(
    id: json['id'] == null ? null : json['id'] as String,
    title: json['title'] == null ? null : json['title'] as String,
    publishedAt: json['published_at'] == null
        ? null
        : json['published_at'] as String,
    youtubeId: json['youtube_id'] == null ? null : json['youtube_id'] as String,
    lessons: json['lessons'] == null ? null : (json['lessons'] as num).toInt(),
  );

  Map<String, Object?> toJson() => {
    if (id != null) 'id': id!,
    if (title != null) 'title': title!,
    if (publishedAt != null) 'published_at': publishedAt!,
    if (youtubeId != null) 'youtube_id': youtubeId!,
    if (lessons != null) 'lessons': lessons!,
  };
}

class StylesFontsItem {
  const StylesFontsItem({required this.id, required this.label});

  final String id;
  final String label;

  factory StylesFontsItem.fromJson(Map<String, Object?> json) =>
      StylesFontsItem(id: json['id'] as String, label: json['label'] as String);

  Map<String, Object?> toJson() => {'id': id, 'label': label};
}

class StylesPositions {
  const StylesPositions({required this.lowerThird, required this.cta});

  final List<String> lowerThird;
  final List<String> cta;

  factory StylesPositions.fromJson(Map<String, Object?> json) =>
      StylesPositions(
        lowerThird: (json['lower_third'] as List)
            .map((e) => e as String)
            .toList(),
        cta: (json['cta'] as List).map((e) => e as String).toList(),
      );

  Map<String, Object?> toJson() => {'lower_third': lowerThird, 'cta': cta};
}

class RecordingsRecordingsItemEditsItem {
  const RecordingsRecordingsItemEditsItem({
    required this.id,
    this.name,
    required this.status,
  });

  final String id;
  final String? name;
  final VideoStatus status;

  factory RecordingsRecordingsItemEditsItem.fromJson(
    Map<String, Object?> json,
  ) => RecordingsRecordingsItemEditsItem(
    id: json['id'] as String,
    name: json['name'] == null ? null : json['name'] as String,
    status: VideoStatus(json['status'] as String),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    if (name != null) 'name': name!,
    'status': status.value,
  };
}

class ShortsStateClipsItemShort {
  const ShortsStateClipsItemShort({
    this.id,
    this.status,
    this.overwriteWarning,
  });

  final String? id;
  final VideoStatus? status;
  final String? overwriteWarning;

  factory ShortsStateClipsItemShort.fromJson(Map<String, Object?> json) =>
      ShortsStateClipsItemShort(
        id: json['id'] == null ? null : json['id'] as String,
        status: json['status'] == null
            ? null
            : VideoStatus(json['status'] as String),
        overwriteWarning: json['overwrite_warning'] == null
            ? null
            : json['overwrite_warning'] as String,
      );

  Map<String, Object?> toJson() => {
    if (id != null) 'id': id!,
    if (status != null) 'status': status!.value,
    if (overwriteWarning != null) 'overwrite_warning': overwriteWarning!,
  };
}

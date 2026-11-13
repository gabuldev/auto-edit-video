import 'dart:async';

import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

import 'theme.dart';

/// What to play: a file the engine serves (with its token), optionally only
/// a window of it (Revisar cortes plays one segment of the recording).
class PlayerSource {
  const PlayerSource(this.url, {this.headers = const {}, this.start, this.end, this.autoplay = false, this.control});

  final Uri url;
  final Map<String, String> headers;
  final Duration? start;
  final Duration? end;
  final bool autoplay;

  /// Where it is now, and a way to jump (the retention drops, "usar o tempo do player").
  final PlayerControl? control;
}

/// The screen's handle on a player: its position, and seeking.
class PlayerControl extends ChangeNotifier {
  Duration _position = Duration.zero;
  Future<void> Function(Duration)? _seek;

  Duration get position => _position;

  /// The player reports where it is.
  void report(Duration p) {
    if ((p - _position).abs() < const Duration(milliseconds: 200)) return;
    _position = p;
    notifyListeners();
  }

  /// The player says how to jump; null when it goes away.
  void attach(Future<void> Function(Duration)? seek) => _seek = seek;

  /// Jump there and play.
  Future<void> seekTo(Duration d) async {
    _position = d;
    notifyListeners();
    await _seek?.call(d);
  }
}

typedef PlayerBuilder = Widget Function(BuildContext context, PlayerSource source);

/// Which player the screens get. Without one above them, media_kit (libmpv);
/// the widget tests put a stand-in here, since there is no libmpv in them.
class PlayerScope extends InheritedWidget {
  const PlayerScope({super.key, required this.builder, required super.child});

  final PlayerBuilder builder;

  static PlayerBuilder of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<PlayerScope>()?.builder ??
      (context, source) => MediaKitPlayer(key: ValueKey(source.url.toString()), source: source);

  @override
  bool updateShouldNotify(PlayerScope old) => old.builder != builder;
}

/// A player with the usual controls (play, seek bar, volume, full screen).
class VideoPlayer extends StatelessWidget {
  const VideoPlayer(this.source, {super.key});
  final PlayerSource source;

  @override
  Widget build(BuildContext context) => PlayerScope.of(context)(context, source);
}

class MediaKitPlayer extends StatefulWidget {
  const MediaKitPlayer({super.key, required this.source});
  final PlayerSource source;

  @override
  State<MediaKitPlayer> createState() => _MediaKitPlayerState();
}

class _MediaKitPlayerState extends State<MediaKitPlayer> {
  late final Player _player = Player();
  late final VideoController _controller = VideoController(_player);
  StreamSubscription<Duration>? _position;

  @override
  void initState() {
    super.initState();
    final s = widget.source;
    _player.open(
      Media(s.url.toString(), httpHeaders: s.headers, start: s.start, end: s.end),
      play: s.autoplay,
    );
    final control = s.control;
    if (control != null) {
      _position = _player.stream.position.listen(control.report);
      control.attach((d) async {
        await _player.seek(d);
        await _player.play();
      });
    }
  }

  @override
  void dispose() {
    unawaited(_position?.cancel());
    widget.source.control?.attach(null);
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ColoredBox(
    color: Colors.black,
    child: MaterialDesktopVideoControlsTheme(
      normal: const MaterialDesktopVideoControlsThemeData(seekBarPositionColor: Tokens.accent),
      fullscreen: const MaterialDesktopVideoControlsThemeData(seekBarPositionColor: Tokens.accent),
      child: Video(controller: _controller, controls: MaterialDesktopVideoControls),
    ),
  );
}

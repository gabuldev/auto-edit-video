import 'package:desktop_drop/desktop_drop.dart';
import 'package:flutter/material.dart';

const videoExts = ['mp4', 'mov', 'mkv', 'avi', 'webm', 'm4v', 'mts', 'm2ts'];
const notVideo = 'Isso não é um vídeo que o pipeline abre (mp4, mov, mkv, webm…).';

bool isVideo(String path) => videoExts.contains(path.split('.').last.toLowerCase());

/// Files dropped on the window over [child] (desktop_drop): [onOver] while
/// one is dragged over, then [onVideo] with the first video, or [onFail].
class VideoDrop extends StatelessWidget {
  const VideoDrop({
    super.key,
    required this.child,
    required this.onVideo,
    required this.onFail,
    this.onOver,
    this.enabled = true,
  });

  final Widget child;
  final ValueChanged<String> onVideo;
  final ValueChanged<String> onFail;
  final ValueChanged<bool>? onOver;
  final bool enabled;

  /// Paths from a drop: the first video, or the reason there is none.
  static (String?, String?) pick(Iterable<String> paths) {
    for (final p in paths) {
      if (isVideo(p)) return (p, null);
    }
    return (null, notVideo);
  }

  @override
  Widget build(BuildContext context) => DropTarget(
    enable: enabled,
    onDragEntered: (_) => onOver?.call(true),
    onDragExited: (_) => onOver?.call(false),
    onDragDone: (d) {
      onOver?.call(false);
      final (path, error) = pick(d.files.map((f) => f.path));
      if (path != null) {
        onVideo(path);
      } else {
        onFail(error!);
      }
    },
    child: child,
  );
}

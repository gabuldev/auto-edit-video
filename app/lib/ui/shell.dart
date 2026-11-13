import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../engine/status.dart';
import '../platform.dart';
import 'edits/edits_screen.dart';
import 'new_edit_screen.dart';
import 'pipeline/cuts_screen.dart';
import 'pipeline/pipeline_screen.dart';
import 'recordings_screen.dart';
import 'result/result_screen.dart';
import 'settings/settings_screen.dart';
import 'shorts_screen.dart';
import 'styles/styles_screen.dart';
import 'trend_screen.dart';
import 'theme.dart';
import 'welcome.dart';
import 'widgets.dart';

/// The sections of the sidebar (same as the Tauri app).
enum Section {
  edits('Edições', Icons.video_library_outlined),
  library('Biblioteca', Icons.movie_outlined),
  retention('Retenção', Icons.insights_outlined),
  styles('Estilos', Icons.palette_outlined),
  settings('Configurações', Icons.settings_outlined);

  const Section(this.label, this.icon);
  final String label;
  final IconData icon;
}

/// The screens of one edit, over Edições.
enum VideoPage { pipeline, cuts, result, shorts }

/// Sidebar + the current screen, with the offline banner on top of it.
class Shell extends StatefulWidget {
  const Shell({
    super.key,
    required this.status,
    required this.client,
    required this.prefs,
    this.pickers = const NativePickers(),
  });

  final EngineStatus status;
  final AutoEditClient client;
  final AppPrefs prefs;
  final Pickers pickers;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  var _section = Section.edits;

  /// The first-run screen, over whatever section is selected.
  var _welcome = false;

  /// What the engine says is missing to edit (the banner in Edições).
  String? _missing;

  /// Novo edit, over Edições: (video already chosen, its type).
  (String?, VideoType?)? _newEdit;

  /// One edit's screen, over Edições.
  (String, VideoPage)? _video;

  @override
  void initState() {
    super.initState();
    unawaited(_checkSetup(onLaunch: true));
  }

  /// On launch, a machine that can't edit yet goes straight to the welcome
  /// screen (unless the person chose "configurar depois"); otherwise the
  /// banner in Edições says what is missing.
  Future<void> _checkSetup({bool onLaunch = false}) async {
    final Setup s;
    try {
      s = await widget.client.api.getSetup();
    } catch (_) {
      return;
    }
    if (!mounted) return;
    setState(() {
      _missing = missingForSetup(s);
      if (onLaunch && !s.ready && !widget.prefs.setupLater) _welcome = true;
    });
  }

  void _select(Section s) {
    setState(() {
      _welcome = false;
      _newEdit = null;
      _video = null;
      _section = s;
    });
    // Back from Configurações, an agent may be working now.
    unawaited(_checkSetup());
  }

  void _leaveWelcome({bool later = false}) {
    if (later) widget.prefs.setupLater = true;
    _select(Section.edits);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Sidebar(status: widget.status, current: _welcome ? null : _section, onSelect: _select),
          Expanded(
            child: ListenableBuilder(
              listenable: widget.status,
              builder: (context, _) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (widget.status.ok == false) OfflineBanner(onRetry: widget.status.check),
                  if (!_welcome && _section == Section.edits && _missing != null)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(28, 16, 28, 0),
                      child: Notice(
                        _missing!,
                        tone: Tone.warn,
                        action: SmallButton('Configurar', onPressed: () => setState(() => _welcome = true)),
                      ),
                    ),
                  Expanded(child: _screen()),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _openNewEdit({String? path, VideoType? type}) => setState(() {
    _welcome = false;
    _section = Section.edits;
    _video = null;
    _newEdit = (path, type);
  });

  /// Resultado goes back where it came from: the pipeline, or Edições.
  bool _resultFromPipeline = false;

  void _openVideo(String id, VideoPage page) => setState(() {
    if (page == VideoPage.result) _resultFromPipeline = _video?.$2 == VideoPage.pipeline;
    _welcome = false;
    // from Retenção, the video screens stay under it (and go back there)
    if (_section != Section.retention) _section = Section.edits;
    _newEdit = null;
    _video = (id, page);
  });

  Widget _screen() {
    if (_welcome) {
      return WelcomeScreen(client: widget.client, onDone: _leaveWelcome, onLater: () => _leaveWelcome(later: true));
    }
    final newEdit = _newEdit;
    if (newEdit != null) {
      return NewEditScreen(
        // a new video chosen elsewhere starts a fresh form
        key: ValueKey(newEdit),
        client: widget.client,
        pickers: widget.pickers,
        path: newEdit.$1,
        type: newEdit.$2,
        onStarted: (id) => _openVideo(id, VideoPage.pipeline),
        onCancel: () => _select(Section.edits),
      );
    }
    final video = _video;
    if (video != null) {
      final (id, page) = video;
      return switch (page) {
        VideoPage.pipeline => PipelineScreen(
          key: ValueKey(video),
          client: widget.client,
          id: id,
          onBack: () => _select(Section.edits),
          onCuts: () => _openVideo(id, VideoPage.cuts),
          onResult: () => _openVideo(id, VideoPage.result),
        ),
        VideoPage.cuts => CutsScreen(
          key: ValueKey(video),
          client: widget.client,
          id: id,
          onBack: () => _openVideo(id, VideoPage.pipeline),
          onRecut: () => _openVideo(id, VideoPage.pipeline),
        ),
        VideoPage.result => ResultScreen(
          key: ValueKey(video),
          client: widget.client,
          id: id,
          onBack: () => _resultFromPipeline ? _openVideo(id, VideoPage.pipeline) : _select(_section),
          onPipeline: () => _openVideo(id, VideoPage.pipeline),
          onSettings: () => _select(Section.settings),
          onShorts: () => _openVideo(id, VideoPage.shorts),
          pickers: widget.pickers,
        ),
        VideoPage.shorts => ShortsScreen(
          key: ValueKey(video),
          client: widget.client,
          id: id,
          onBack: () => _openVideo(id, VideoPage.result),
          onCut: () => _select(Section.edits),
          onOpen: (short) => _openVideo(short, VideoPage.pipeline),
        ),
      };
    }
    return switch (_section) {
      Section.edits => EditsScreen(
        client: widget.client,
        pickers: widget.pickers,
        onNewEdit: ({String? path}) => _openNewEdit(path: path),
        onOpen: (id, {bool result = false}) => _openVideo(id, result ? VideoPage.result : VideoPage.pipeline),
      ),
      Section.library => RecordingsScreen(
        client: widget.client,
        onEdit: (path, type) => _openNewEdit(path: path, type: type),
        onSettings: () => _select(Section.settings),
      ),
      Section.retention => TrendScreen(client: widget.client, onOpen: (id) => _openVideo(id, VideoPage.result)),
      Section.styles => StylesScreen(client: widget.client, pickers: widget.pickers),
      Section.settings => SettingsScreen(client: widget.client, pickers: widget.pickers, status: widget.status),
    };
  }
}

class Sidebar extends StatelessWidget {
  const Sidebar({super.key, required this.status, required this.current, required this.onSelect});

  final EngineStatus status;

  /// Null while the welcome screen is up.
  final Section? current;
  final ValueChanged<Section> onSelect;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 240,
      padding: const EdgeInsets.fromLTRB(14, 20, 14, 20),
      decoration: const BoxDecoration(
        color: Tokens.sidebar,
        border: Border(right: BorderSide(color: Tokens.borderSoft)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(8, 6, 8, 22),
            child: Row(
              children: [
                BrandLogo(),
                SizedBox(width: 11),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'gabuldev',
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                      ),
                      Text(
                        'auto-edit',
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontFamily: Tokens.mono, fontSize: 10, color: Tokens.faint, letterSpacing: .5),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          for (final s in Section.values) _NavItem(section: s, active: s == current, onTap: () => onSelect(s)),
          const Spacer(),
          const Divider(height: 1),
          const SizedBox(height: 14),
          EngineIndicator(status: status),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.section, required this.active, required this.onTap});

  final Section section;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = active ? Tokens.accent : Tokens.dim;
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Material(
        color: active ? Tokens.navActive : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Icon(section.icon, size: 19, color: color),
                const SizedBox(width: 11),
                Flexible(
                  child: Text(
                    section.label,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 14,
                      color: color,
                      fontWeight: active ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The engine at the foot of the sidebar: a quiet line when all is well, a
/// louder one (and "Reiniciar o motor") when it stops answering.
class EngineIndicator extends StatelessWidget {
  const EngineIndicator({super.key, required this.status});
  final EngineStatus status;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: status,
      builder: (context, _) {
        final off = status.ok == false && !status.restarting;
        final (Color dot, Color? bg) = status.restarting
            ? (Tokens.run, Tokens.run.withValues(alpha: .08))
            : status.ok == true
            ? (Tokens.ok, null)
            : off
            ? (Tokens.err, Tokens.err.withValues(alpha: .08))
            : (Tokens.faint, null);
        final label = status.restarting
            ? 'Reiniciando o motor…'
            : status.ok == true
            ? 'Motor conectado'
            : off
            ? 'Motor sem resposta'
            : 'Verificando o motor…';
        final sub =
            status.error ??
            (status.restarting
                ? 'Leva alguns segundos.'
                : !off
                ? null
                : !status.canRestart
                ? 'Rode auto-edit serve no terminal.'
                : status.stuck
                ? 'Não voltou sozinho.'
                : 'Tentando reconectar…');
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
              decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(10)),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    margin: const EdgeInsets.only(top: 5),
                    decoration: BoxDecoration(
                      color: dot,
                      shape: BoxShape.circle,
                      boxShadow: [BoxShadow(color: dot.withValues(alpha: .18), spreadRadius: 3)],
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          label,
                          style: TextStyle(
                            fontSize: 12.5,
                            color: status.ok == true ? Tokens.dim : Tokens.text,
                            fontWeight: status.ok == true ? FontWeight.w400 : FontWeight.w500,
                          ),
                        ),
                        if (sub != null)
                          Text(
                            sub,
                            style: TextStyle(
                              fontSize: 11.5,
                              height: 1.4,
                              color: off ? const Color(0xFFD8A3A3) : Tokens.faint,
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (status.stuck && status.canRestart)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Tooltip(
                  message: 'Para o motor e sobe de novo. Uma edição que estiver rodando é interrompida.',
                  child: OutlinedButton(onPressed: status.restart, child: const Text('Reiniciar o motor')),
                ),
              ),
          ],
        );
      },
    );
  }
}

class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, required this.onRetry});
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(28, 16, 28, 0),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: Tokens.err.withValues(alpha: .08),
        border: Border.all(color: const Color(0xFF3A2530)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Wrap(
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          const Text(
            'Motor offline. ',
            style: TextStyle(fontWeight: FontWeight.w700, color: Color(0xFFF3B0AF)),
          ),
          const Text(
            'O app inicia o motor sozinho; se não subir, rode ',
            style: TextStyle(fontSize: 13, color: Color(0xFFF3B0AF)),
          ),
          const Text('auto-edit serve', style: TextStyle(fontFamily: Tokens.mono, fontSize: 12.5)),
          const Text(' no terminal e ', style: TextStyle(fontSize: 13, color: Color(0xFFF3B0AF))),
          InkWell(
            onTap: onRetry,
            child: const Text('tente de novo', style: TextStyle(fontSize: 13, color: Tokens.accent)),
          ),
          const Text('.', style: TextStyle(fontSize: 13, color: Color(0xFFF3B0AF))),
        ],
      ),
    );
  }
}

/// Topbar like the Tauri app's: title, subtitle, actions on the right.
class TopBar extends StatelessWidget {
  const TopBar({
    super.key,
    required this.title,
    this.subtitle,
    this.subtitleWidget,
    this.actions = const [],
    this.onBack,
  });

  final String title;

  /// A back arrow before the title.
  final VoidCallback? onBack;
  final String? subtitle;

  /// Instead of [subtitle], for one with links.
  final Widget? subtitleWidget;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 70,
      padding: const EdgeInsets.symmetric(horizontal: 28),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Tokens.borderSoft)),
      ),
      child: Row(
        children: [
          if (onBack != null) ...[
            IconButton.outlined(tooltip: 'Voltar', onPressed: onBack, icon: const Icon(Icons.arrow_back, size: 18)),
            const SizedBox(width: 14),
          ],
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                ),
                if (subtitleWidget != null)
                  subtitleWidget!
                else if (subtitle != null)
                  Text(subtitle!, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
              ],
            ),
          ),
          ...actions,
        ],
      ),
    );
  }
}

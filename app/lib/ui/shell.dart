import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';

import '../engine/status.dart';
import 'home.dart';
import 'theme.dart';

/// The sections of the sidebar (same as the Tauri app).
enum Section {
  edits('Edições', Icons.video_library_outlined),
  library('Biblioteca', Icons.movie_outlined),
  styles('Estilos', Icons.palette_outlined),
  settings('Configurações', Icons.settings_outlined);

  const Section(this.label, this.icon);
  final String label;
  final IconData icon;
}

/// Sidebar + the current screen, with the offline banner on top of it.
class Shell extends StatefulWidget {
  const Shell({super.key, required this.status, required this.client});

  final EngineStatus status;
  final AutoEditClient client;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  var _section = Section.edits;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Sidebar(status: widget.status, current: _section, onSelect: (s) => setState(() => _section = s)),
          Expanded(
            child: ListenableBuilder(
              listenable: widget.status,
              builder: (context, _) => Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (widget.status.ok == false) OfflineBanner(onRetry: widget.status.check),
                  Expanded(child: _screen()),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _screen() => switch (_section) {
    Section.edits => HomeScreen(status: widget.status, client: widget.client),
    Section.library => const ComingSoon(title: 'Biblioteca', issue: 139),
    Section.styles => const ComingSoon(title: 'Estilos', issue: 142),
    Section.settings => const ComingSoon(title: 'Configurações', issue: 138),
  };
}

class Sidebar extends StatelessWidget {
  const Sidebar({super.key, required this.status, required this.current, required this.onSelect});

  final EngineStatus status;
  final Section current;
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
  const TopBar({super.key, required this.title, this.subtitle, this.actions = const []});

  final String title;
  final String? subtitle;
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
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                if (subtitle != null) Text(subtitle!, style: const TextStyle(fontSize: 13, color: Tokens.dim)),
              ],
            ),
          ),
          ...actions,
        ],
      ),
    );
  }
}

class ComingSoon extends StatelessWidget {
  const ComingSoon({super.key, required this.title, required this.issue});
  final String title;
  final int issue;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      TopBar(title: title),
      Expanded(
        child: Center(
          child: Text(
            'Esta tela chega na #$issue. Por enquanto, use o app atual.',
            style: const TextStyle(color: Tokens.dim),
          ),
        ),
      ),
    ],
  );
}

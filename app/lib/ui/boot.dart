import 'dart:async';

import 'package:flutter/material.dart';

import 'theme.dart';

/// Until the engine first answers: nothing mounts half-offline. It never
/// gives up, it only says more the longer it takes.
class BootScreen extends StatefulWidget {
  const BootScreen({super.key, this.startError});

  /// Why the app could not start the engine (still waits for one by hand).
  final String? startError;

  @override
  State<BootScreen> createState() => _BootScreenState();
}

class _BootScreenState extends State<BootScreen> {
  final _since = DateTime.now();
  late final Timer _tick;

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
  }

  @override
  void dispose() {
    _tick.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final waited = DateTime.now().difference(_since);
    const hint = TextStyle(fontSize: 12.5, height: 1.55, color: Tokens.faint);
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const BrandLogo(size: 52),
              const SizedBox(height: 12),
              const Text('Auto-Edit', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 26),
              const SizedBox(
                width: 26,
                height: 26,
                child: CircularProgressIndicator(strokeWidth: 2, color: Tokens.accent),
              ),
              const SizedBox(height: 12),
              const Text('Iniciando o motor…', style: TextStyle(fontSize: 13.5, color: Tokens.dim)),
              if (widget.startError != null) ...[
                const SizedBox(height: 12),
                Text(
                  widget.startError!,
                  textAlign: TextAlign.center,
                  style: hint.copyWith(color: Tokens.err),
                ),
              ],
              if (waited.inSeconds >= 15) ...[
                const SizedBox(height: 12),
                const Text('Na primeira abertura pode levar um pouco mais.', textAlign: TextAlign.center, style: hint),
              ],
              if (waited.inSeconds >= 60) ...[
                const SizedBox(height: 12),
                Text(
                  'O motor ainda não respondeu. Se continuar assim, feche e abra o app de novo '
                  '(ou rode auto-edit serve no terminal). Continuo tentando.',
                  textAlign: TextAlign.center,
                  style: hint.copyWith(color: const Color(0xFFF6BCBB)),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

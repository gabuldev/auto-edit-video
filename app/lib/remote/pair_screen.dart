import 'dart:async';
import 'dart:io';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'remote_store.dart';

/// Builds the camera view that reads QR codes; it calls back with the text.
typedef ScannerBuilder = Widget Function(BuildContext context, ValueChanged<String> onCode);

/// What a failed pairing says, in words the person can act on.
String pairingError(Object e, PairingLink link) {
  final where = '${link.config.baseUrl.host}:${link.config.baseUrl.port}';
  if (e is ApiException) return e.message;
  if (e is HandshakeException || e is TlsException) {
    return 'O certificado do computador não é o do QR code. Gere outro QR no computador e tente de novo.';
  }
  if (e is SocketException || e is TimeoutException || e is http.ClientException) {
    return 'Não achei o computador em $where. O celular está na mesma rede Wi-Fi que ele, '
        'e o acesso pela rede está ligado em Configurações → Celular?';
  }
  return 'Não deu pra parear: $e';
}

/// The name this phone shows in the computer's list.
String deviceName() {
  final kind = Platform.isIOS ? 'iPhone' : (Platform.isAndroid ? 'Android' : Platform.operatingSystem);
  final host = Platform.localHostname;
  return host.isEmpty || host == 'localhost' ? kind : '$kind ($host)';
}

/// Trades a scanned QR code for this device's token.
Future<RemoteEngine> pairWith(PairingLink link, {String? name, AutoEditClient Function(EngineConfig)? connect}) async {
  final client = (connect ?? AutoEditClient.new)(link.config);
  try {
    final paired = await client.api
        .pair(PairRequest(code: link.code, name: name ?? deviceName()))
        .timeout(const Duration(seconds: 15));
    return RemoteEngine(
      baseUrl: link.config.baseUrl,
      token: paired.token,
      fingerprint: link.config.fingerprint!,
      name: link.name,
    );
  } finally {
    client.close();
  }
}

/// The phone's first screen: read the QR code the computer shows (or paste
/// its link) and pair.
class PairScreen extends StatefulWidget {
  const PairScreen({super.key, required this.onPaired, this.scanner, this.notice, this.connect});

  final ValueChanged<RemoteEngine> onPaired;

  /// The camera (null: only the paste field, as in tests and on desktop).
  final ScannerBuilder? scanner;

  /// Why we're here again (the token was revoked...).
  final String? notice;

  final AutoEditClient Function(EngineConfig)? connect;

  @override
  State<PairScreen> createState() => _PairScreenState();
}

class _PairScreenState extends State<PairScreen> {
  final _paste = TextEditingController();
  String? _error;
  bool _busy = false;
  String? _lastCode;

  @override
  void dispose() {
    _paste.dispose();
    super.dispose();
  }

  Future<void> _use(String text) async {
    if (_busy) return;
    final link = EngineConfig.pairingLink(text);
    if (link == null) {
      setState(() => _error = 'Esse não é o QR code do Auto-Edit. Abra Configurações → Celular no computador.');
      return;
    }
    if (link.code == _lastCode && _error != null) return; // the camera reads the same failed code again and again
    _lastCode = link.code;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final engine = await pairWith(link, connect: widget.connect);
      if (mounted) widget.onPaired(engine);
    } catch (e) {
      if (mounted) setState(() => _error = pairingError(e, link));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 28, 20, 28),
          children: [
            const Row(
              children: [
                BrandLogo(),
                SizedBox(width: 12),
                Expanded(
                  child: Text('Conectar ao computador', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                ),
              ],
            ),
            const SizedBox(height: 14),
            const Text(
              'No computador, abra o Auto-Edit em Configurações → Celular, ligue o acesso pela rede '
              'e toque em "Parear aparelho". Depois aponte a câmera pro QR code.',
              style: TextStyle(fontSize: 14, color: Tokens.dim, height: 1.5),
            ),
            const SizedBox(height: 18),
            if (widget.notice != null) Notice(widget.notice!, tone: Tone.warn),
            if (_error != null) Notice(_error!),
            if (widget.scanner != null)
              ClipRRect(
                borderRadius: BorderRadius.circular(14),
                child: AspectRatio(
                  aspectRatio: 1,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      widget.scanner!(context, (code) => unawaited(_use(code))),
                      if (_busy)
                        const ColoredBox(
                          color: Color(0x99000000),
                          child: Center(child: CircularProgressIndicator()),
                        ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 18),
            Text(
              widget.scanner != null ? 'Ou cole o link do QR code' : 'Cole o link do QR code',
              style: const TextStyle(fontSize: 12.5, color: Tokens.dim, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _paste,
                    decoration: const InputDecoration(hintText: 'autoedit://pair?…', isDense: true),
                    onSubmitted: (t) => unawaited(_use(t)),
                  ),
                ),
                const SizedBox(width: 8),
                SmallButton(
                  _busy ? 'Pareando…' : 'Parear',
                  primary: true,
                  onPressed: _busy ? null : () => unawaited(_use(_paste.text)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

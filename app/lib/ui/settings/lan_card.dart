import 'dart:async';

import 'package:auto_edit_client/auto_edit_client.dart';
import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../format.dart';
import '../theme.dart';
import '../widgets.dart';

/// The network access (auto_edit/lan.py): on/off, pairing a phone by QR code
/// and the paired devices. Only the engine's own machine can change it.
class LanController extends ChangeNotifier {
  LanController(this.client, {this.every = const Duration(seconds: 2)});

  final AutoEditClient client;

  /// How often the list is refreshed while a QR code is up (to see the phone arrive).
  final Duration every;
  AutoEditApi get _api => client.api;

  LanState? state;
  String? error;
  bool busy = false;

  /// The QR code on screen (null: none).
  Pairing? pairing;

  /// The device whose "Revogar" was clicked once.
  String? revokeArmed;

  Timer? _poll;
  bool _disposed = false;

  Future<void> load() async {
    try {
      final before = state?.devices.length ?? 0;
      state = await _api.getLan();
      error = null;
      // A new device while the QR is up: it paired, the code is spent.
      if (pairing != null && state!.devices.length > before) closePairing();
      if (pairing != null && _expired(pairing!)) closePairing();
    } catch (e) {
      error = 'Não deu pra ler o acesso pela rede: ${errorText(e)}';
    }
    _notify();
  }

  static bool _expired(Pairing p) {
    final at = DateTime.tryParse(p.expiresAt);
    return at != null && DateTime.now().isAfter(at);
  }

  Future<void> toggle(bool on) => _run(() async {
    state = await _api.setLan(SetLanRequest(enabled: on));
    if (!on) closePairing();
  });

  Future<void> pair() => _run(() async {
    pairing = await _api.startPairing();
    _poll?.cancel();
    _poll = Timer.periodic(every, (_) => load());
  });

  void closePairing() {
    pairing = null;
    _poll?.cancel();
    _poll = null;
    _notify();
  }

  Future<void> revoke(String id) async {
    if (revokeArmed != id) {
      revokeArmed = id;
      _notify();
      return;
    }
    revokeArmed = null;
    await _run(() async {
      await _api.revokeDevice(id);
      state = await _api.getLan();
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    busy = true;
    error = null;
    _notify();
    try {
      await action();
    } catch (e) {
      error = errorText(e);
    } finally {
      busy = false;
      _notify();
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _poll?.cancel();
    super.dispose();
  }
}

/// `ab12cd34…` → `AB12 CD34 EF56 7890`: the start of the fingerprint, to
/// compare with what the phone shows.
String shortFingerprint(String fp) {
  final hex = fp.replaceAll(':', '').toUpperCase();
  final head = hex.length > 16 ? hex.substring(0, 16) : hex;
  return [for (var i = 0; i < head.length; i += 4) head.substring(i, (i + 4).clamp(0, head.length))].join(' ');
}

class LanCard extends StatefulWidget {
  const LanCard({super.key, required this.client, this.every});

  final AutoEditClient client;
  final Duration? every;

  @override
  State<LanCard> createState() => _LanCardState();
}

class _LanCardState extends State<LanCard> {
  late final LanController c;

  @override
  void initState() {
    super.initState();
    c = LanController(widget.client, every: widget.every ?? const Duration(seconds: 2));
    unawaited(c.load());
  }

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: c,
    builder: (context, _) {
      final s = c.state;
      final on = s?.enabled ?? false;
      return Panel(
        title: 'Celular (rede local)',
        subtitle: const Text(
          'Acompanhe e mande edições deste computador pelo celular, na mesma rede Wi-Fi. '
          'Cada aparelho pareado tem a sua chave, e dá pra revogar quando quiser.',
        ),
        trailing: s == null ? null : Switch(value: on, onChanged: c.busy ? null : (v) => unawaited(c.toggle(v))),
        children: [
          if (c.error != null) Notice(c.error!),
          if (s != null && on) ..._status(s),
          if (s != null && on && s.running) ...[
            const SizedBox(height: 12),
            if (c.pairing == null)
              Align(
                alignment: Alignment.centerLeft,
                child: SmallButton('Parear aparelho', primary: true, onPressed: c.busy ? null : c.pair),
              )
            else
              _PairingBox(pairing: c.pairing!, onClose: c.closePairing),
          ],
          if (s != null && s.devices.isNotEmpty) ...[
            const SizedBox(height: 14),
            const Text(
              'Aparelhos pareados',
              style: TextStyle(fontSize: 12.5, color: Tokens.dim, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 6),
            for (final d in s.devices)
              _DeviceRow(
                device: d,
                armed: c.revokeArmed == d.id,
                onRevoke: c.busy ? null : () => unawaited(c.revoke(d.id)),
              ),
          ],
        ],
      );
    },
  );

  List<Widget> _status(LanState s) {
    if (!s.running) {
      return [Notice(s.error ?? 'O acesso pela rede está ligado, mas não está ouvindo.')];
    }
    final where = s.addresses.isEmpty ? 'nenhuma rede encontrada' : '${s.addresses.first}:${s.port}';
    return [
      Text.rich(
        TextSpan(
          children: [
            const TextSpan(text: 'Ouvindo em '),
            TextSpan(
              text: where,
              style: const TextStyle(fontFamily: Tokens.mono, color: Tokens.text),
            ),
            const TextSpan(text: ' (HTTPS)'),
            if (!s.mdns) const TextSpan(text: '. Sem anúncio na rede: o celular acha o computador pelo QR.'),
          ],
        ),
        style: const TextStyle(fontSize: 13, color: Tokens.dim),
      ),
    ];
  }
}

class _PairingBox extends StatelessWidget {
  const _PairingBox({required this.pairing, required this.onClose});

  final Pairing pairing;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final until = DateTime.tryParse(pairing.expiresAt)?.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    final time = until == null ? '' : ' (até ${two(until.hour)}:${two(until.minute)})';
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10)),
          child: QrImageView(data: pairing.url, size: 180, padding: EdgeInsets.zero),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Escaneie com o app Auto-Edit no celular',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 6),
              Text(
                'O código vale por 5 minutos$time e uma vez só. Quando o celular parear, ele aparece na lista abaixo.',
                style: const TextStyle(fontSize: 13, color: Tokens.dim, height: 1.45),
              ),
              const SizedBox(height: 10),
              Text.rich(
                TextSpan(
                  children: [
                    const TextSpan(text: 'Certificado: '),
                    TextSpan(
                      text: shortFingerprint(pairing.fingerprint),
                      style: const TextStyle(fontFamily: Tokens.mono, color: Tokens.text),
                    ),
                  ],
                ),
                style: const TextStyle(fontSize: 12.5, color: Tokens.dim),
              ),
              const SizedBox(height: 12),
              SmallButton('Cancelar', onPressed: onClose),
            ],
          ),
        ),
      ],
    );
  }
}

class _DeviceRow extends StatelessWidget {
  const _DeviceRow({required this.device, required this.armed, required this.onRevoke});

  final LanDevice device;
  final bool armed;
  final VoidCallback? onRevoke;

  @override
  Widget build(BuildContext context) {
    final seen = device.lastSeen == null ? 'ainda não usou' : 'usado em ${when(device.lastSeen)}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          const Icon(Icons.smartphone_outlined, size: 18, color: Tokens.dim),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(device.name, style: const TextStyle(fontSize: 13.5)),
                Text(
                  'pareado em ${when(device.createdAt)} · $seen',
                  style: const TextStyle(fontSize: 12, color: Tokens.faint),
                ),
              ],
            ),
          ),
          DangerButton(armed ? 'Revogar mesmo' : 'Revogar', confirm: armed, onPressed: onRevoke),
        ],
      ),
    );
  }
}

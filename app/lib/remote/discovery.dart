import 'package:nsd/nsd.dart' as nsd;

/// An engine announcing itself on the network (`_autoedit._tcp`, auto_edit/lan.py).
class FoundEngine {
  const FoundEngine({required this.host, required this.port, required this.fingerprint, this.name});
  final String host;
  final int port;
  final String fingerprint;
  final String? name;
}

/// Finds engines on the network. The paired one is recognized by its
/// certificate's fingerprint: when the computer gets a new IP, the phone
/// finds it again without a new QR code.
abstract class Discovery {
  Future<List<FoundEngine>> scan({Duration wait});
}

class NsdDiscovery implements Discovery {
  const NsdDiscovery();

  @override
  Future<List<FoundEngine>> scan({Duration wait = const Duration(seconds: 3)}) async {
    final found = <FoundEngine>[];
    final discovery = await nsd.startDiscovery('_autoedit._tcp', ipLookupType: nsd.IpLookupType.v4);
    try {
      await Future<void>.delayed(wait);
      for (final s in discovery.services) {
        final ip = s.addresses?.firstOrNull?.address ?? s.host;
        final fp = s.txt?['fp'];
        if (ip == null || s.port == null || fp == null) continue;
        found.add(
          FoundEngine(
            host: ip,
            port: s.port!,
            fingerprint: String.fromCharCodes(fp),
            name: s.txt?['name'] == null ? s.name : String.fromCharCodes(s.txt!['name']!),
          ),
        );
      }
    } finally {
      await nsd.stopDiscovery(discovery);
    }
    return found;
  }
}

class NoDiscovery implements Discovery {
  const NoDiscovery([this.engines = const []]);
  final List<FoundEngine> engines;

  @override
  Future<List<FoundEngine>> scan({Duration wait = Duration.zero}) async => engines;
}

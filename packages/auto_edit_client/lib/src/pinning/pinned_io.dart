import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

/// An HTTP client that trusts exactly one certificate: the one whose SHA-256
/// (hex, of the DER) is [fingerprint]. No CA is trusted, so every
/// certificate goes through the check, even one a CA signed.
http.Client pinnedClient(String fingerprint) {
  final expected = fingerprint.replaceAll(':', '').toLowerCase();
  final io = HttpClient(context: SecurityContext(withTrustedRoots: false))
    ..badCertificateCallback = (cert, host, port) => sha256.convert(cert.der).toString() == expected;
  return IOClient(io);
}

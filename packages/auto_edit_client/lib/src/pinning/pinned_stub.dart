import 'package:http/http.dart' as http;

/// The browser decides which certificates to trust: no pinning on the web.
http.Client pinnedClient(String fingerprint) =>
    throw UnsupportedError('certificate pinning needs dart:io (desktop or phone)');
